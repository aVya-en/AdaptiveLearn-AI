"""Adaptive task routing: explicitly enabled Groq first, Gemini fallback."""

from __future__ import annotations

import hashlib
import json
import logging
import copy
import re
import threading
import time
from concurrent.futures import Future
from typing import Any

from utils.config import get_gemini_model, get_groq_api_key, get_groq_model, groq_api_usage_allowed, load_configuration
from modules.ai_tutor import TutorServiceError, generate_structured_content
from utils.performance import measure_function, measure_stage

logger = logging.getLogger(__name__)
_usage_lock = threading.Lock()
_usage = {
    "groq_requests": 0, "groq_successes": 0, "groq_failures": 0,
    "gemini_primary_requests": 0, "gemini_fallbacks": 0,
    "groq_input_tokens": 0, "groq_output_tokens": 0,
    "groq_input_token_metadata_count": 0, "groq_output_token_metadata_count": 0,
}
_inflight_lock = threading.Lock()
_inflight: dict[str, Future[tuple[str, dict[str, Any]]]] = {}
_groq_cooldown_lock = threading.Lock()
_groq_cooldown_until = 0.0
_GROQ_MAX_COMPLETION_TOKENS = 1200
_GROQ_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 30.0
_GROQ_SCHEMA_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def get_adaptive_provider_usage() -> dict[str, int | None]:
    with _usage_lock:
        result = dict(_usage)
    result["groq_input_tokens"] = result["groq_input_tokens"] if result["groq_input_token_metadata_count"] else None
    result["groq_output_tokens"] = result["groq_output_tokens"] if result["groq_output_token_metadata_count"] else None
    return result


def _parse_retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    raw_delay = headers.get("retry-after") if hasattr(headers, "get") else None
    try:
        delay = float(raw_delay)
    except (TypeError, ValueError):
        return None
    return delay if delay >= 0 else None


def _set_groq_cooldown(delay: float) -> None:
    global _groq_cooldown_until
    with _groq_cooldown_lock:
        _groq_cooldown_until = max(_groq_cooldown_until, time.monotonic() + max(0.0, delay))


def _groq_in_cooldown() -> bool:
    with _groq_cooldown_lock:
        return _groq_cooldown_until > time.monotonic()


def _strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy and normalize JSON Schema types and strict-mode object requirements for Groq."""
    normalized = copy.deepcopy(schema)

    def normalize_type(value: Any) -> Any:
        if isinstance(value, str):
            values = [value]
            was_list = False
        elif isinstance(value, list):
            values = value
            was_list = True
        else:
            raise ValueError("Groq JSON Schema types must be strings or a list of strings.")
        result = []
        for item in values:
            if not isinstance(item, str) or item.casefold() not in _GROQ_SCHEMA_TYPES:
                raise ValueError("Groq JSON Schema contains an unsupported data type.")
            result.append(item.casefold())
        return result if was_list else result[0]

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "type" in node:
                node["type"] = normalize_type(node["type"])
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["additionalProperties"] = False
                # Groq strict mode requires every declared object field to be
                # required; optional fields should be represented as nullable.
                node["required"] = list(properties)
                for property_schema in properties.values():
                    visit(property_schema)
            for key in ("items", "anyOf", "oneOf", "allOf", "$defs", "definitions"):
                value = node.get(key)
                if isinstance(value, list):
                    for item in value:
                        visit(item)
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(normalized)
    return normalized


def _safe_provider_field(value: Any, prompt: str, *, limit: int = 160) -> str | None:
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return None
    for token in sorted(set(re.findall(r"[\w.+%'-]{3,}", prompt)), key=len, reverse=True):
        text = re.sub(re.escape(token), "[redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", text)
    text = re.sub(r"(?i)\b(?:gsk_[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{8,})\b", "[redacted]", text)
    return text[:limit]


def _safe_provider_label(value: Any) -> str | None:
    """Keep structured error labels to a non-content identifier character set."""
    if not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text or len(text) > 120 or not re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", text):
        return None
    return text


def _groq_error_details(error: Exception, prompt: str) -> dict[str, str | None]:
    """Extract only provider error fields; never include headers or request content."""
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        response = getattr(error, "response", None)
        try:
            body = response.json() if response is not None else None
        except Exception:
            body = None
    error_body = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(error_body, dict):
        error_body = {}
    return {
        "code": _safe_provider_label(error_body.get("code")),
        "type": _safe_provider_label(error_body.get("type")),
        "param": _safe_provider_label(error_body.get("param") or error_body.get("field")),
        "message": _safe_provider_field(error_body.get("message"), prompt, limit=320),
    }


@measure_function("adaptive.provider.groq_request")
def _groq_request(
    prompt: str, schema: dict[str, Any], task: str,
    *, max_completion_tokens: int = _GROQ_MAX_COMPLETION_TOKENS,
    usage_out: dict[str, int | None] | None = None,
) -> str:
    """Call Groq's official SDK once with schema-constrained chat completion."""
    key = get_groq_api_key()
    if not key:
        raise TutorServiceError("Groq is not configured.")

    try:
        groq_schema = _strict_json_schema(schema)
    except ValueError:
        raise TutorServiceError("The adaptive response schema is incompatible with Groq structured output.") from None
    model = get_groq_model()

    from groq import APIConnectionError, APIError, APIStatusError, Groq

    with _usage_lock:
        _usage["groq_requests"] += 1
        _usage[f"{task}_groq_requests"] = _usage.get(f"{task}_groq_requests", 0) + 1
    try:
        with measure_stage(
            "provider.client_construction", provider="groq", model=model, task=task,
        ):
            client = Groq(
                api_key=key,
                timeout=30.0,
                max_retries=0,
            )
        with measure_stage(
            "provider.request", provider="groq", model=model, task=task,
        ) as performance:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Return only the requested structured result. Use only supplied evidence."},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "adaptive_result", "strict": True,
                        "schema": groq_schema,
                    },
                },
                max_completion_tokens=max_completion_tokens,
                reasoning_effort="medium",
            )
            usage = getattr(completion, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            performance["input_tokens"] = prompt_tokens if isinstance(prompt_tokens, int) else None
            performance["output_tokens"] = completion_tokens if isinstance(completion_tokens, int) else None
        content = completion.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise TutorServiceError("Groq returned an empty response.")
        with measure_stage("adaptive.provider.response_parsing", provider="groq", model=model, task=task):
            json.loads(content)
        if usage_out is not None:
            usage_out.update({
                "input_tokens": prompt_tokens if isinstance(prompt_tokens, int) else None,
                "output_tokens": completion_tokens if isinstance(completion_tokens, int) else None,
            })
        with _usage_lock:
            _usage["groq_successes"] += 1
            if isinstance(prompt_tokens, int):
                _usage["groq_input_tokens"] += prompt_tokens
                _usage["groq_input_token_metadata_count"] += 1
            if isinstance(completion_tokens, int):
                _usage["groq_output_tokens"] += completion_tokens
                _usage["groq_output_token_metadata_count"] += 1
        return content
    except APIStatusError as error:
        status = error.status_code
        retry_after = _parse_retry_after(error)
        if status == 400:
            details = _groq_error_details(error, prompt)
            logger.error(
                "Groq request rejected status=400 provider_code=%s provider_type=%s provider_param=%s "
                "provider_message=%s model=%s task=%s structured_output=true",
                details["code"], details["type"], details["param"], details["message"], model, task,
            )
        if status == 429:
            _set_groq_cooldown(
                retry_after if retry_after is not None else _GROQ_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
            )
            message = "Groq rate limit or quota reached; using Gemini fallback."
        elif status == 401:
            message = "Groq rejected the API key (HTTP 401). Check the key and whether it is active."
        elif status == 403:
            message = "Groq denied permission (HTTP 403). Check model access and account permissions."
        elif status == 400:
            message = "Groq rejected the adaptive request (HTTP 400). Check the model and structured request schema."
        elif status == 404:
            message = "Groq could not find the configured model (HTTP 404). Check GROQ_MODEL and model access."
        elif status >= 500:
            message = f"Groq is temporarily unavailable (HTTP {status}); using Gemini fallback."
        else:
            message = f"Groq API request failed (HTTP {status})."
        with _usage_lock:
            _usage["groq_failures"] += 1
        raise TutorServiceError(message, status_code=status, retry_delay_seconds=retry_after) from None
    except APIConnectionError:
        with _usage_lock:
            _usage["groq_failures"] += 1
        raise TutorServiceError("Could not connect to Groq; using Gemini fallback.") from None
    except APIError as error:
        with _usage_lock:
            _usage["groq_failures"] += 1
        raise TutorServiceError("Groq returned an unexpected provider error.", status_code=getattr(error, "status_code", None)) from None
    except TutorServiceError:
        with _usage_lock:
            _usage["groq_failures"] += 1
        raise
    except (ValueError, KeyError, TypeError, IndexError):
        with _usage_lock:
            _usage["groq_failures"] += 1
        raise TutorServiceError("Groq returned a malformed structured response.") from None


@measure_function("adaptive.provider.request_total")
def _generate_adaptive_uncached(
    prompt: str, response_schema: dict[str, Any], task: str,
    *, output_token_limit: int | None = None,
    metadata_out: dict[str, Any] | None = None,
) -> str:
    load_configuration()
    groq_enabled = groq_api_usage_allowed() and bool(get_groq_api_key())
    groq_failed_recoverably = False
    provider_metadata: dict[str, Any] = {
        "provider": "gemini", "task": task, "fallback_used": False,
        "input_tokens": None, "output_tokens": None,
    }
    if groq_enabled and not _groq_in_cooldown():
        try:
            usage: dict[str, int | None] = {}
            content = _groq_request(
                prompt, response_schema, task,
                max_completion_tokens=output_token_limit or _GROQ_MAX_COMPLETION_TOKENS,
                usage_out=usage,
            )
            provider_metadata.update({
                "provider": "groq", "fallback_used": False,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            })
            if metadata_out is not None:
                metadata_out.update(provider_metadata)
            return content
        except TutorServiceError as error:
            recoverable = (
                error.status_code in (408, 409, 429, 498, 500, 502, 503, 504)
                or (error.status_code is None and "connect" in str(error).casefold())
            )
            if not recoverable:
                raise
            groq_failed_recoverably = True
            logger.warning(
                "Groq adaptive request failed recoverably; using Gemini fallback (status=%s, retry_after_seconds=%s)",
                error.status_code,
                error.retry_delay_seconds,
            )
    elif groq_enabled and _groq_in_cooldown():
        groq_failed_recoverably = True
        logger.info("Groq is in rate-limit cooldown; using Gemini fallback")
    with _usage_lock:
        _usage["gemini_fallbacks" if groq_failed_recoverably else "gemini_primary_requests"] += 1
    provider_metadata["fallback_used"] = groq_failed_recoverably
    gemini_usage: dict[str, int | None] = {}
    gemini_kwargs: dict[str, Any] = {"feature": "adaptive"}
    if output_token_limit is not None:
        gemini_kwargs["max_output_tokens"] = output_token_limit
    if metadata_out is not None:
        gemini_kwargs["usage_out"] = gemini_usage
    with measure_stage(
        "adaptive.gemini_fallback" if groq_failed_recoverably else "adaptive.gemini_primary",
        provider="gemini", model=get_gemini_model(), task=task,
    ) as performance:
        content = generate_structured_content(prompt, response_schema, **gemini_kwargs)
        performance["input_tokens"] = gemini_usage.get("input_tokens")
        performance["output_tokens"] = gemini_usage.get("output_tokens")
    if metadata_out is not None:
        provider_metadata.update({
            "input_tokens": gemini_usage.get("input_tokens"),
            "output_tokens": gemini_usage.get("output_tokens"),
        })
        metadata_out.update(provider_metadata)
    return content


def _generate_adaptive_coalesced(
    prompt: str, response_schema: dict[str, Any], task: str,
    *, student_scope: str | int | None,
    output_token_limit: int | None,
) -> tuple[str, dict[str, Any]]:
    if student_scope is None:
        metadata: dict[str, Any] = {}
        content = _generate_adaptive_uncached(
            prompt, response_schema, task,
            output_token_limit=output_token_limit, metadata_out=metadata,
        )
        return content, metadata
    identity = json.dumps(
        [str(student_scope), task, prompt, response_schema, output_token_limit],
        sort_keys=True, separators=(",", ":"),
    )
    request_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    with _inflight_lock:
        future = _inflight.get(request_key)
        is_owner = future is None
        if future is None:
            future = Future()
            _inflight[request_key] = future
    if not is_owner:
        content, metadata = future.result()
        return content, dict(metadata)
    try:
        metadata: dict[str, Any] = {}
        content = _generate_adaptive_uncached(
            prompt, response_schema, task,
            output_token_limit=output_token_limit, metadata_out=metadata,
        )
        result = (content, metadata)
        future.set_result(result)
        return content, dict(metadata)
    except BaseException as error:
        future.set_exception(error)
        raise
    finally:
        with _inflight_lock:
            _inflight.pop(request_key, None)


def generate_adaptive_content(
    prompt: str, response_schema: dict[str, Any], task: str = "adaptive",
    *, student_scope: str | int | None = None,
    output_token_limit: int | None = None,
) -> str:
    """Coalesce identical in-flight work only within the same student scope."""
    content, _metadata = _generate_adaptive_coalesced(
        prompt, response_schema, task,
        student_scope=student_scope, output_token_limit=output_token_limit,
    )
    return content


def generate_adaptive_content_with_metadata(
    prompt: str, response_schema: dict[str, Any], task: str,
    *, student_scope: str | int, output_token_limit: int,
) -> tuple[str, dict[str, Any]]:
    """Generate once through the adapter and return safe per-request metadata."""
    return _generate_adaptive_coalesced(
        prompt, response_schema, task,
        student_scope=student_scope, output_token_limit=output_token_limit,
    )
