"""Gemini-backed tutoring service and student-scoped chat state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import random
import re
import threading
import time
from typing import Any

from utils.config import get_gemini_api_key, get_gemini_fallback_model, get_gemini_model, gemini_credential_wait_seconds, load_configuration
from modules import gemini_credentials
from utils.performance import measure_function, measure_stage

logger = logging.getLogger(__name__)
FALLBACK_GEMINI_MODEL = "gemini-3.5-flash"
TRANSIENT_GEMINI_STATUSES = frozenset({503, 504})
PRIMARY_RETRY_DELAY_SECONDS = 0.5
MAX_RETRY_DELAY_SECONDS = 30.0
MAX_RATE_LIMIT_RETRIES = 2
MAX_TRANSIENT_RETRIES = 1
MAX_HISTORY_MESSAGES = 10

_usage_lock = threading.Lock()
_usage_counts = {
    "successful_api_calls": 0,
    "failed_api_calls": 0,
    "primary_model_requests": 0,
    "fallback_model_requests": 0,
    "cached_quiz_retrievals": 0,
    "quiz_cache_lookups": 0,
    "prompt_tokens_total": 0,
    "response_tokens_total": 0,
    "prompt_token_metadata_count": 0,
    "response_token_metadata_count": 0,
    "tutor_prompt_tokens_total": 0,
    "tutor_response_tokens_total": 0,
    "tutor_prompt_token_metadata_count": 0,
    "tutor_response_token_metadata_count": 0,
    "quiz_generation_prompt_tokens_total": 0,
    "quiz_generation_response_tokens_total": 0,
    "quiz_generation_prompt_token_metadata_count": 0,
    "quiz_generation_response_token_metadata_count": 0,
    "tutor_api_requests": 0,
    "tutor_successful_calls": 0,
    "tutor_failed_calls": 0,
    "quiz_generation_api_requests": 0,
    "quiz_generation_successful_calls": 0,
    "quiz_generation_failed_calls": 0,
    "diagnostic_api_requests": 0,
    "adaptive_api_requests": 0,
    "adaptive_successful_calls": 0,
    "adaptive_failed_calls": 0,
    "adaptive_prompt_tokens_total": 0,
    "adaptive_response_tokens_total": 0,
    "adaptive_prompt_token_metadata_count": 0,
    "adaptive_response_token_metadata_count": 0,
}


class _LazyGenAI:
    """Load the Google SDK only when a Gemini operation is actually requested."""

    def __getattr__(self, name: str) -> Any:
        from google import genai as sdk

        return getattr(sdk, name)


genai = _LazyGenAI()


def _load_genai_support() -> tuple[Any, Any]:
    """Import SDK error/config types and HTTP exceptions on demand."""
    from google.genai import errors, types
    import httpx

    return (errors, types), httpx


def record_cached_quiz_retrieval() -> None:
    """Increment the local, process-only count of reused generated quizzes."""
    with _usage_lock:
        _usage_counts["cached_quiz_retrievals"] += 1


def record_quiz_cache_lookup() -> None:
    """Count an eligible cache lookup without recording quiz or student data."""
    with _usage_lock:
        _usage_counts["quiz_cache_lookups"] += 1


def get_api_usage_stats() -> dict[str, int | float | None]:
    """Return local counters; token counts are unavailable when metadata was absent."""
    with _usage_lock:
        stats: dict[str, int | float | None] = dict(_usage_counts)
    prompt_count = int(stats["prompt_token_metadata_count"] or 0)
    response_count = int(stats["response_token_metadata_count"] or 0)
    stats["estimated_prompt_tokens"] = stats["prompt_tokens_total"] if prompt_count else None
    stats["estimated_response_tokens"] = stats["response_tokens_total"] if response_count else None
    stats["average_prompt_tokens"] = stats["prompt_tokens_total"] / prompt_count if prompt_count else None
    stats["average_response_tokens"] = stats["response_tokens_total"] / response_count if response_count else None
    for feature in ("tutor", "quiz_generation", "adaptive"):
        for token_type in ("prompt", "response"):
            count = int(stats[f"{feature}_{token_type}_token_metadata_count"] or 0)
            total = int(stats[f"{feature}_{token_type}_tokens_total"] or 0)
            stats[f"average_{feature}_{token_type}_tokens"] = total / count if count else None
    lookups = int(stats["quiz_cache_lookups"] or 0)
    stats["quiz_cache_hit_rate"] = (int(stats["cached_quiz_retrievals"] or 0) / lookups) if lookups else None
    return stats


def _record_api_request(model: str, feature: str = "tutor") -> None:
    with _usage_lock:
        model_counter = "fallback_model_requests" if model == get_gemini_fallback_model() else "primary_model_requests"
        _usage_counts[model_counter] += 1
        feature_key = {"tutor": "tutor_api_requests", "quiz": "quiz_generation_api_requests", "adaptive": "adaptive_api_requests"}.get(feature, "diagnostic_api_requests")
        _usage_counts[feature_key] += 1


def _record_api_outcome(success: bool, response: Any = None, feature: str = "tutor") -> None:
    with _usage_lock:
        _usage_counts["successful_api_calls" if success else "failed_api_calls"] += 1
        prefix = {"tutor": "tutor", "quiz": "quiz_generation", "adaptive": "adaptive"}.get(feature)
        if prefix:
            _usage_counts[f"{prefix}_{'successful_calls' if success else 'failed_calls'}"] += 1
        usage = getattr(response, "usage_metadata", None) if response is not None else None
        prompt_tokens = getattr(usage, "prompt_token_count", None)
        response_tokens = getattr(usage, "candidates_token_count", None)
        if isinstance(prompt_tokens, int):
            _usage_counts["prompt_tokens_total"] += prompt_tokens
            _usage_counts["prompt_token_metadata_count"] += 1
            prefix = {"tutor": "tutor", "quiz": "quiz_generation", "adaptive": "adaptive"}.get(feature)
            if prefix:
                _usage_counts[f"{prefix}_prompt_tokens_total"] += prompt_tokens
                _usage_counts[f"{prefix}_prompt_token_metadata_count"] += 1
        if isinstance(response_tokens, int):
            _usage_counts["response_tokens_total"] += response_tokens
            _usage_counts["response_token_metadata_count"] += 1
            prefix = {"tutor": "tutor", "quiz": "quiz_generation", "adaptive": "adaptive"}.get(feature)
            if prefix:
                _usage_counts[f"{prefix}_response_tokens_total"] += response_tokens
                _usage_counts[f"{prefix}_response_token_metadata_count"] += 1


class TutorServiceError(RuntimeError):
    """A safe, user-facing tutoring service error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        retry_delay_seconds: float | None = None,
        quota_scope: str | None = None,
        temporary_rate_limit: bool = False,
        quota_type: str | None = None,
        provider_model: str | None = None,
        transient: bool = False,
        error_type: str | None = None,
        primary_transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_delay_seconds = retry_delay_seconds
        self.quota_scope = quota_scope
        self.temporary_rate_limit = temporary_rate_limit
        self.quota_type = quota_type
        self.provider_model = provider_model
        self.transient = transient or status_code in TRANSIENT_GEMINI_STATUSES
        default_error_types = {
            400: "invalid_request",
            401: "authentication",
            403: "authentication",
            404: "model_not_found",
            429: "quota_or_rate_limit",
            500: "server_error",
            502: "server_error",
            503: "server_error",
            504: "server_error",
        }
        self.error_type = error_type or default_error_types.get(status_code, "service_error")
        self.primary_transient = primary_transient


class MissingAPIKeyError(TutorServiceError):
    """Raised when no Gemini API key is configured."""


@dataclass(frozen=True)
class ConnectionTestResult:
    """Structured result returned by the manual Gemini connection check."""

    success: bool
    message: str
    response: str | None = None
    status_code: int | str | None = None
    error_type: str | None = None

    def __str__(self) -> str:
        """Keep command-line display concise while retaining structured fields."""
        return self.message


@dataclass(frozen=True)
class GeminiModelInfo:
    """Public model metadata returned by the Gemini model-list diagnostic."""

    name: str
    display_name: str
    supports_generate_content: bool


def conversation_key(student_id: int | str) -> str:
    """Return the isolated session-state key for a student conversation."""
    return f"ai_tutor_conversation_{student_id}"


def tutor_request_fingerprint(
    question: str,
    history: Sequence[dict[str, str]],
    subject: str,
    topic: str,
    difficulty: str,
) -> str:
    """Hash a pending tutor turn locally for rerun deduplication; never log it."""
    body = json.dumps(
        {
            "question": question.strip(),
            "history": list(history),
            "subject": subject,
            "topic": topic,
            "difficulty": difficulty,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def get_student_conversation(
    session_state: MutableMapping[str, Any],
    student_id: int | str,
    subject: str,
    topic: str,
    difficulty: str,
) -> dict[str, Any]:
    """Get this student's conversation, resetting it when teaching context changes."""
    key = conversation_key(student_id)
    context = {"subject": subject, "topic": topic, "difficulty": difficulty}
    conversation = session_state.get(key)
    if not conversation or conversation.get("context") != context:
        conversation = {"context": context, "messages": []}
        session_state[key] = conversation
    return conversation


def build_system_instruction(
    subject: str, topic: str, difficulty: str, student_name: str | None = None
) -> str:
    """Build the tutor behavior and current learner context for Gemini."""
    learner = f" The learner's first name is {student_name.strip()}." if student_name and student_name.strip() else ""
    return f"""You are AdaptiveLearn AI, a patient university-level computer science tutor.
Teach {subject}, focusing on {topic}, at the {difficulty} level.{learner}

Teach for understanding: explain ideas in clear steps, use practical examples,
and include Python code when it helps. When asked, explain code line by line.
Ask a short conceptual check question when useful. Correct misconceptions kindly
and explain why. Adapt to the conversation so far and answer follow-up questions
using that context. Use Markdown headings, equations, and fenced code blocks
where useful. Do not claim the learner has mastered anything based on this chat.
If a request is unrelated to computer science learning, briefly steer it back to
the selected subject or topic."""


def build_contents(history: Sequence[dict[str, str]], question: str) -> list[dict[str, Any]]:
    """Convert stored chat turns and the current question to Gemini contents."""
    contents: list[dict[str, Any]] = []
    # Keep recent turns for follow-up coherence without resending an unbounded chat.
    for message in history[-MAX_HISTORY_MESSAGES:]:
        role = message.get("role")
        text = message.get("content", "").strip()
        if role in ("user", "assistant") and text:
            contents.append({"role": "user" if role == "user" else "model", "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": question.strip()}]})
    return contents


def _safe_error_diagnostics(error: Exception) -> str:
    """Return technical error fields without logging provider text or request data."""
    fields = [type(error).__name__]
    for attribute in ("code", "status", "errno"):
        value = getattr(error, attribute, None)
        if isinstance(value, (int, str)) and value:
            fields.append(f"{attribute}={value}")
    return " ".join(fields)


def _api_error_message(status: int | None, model: str, details: str = "") -> str:
    """Translate Gemini status codes into actionable, sanitized UI messages."""
    normalized_details = details.casefold()
    if "api_key_invalid" in normalized_details or "api key not valid" in normalized_details:
        return "Gemini rejected the configured API key. Set a valid Gemini API key in GEMINI_API_KEY_1 through GEMINI_API_KEY_3 in the environment or Streamlit secrets, then restart the app."
    if status == 401:
        return "Gemini rejected the API key (401). Check that the configured key is valid and has not been revoked."
    if status == 403:
        return "Gemini denied permission (403). Check that the configured API key is valid and that the Gemini API is enabled for its project."
    if status == 404:
        return f"Gemini could not find model '{model}' (404). Check GEMINI_MODEL and model access."
    if status == 429:
        return "Gemini reports a quota exhaustion or rate limit (429). Check the project quota and retry after the configured cooldown."
    if status == 400:
        return "Gemini rejected this request (400). Check the prompt and request configuration."
    if status in (500, 502, 503, 504):
        return f"Gemini is temporarily unavailable (HTTP {status}). Try again shortly."
    return f"Gemini API request failed (HTTP {status or 'unknown'}). See the application terminal for diagnostic details."


def _quota_diagnostics(error: Any) -> tuple[float | None, str | None, bool]:
    """Extract retry timing and conservative quota scope from GenAI error details."""
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return None, None, False
    encoded = str(details).casefold()
    retry_delay: float | None = None
    model_specific = False
    temporary = False

    def visit(value: Any) -> None:
        nonlocal retry_delay, model_specific, temporary
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).casefold()
                if key_text in {"retrydelay", "retry_delay"} and isinstance(item, (str, int, float)):
                    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|ms)?\s*", str(item), re.IGNORECASE)
                    if match:
                        value_seconds = float(match.group(1))
                        if (match.group(2) or "s").casefold() == "ms":
                            value_seconds /= 1000
                        retry_delay = value_seconds
                if key_text in {"quota_metric", "quota_limit", "metric", "limit"}:
                    quota_value = str(item).casefold()
                    if "model" in quota_value or "generate_content" in quota_value or "generatecontent" in quota_value:
                        model_specific = True
                if key_text in {"reason", "type", "quota_id"} and "rate" in str(item).casefold():
                    temporary = True
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(details)
    has_daily_window = any(term in encoded for term in ("per_day", "per-day", "per day", "perday", "daily", "requestsperday", "tokensperday"))
    explicit_rate_limit = any(term in encoded for term in ("rate_limit", "ratelimit", "per_minute", "per-minute", "per minute", "perminute", "requestsperminute", "tokensperminute"))
    temporary = temporary or (retry_delay is not None and not has_daily_window) or explicit_rate_limit
    if model_specific:
        scope = "project_model" if any(term in encoded for term in ("project", "per_project", "project-wide")) else "model_specific"
    elif any(term in encoded for term in ("project", "per_project", "project-wide")):
        scope = "shared"
    elif any(term in encoded for term in ("api key", "apikey", "per_key", "per_day", "per-day", "perday", "daily")):
        scope = "key"
    else:
        scope = "unknown"
    if has_daily_window:
        temporary = False
    return retry_delay, scope, temporary


def _parse_retry_delay(value: Any, *, allow_http_date: bool = False) -> float | None:
    """Parse a Gemini RetryInfo duration or Retry-After value, if present."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        delay = float(value)
        return delay if math.isfinite(delay) and delay >= 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|ms)?", text, re.IGNORECASE)
    if match:
        delay = float(match.group(1))
        if (match.group(2) or "s").casefold() == "ms":
            delay /= 1000
        return delay if math.isfinite(delay) else None
    if allow_http_date:
        try:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _provider_retry_delay(error: Any) -> float | None:
    """Read Google RetryInfo and HTTP Retry-After without treating 503 as quota."""
    delays: list[float] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold().replace("_", "") == "retrydelay":
                    delay = _parse_retry_delay(item)
                    if delay is not None:
                        delays.append(delay)
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(getattr(error, "details", None))
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if hasattr(headers, "get"):
        retry_after = headers.get("retry-after")
        if retry_after is None:
            retry_after = headers.get("Retry-After")
        header_delay = _parse_retry_delay(retry_after, allow_http_date=True)
        if header_delay is not None:
            delays.append(header_delay)
    return max(delays) if delays else None


def _is_transient_gemini_error(error: TutorServiceError) -> bool:
    """Identify retryable service/network failures, excluding quota and auth errors."""
    return error.status_code in TRANSIENT_GEMINI_STATUSES or error.transient


def _quota_type(details: Any) -> str | None:
    """Classify Google's quota dimension without relying on prose guesses."""
    encoded = str(details).casefold()
    if any(term in encoded for term in ("per_day", "per-day", "per day", "perday", "daily")):
        return "daily"
    if any(term in encoded for term in ("tokens_per_minute", "token_per_minute", "tokensperminute")) or (
        "tokens_per_" in encoded and "_per_minute" in encoded
    ):
        return "token_per_minute"
    if any(term in encoded for term in ("requests_per_minute", "request_per_minute", "requestsperminute")) or (
        "requests_per_" in encoded and "_per_minute" in encoded
    ):
        return "request_per_minute"
    return None


def _quota_condition_label(error: TutorServiceError) -> str:
    """Describe a 429 without repeating provider text or inventing its scope."""
    if error.quota_type == "daily":
        return "daily quota exhaustion"
    if error.quota_type in ("request_per_minute", "token_per_minute") or error.temporary_rate_limit:
        return "rate limit"
    if error.quota_scope in (None, "unknown"):
        return "rate limit or quota exhaustion"
    return "quota exhaustion"


def _quota_scope_label(error: TutorServiceError) -> str:
    scope = {
        "shared": "project-wide scope",
        "project": "project-wide scope",
        "project_model": "project/model-specific scope",
        "model_specific": "model-specific scope",
        "key": "credential-level scope",
        "unknown": "unknown scope",
        None: "unknown scope",
    }.get(error.quota_scope, "unknown scope")
    quota = {
        "request_per_minute": "requests-per-minute",
        "token_per_minute": "tokens-per-minute",
        "daily": "daily",
    }.get(error.quota_type)
    return f", {quota}, {scope}" if quota else f", {scope}"


def _quota_error_message(details: Any, scope: str | None, temporary: bool) -> str:
    """Describe a 429 conservatively using only fields supplied by Google."""
    encoded = str(details).casefold()
    daily = any(term in encoded for term in ("per_day", "per-day", "per day", "perday", "daily"))
    if daily:
        if scope == "shared":
            return "Gemini reports RESOURCE_EXHAUSTED (429) for a project-level daily quota."
        if scope == "key":
            return "Gemini reports RESOURCE_EXHAUSTED (429) for a credential-level daily quota."
        return "Gemini reports a daily quota exhaustion, but its scope is unknown; shared quota cannot be reliably inferred."
    if _quota_type(details) == "request_per_minute":
        return "Gemini reports a requests-per-minute rate limit (429)."
    if _quota_type(details) == "token_per_minute":
        return "Gemini reports a tokens-per-minute rate limit (429)."
    if temporary and scope in ("model_specific", "project_model"):
        return "Gemini reports a temporary model-specific rate limit (429). The request was retried with bounded delays and may use the configured fallback model."
    if scope == "shared":
        return "Gemini reports a project-level quota or rate limit (429)."
    if scope == "unknown":
        return "Gemini reports a rate limit or quota exhaustion (429), but quota scope is unknown; shared quota cannot be reliably inferred."
    if temporary:
        return "Gemini reports a temporary rate limit (429), but the provider response does not identify a model-specific quota. The request was retried with bounded delays; model fallback was not attempted."
    return "Gemini reports RESOURCE_EXHAUSTED (429): quota or rate limit exceeded. The provider response does not identify the limit scope; no model fallback was attempted. See sanitized provider details in the application terminal."


@measure_function("gemini.generate_content")
def _request_gemini(
    api_key: str,
    model: str,
    contents: str | list[dict[str, Any]],
    config: Any | None = None,
    feature: str = "tutor",
) -> Any:
    """Run one Gemini request and preserve useful, safely logged diagnostics."""
    (errors, types), httpx = _load_genai_support()
    _record_api_request(model, feature)
    try:
        with measure_stage(
            "provider.client_construction", provider="gemini", model=model, task=feature,
        ):
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=30_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        with measure_stage(
            "provider.request", provider="gemini", model=model, task=feature,
        ) as performance:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            usage = getattr(response, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", None)
            output_tokens = getattr(usage, "candidates_token_count", None)
            performance["input_tokens"] = input_tokens if isinstance(input_tokens, int) else None
            performance["output_tokens"] = output_tokens if isinstance(output_tokens, int) else None
        _record_api_outcome(True, response, feature)
        return response
    except errors.APIError as error:
        _record_api_outcome(False, feature=feature)
        status = getattr(error, "code", None)
        retry_delay, quota_scope, temporary_rate_limit = _quota_diagnostics(error) if status == 429 else (None, None, False)
        provider_retry_delay = _provider_retry_delay(error) if status == 429 or status in TRANSIENT_GEMINI_STATUSES else None
        if provider_retry_delay is not None:
            retry_delay = provider_retry_delay
        quota_type = _quota_type(getattr(error, "details", None)) if status == 429 else None
        logger.error(
            "Gemini API error status=%s provider_status=%s model=%s quota_scope=%s temporary_rate_limit=%s retry_delay_seconds=%s details=%s",
            status,
            getattr(error, "status", None),
            model,
            quota_scope,
            temporary_rate_limit,
            retry_delay,
            _safe_error_diagnostics(error),
        )
        message = _quota_error_message(getattr(error, "details", None), quota_scope, temporary_rate_limit) if status == 429 else _api_error_message(status, model, str(error))
        raise TutorServiceError(
            message,
            status_code=status,
            retry_delay_seconds=retry_delay,
            quota_scope=quota_scope,
            temporary_rate_limit=temporary_rate_limit,
            quota_type=quota_type,
            provider_model=model,
            transient=status in TRANSIENT_GEMINI_STATUSES,
            error_type=(
                "authentication" if status in (401, 403) else
                "quota_or_rate_limit" if status == 429 else
                "server_error" if status in TRANSIENT_GEMINI_STATUSES else
                "service_error"
            ),
        ) from None
    except (httpx.RequestError, TimeoutError, ConnectionError, OSError) as error:
        _record_api_outcome(False, feature=feature)
        is_timeout = isinstance(error, (httpx.TimeoutException, TimeoutError)) or "timeout" in type(error).__name__.casefold()
        error_type = "timeout" if is_timeout else "network_error"
        logger.error(
            "Gemini %s error model=%s type=%s details=%s",
            error_type,
            model,
            type(error).__name__,
            _safe_error_diagnostics(error),
        )
        message = (
            "Gemini request timed out. Please retry in a moment."
            if is_timeout else
            "Could not connect to Gemini. Check your network connection and try again."
        )
        raise TutorServiceError(message, transient=True, error_type=error_type) from None
    except Exception as error:
        _record_api_outcome(False, feature=feature)
        logger.error(
            "Unexpected Gemini client error model=%s type=%s details=%s",
            model,
            type(error).__name__,
            _safe_error_diagnostics(error),
        )
        raise TutorServiceError("Gemini encountered an unexpected error. See the application terminal for details.") from None


def _request_gemini_with_model_fallback(
    api_key: str,
    primary_model: str,
    contents: str | list[dict[str, Any]],
    config: Any | None = None,
    feature: str = "tutor",
) -> Any:
    """Retry a transient primary failure, then try Gemini fallback on the same key."""
    fallback_model = get_gemini_fallback_model()
    primary_error: TutorServiceError | None = None
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return _request_gemini(api_key, primary_model, contents, config, feature)
        except TutorServiceError as error:
            if error.status_code == 429 and error.quota_scope in ("model_specific", "project_model"):
                credential = next(
                    (row for row in gemini_credentials.configured_credentials(api_key) if row["key"] == api_key),
                    {"key": api_key, "project_id": None},
                )
                gemini_credentials.mark_model_cooldown(
                    credential, primary_model, error.retry_delay_seconds,
                    project_wide=error.quota_scope == "project_model",
                    reported_scope=error.quota_scope, quota_type=error.quota_type,
                    temporary_rate_limit=error.temporary_rate_limit, status_code=error.status_code,
                )
            retryable = _is_transient_gemini_error(error) or (
                error.status_code == 429 and error.temporary_rate_limit
            )
            if not retryable:
                raise
            primary_error = error
            retry_limit = MAX_RATE_LIMIT_RETRIES if error.status_code == 429 else MAX_TRANSIENT_RETRIES
            if attempt < retry_limit:
                delay = error.retry_delay_seconds
                if delay is not None and delay > MAX_RETRY_DELAY_SECONDS:
                    logger.warning(
                        "Gemini requested retry delay %.1fs, exceeding the %.1fs retry bound; skipping same-model retry",
                        delay,
                        MAX_RETRY_DELAY_SECONDS,
                    )
                    break
                if delay is None:
                    delay_cap = min(PRIMARY_RETRY_DELAY_SECONDS * (2 ** attempt), MAX_RETRY_DELAY_SECONDS)
                    delay = random.uniform(delay_cap / 2, delay_cap)
                logger.warning(
                    "Gemini primary model %s failed (%s); retry %s/%s in %.2f seconds",
                    primary_model,
                    error.status_code if error.status_code is not None else error.error_type,
                    attempt + 1,
                    retry_limit,
                    delay,
                )
                time.sleep(delay)
                continue
            break

    assert primary_error is not None
    can_fallback = _is_transient_gemini_error(primary_error) or (
        primary_error.status_code == 429
        and primary_error.temporary_rate_limit
        and primary_error.quota_scope in ("model_specific", "project_model")
    )
    if not can_fallback or primary_model == fallback_model:
        raise primary_error
    logger.warning(
        "Gemini primary model %s remained unavailable (%s); switching to %s",
        primary_model,
        primary_error.status_code if primary_error.status_code is not None else primary_error.error_type,
        fallback_model,
    )
    try:
        return _request_gemini(api_key, fallback_model, contents, config, feature)
    except TutorServiceError as error:
        if _is_transient_gemini_error(primary_error):
            error.primary_transient = True
        if _is_transient_gemini_error(error):
            logger.error(
                "Gemini primary and fallback models are unavailable; primary=%s primary_error=%s fallback=%s fallback_error=%s",
                primary_model,
                primary_error.error_type,
                fallback_model,
                error.status_code if error.status_code is not None else error.error_type,
            )
            raise TutorServiceError(
                f"Gemini is temporarily unavailable on both {primary_model} and {fallback_model}. Please retry in a moment.",
                status_code=error.status_code,
                retry_delay_seconds=error.retry_delay_seconds,
                quota_scope=error.quota_scope,
                temporary_rate_limit=error.temporary_rate_limit,
                quota_type=error.quota_type,
                provider_model=error.provider_model or fallback_model,
                transient=True,
                error_type=error.error_type,
                primary_transient=error.primary_transient,
            ) from None
        if error.primary_transient and error.status_code in (401, 403):
            # A key accepted by the primary model can still be rejected on the
            # fallback endpoint. Let the credential pool try its next key.
            raise
        raise


def _request_gemini_with_fallback(
    api_key: str,
    primary_model: str,
    contents: str | list[dict[str, Any]],
    config: Any | None = None,
    feature: str = "tutor",
) -> Any:
    """Use ordered Gemini credentials, rotating after recoverable provider failures."""
    configured = gemini_credentials.eligible_credentials(api_key, primary_model)
    if not configured:
        if not gemini_credentials.configured_credentials(api_key):
            raise MissingAPIKeyError("No Gemini API credentials are configured.")
        context = gemini_credentials.quota_context(primary_model)
        retry_at = gemini_credentials.earliest_retry_time(
            gemini_credentials.configured_credentials(api_key), primary_model
        )
        retry_text = f" Earliest known retry: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(retry_at))}." if retry_at else ""
        if context and context["scope"] in (None, "unknown"):
            identity_note = " Quota scope is unknown; shared quota cannot be reliably inferred."
        elif gemini_credentials.shared_quota_identity_unknown() or (
            context and context["scope"] == "shared"
            and any(not row.get("project_id") for row in gemini_credentials.configured_credentials(api_key))
        ):
            identity_note = " Project identity is not configured, so shared quota cannot be reliably inferred."
        elif not context and gemini_credentials.quota_scope_unknown():
            identity_note = " Quota scope is unknown; shared quota cannot be reliably inferred."
        else:
            identity_note = ""
        error_context = TutorServiceError(
            "", status_code=(context or {}).get("status_code", 429),
            quota_scope=(context or {}).get("scope"),
            quota_type=(context or {}).get("quota_type"),
            temporary_rate_limit=(context or {}).get("temporary_rate_limit", False),
        )
        raise TutorServiceError(
            f"Gemini {_quota_condition_label(error_context)} ({error_context.status_code}){_quota_scope_label(error_context)}: All configured Gemini credentials are temporarily unavailable." + identity_note + retry_text,
            status_code=error_context.status_code,
            retry_delay_seconds=(context or {}).get("retry_delay_seconds"),
            quota_scope=error_context.quota_scope,
            temporary_rate_limit=error_context.temporary_rate_limit,
            quota_type=error_context.quota_type,
            provider_model=primary_model,
        )
    last_error: TutorServiceError | None = None
    tried: set[str] = set()
    while True:
        credential = gemini_credentials.reserve_credential(
            api_key, model=primary_model, excluded_keys=tried, wait_timeout=gemini_credential_wait_seconds()
        )
        if credential is None:
            break
        tried.add(credential["key"])
        try:
            result = _request_gemini_with_model_fallback(
                credential["key"], primary_model, contents, config, feature
            )
            gemini_credentials.record_success(credential, primary_model)
            gemini_credentials.release_credential(credential)
            return result
        except TutorServiceError as error:
            last_error = error
            if _is_transient_gemini_error(error) or (
                error.primary_transient and error.status_code in (401, 403)
            ):
                # The model-level helper has already performed its bounded retry
                # and fallback. A server-side outage can still be credential
                # specific, so try each other configured credential once. A fallback
                # auth rejection after a transient primary failure is key-specific.
                gemini_credentials.release_credential(credential)
                continue
            if error.status_code != 429:
                gemini_credentials.release_credential(credential)
                raise
            scope = error.quota_scope
            if scope == "shared" and credential.get("project_id"):
                scope = "project"
            elif scope == "shared":
                # Without the provider's project identity, do not assume the
                # other configured credentials belong to the same quota
                # bucket. Cool this credential and let known independent keys
                # remain eligible.
                scope = "key"
            elif scope == "project_model" and not credential.get("project_id"):
                scope = "model_specific"
            gemini_credentials.mark_unavailable(
                credential, error.retry_delay_seconds, scope=scope or "unknown",
                model=error.provider_model or primary_model,
                reported_scope=error.quota_scope, quota_type=error.quota_type,
                temporary_rate_limit=error.temporary_rate_limit, status_code=error.status_code,
            )
        except BaseException:
            gemini_credentials.release_credential(credential)
            raise
    if last_error and last_error.status_code == 429:
        keys = gemini_credentials.configured_credentials(api_key)
        retry_at = gemini_credentials.earliest_retry_time(
            keys, last_error.provider_model or primary_model
        )
        retry_text = f" Earliest known retry: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(retry_at))}." if retry_at else ""
        if gemini_credentials.shared_quota_identity_unknown() or (
            last_error.quota_scope == "shared"
            and any(not row.get("project_id") for row in keys)
        ):
            identity_note = " Project identity is not configured, so shared quota cannot be reliably inferred."
        elif last_error.quota_scope in (None, "unknown"):
            identity_note = " Quota scope is unknown; shared quota cannot be reliably inferred."
        else:
            identity_note = ""
        raise TutorServiceError(
            f"Gemini {_quota_condition_label(last_error)} (429){_quota_scope_label(last_error)}: All configured Gemini credentials are temporarily unavailable." + identity_note + retry_text,
            status_code=429,
            retry_delay_seconds=last_error.retry_delay_seconds,
            quota_scope=last_error.quota_scope,
            temporary_rate_limit=last_error.temporary_rate_limit,
            quota_type=last_error.quota_type,
            provider_model=last_error.provider_model or primary_model,
        ) from None
    if last_error:
        raise last_error
    retry_at = gemini_credentials.earliest_retry_time(
        gemini_credentials.configured_credentials(api_key), primary_model
    )
    retry_text = f" Earliest known retry: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(retry_at))}." if retry_at else ""
    raise TutorServiceError(
        "All configured Gemini credentials are currently reserved or temporarily unavailable." + retry_text,
        status_code=429,
    )


def test_gemini_connection() -> ConnectionTestResult:
    """Test Gemini and return a concise, structured result instead of raising service errors."""
    try:
        load_configuration()
        api_key = get_gemini_api_key()
        if not api_key:
            raise MissingAPIKeyError("No Gemini API credentials are configured. Set one of GEMINI_API_KEY_1 through GEMINI_API_KEY_3 in the environment or Streamlit secrets.")
        model = get_gemini_model()
        response = _request_gemini_with_fallback(
            api_key,
            model,
            "Reply with exactly: Gemini connection successful.",
            feature="diagnostic",
        )
        answer = getattr(response, "text", None)
        if not isinstance(answer, str) or not answer.strip():
            logger.error("Gemini connection test returned an empty response; model=%s", model)
            raise TutorServiceError("Gemini returned an empty response during the connection test.")
        return ConnectionTestResult(
            success=True,
            message="Gemini connection successful.",
            response=answer.strip(),
        )
    except TutorServiceError as error:
        diagnostic = str(error)
        lowered = diagnostic.casefold()
        status_code: int | str | None = error.status_code
        error_type = error.error_type

        if status_code == "401/403" or "401/403" in diagnostic:
            status_code = "401/403"
            error_type = "authentication"
        elif status_code is None:
            status_match = re.search(r"\b(?:http\s*)?(400|401|403|404|429|500|502|503|504)\b", diagnostic, re.IGNORECASE)
            if status_match:
                status_code = int(status_match.group(1))
                status_type = {
                    400: "invalid_request",
                    401: "authentication",
                    403: "authentication",
                    404: "model_not_found",
                    429: "quota_or_rate_limit",
                    500: "server_error",
                    502: "server_error",
                    503: "server_error",
                    504: "server_error",
                }
                error_type = status_type[status_code]

        if "api key" in lowered or "api_key" in lowered:
            error_type = "authentication"
        elif "timed out" in lowered:
            error_type = "timeout"
        elif "could not connect to gemini" in lowered:
            error_type = "network_error"
        elif "empty response" in lowered:
            error_type = "empty_response"

        return ConnectionTestResult(
            success=False,
            message=diagnostic,
            status_code=status_code,
            error_type=error_type,
        )


def list_available_gemini_models() -> list[GeminiModelInfo]:
    """List models visible to the configured key and flag generateContent support."""
    load_configuration()
    api_key = get_gemini_api_key()
    if not api_key:
        raise MissingAPIKeyError("No Gemini API credentials are configured. Set one of GEMINI_API_KEY_1 through GEMINI_API_KEY_3 in the environment or Streamlit secrets.")

    (errors, types), httpx = _load_genai_support()
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000),
        )
        models = client.models.list()
        return [
            GeminiModelInfo(
                name=str(getattr(model, "name", "") or ""),
                display_name=str(getattr(model, "display_name", "") or ""),
                supports_generate_content=any(
                    str(action).casefold() == "generatecontent"
                    for action in (getattr(model, "supported_actions", None) or [])
                ),
            )
            for model in models
        ]
    except errors.APIError as error:
        status = getattr(error, "code", None)
        logger.error(
            "Gemini models.list API error status=%s details=%s",
            status,
            _safe_error_diagnostics(error),
        )
        raise TutorServiceError(_api_error_message(status, "model listing", str(error))) from None
    except (httpx.RequestError, TimeoutError, ConnectionError, OSError) as error:
        logger.error(
            "Gemini models.list network error type=%s details=%s",
            type(error).__name__,
            _safe_error_diagnostics(error),
        )
        raise TutorServiceError("Could not connect to Gemini to list models.") from None


def generate_tutor_response(
    question: str,
    history: Sequence[dict[str, str]],
    subject: str,
    topic: str,
    difficulty: str,
    student_name: str | None = None,
) -> str:
    """Request a grounded tutoring response from Gemini or raise a safe error."""
    load_configuration()
    model = get_gemini_model()
    with measure_stage("tutor.response_total", provider="gemini", model=model, task="tutor"):
        return _generate_tutor_response(question, history, subject, topic, difficulty, student_name)


def _generate_tutor_response(
    question: str,
    history: Sequence[dict[str, str]],
    subject: str,
    topic: str,
    difficulty: str,
    student_name: str | None = None,
) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise MissingAPIKeyError(
            "Gemini is not configured. Add a Gemini key to GEMINI_API_KEY_1 through GEMINI_API_KEY_3 in the environment or Streamlit secrets, then restart the app."
        )
    if not question.strip():
        raise TutorServiceError("Enter a question before sending.")

    model = get_gemini_model()
    (_errors, types), _httpx = _load_genai_support()
    with measure_stage("tutor.context_construction", provider="local", model=model, task="tutor"):
        contents = build_contents(history, question)
        system_instruction = build_system_instruction(subject, topic, difficulty, student_name)
        config = types.GenerateContentConfig(system_instruction=system_instruction)

    response = _request_gemini_with_fallback(
        api_key, model, contents, config, feature="tutor",
    )

    with measure_stage("tutor.response_processing", provider="local", model=model, task="tutor"):
        answer = getattr(response, "text", None)
        if not isinstance(answer, str) or not answer.strip():
            logger.error("Gemini tutor response was empty; model=%s", model)
            raise TutorServiceError("Gemini returned an empty response. Please try asking again.")
        return answer.strip()


def generate_structured_content(
    prompt: str, response_schema: dict[str, Any], feature: str = "quiz",
    *, max_output_tokens: int | None = None,
    usage_out: dict[str, int | None] | None = None,
) -> str:
    """Generate schema-constrained JSON through the shared Gemini configuration."""
    load_configuration()
    api_key = get_gemini_api_key()
    if not api_key:
        raise MissingAPIKeyError(
            "Gemini is not configured. Add a Gemini key to GEMINI_API_KEY_1 through GEMINI_API_KEY_3 in the environment or Streamlit secrets, then restart the app."
        )
    (_errors, types), _httpx = _load_genai_support()
    response = _request_gemini_with_fallback(
        api_key,
        get_gemini_model(),
        prompt,
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            **({"max_output_tokens": max_output_tokens} if max_output_tokens is not None else {}),
        ),
        feature=feature,
    )
    answer = getattr(response, "text", None)
    if not isinstance(answer, str) or not answer.strip():
        logger.error("Gemini structured response was empty; model=%s", get_gemini_model())
        raise TutorServiceError("Gemini returned an empty structured response. Please try again.")
    if usage_out is not None:
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None)
        response_tokens = getattr(usage, "candidates_token_count", None)
        usage_out.update({
            "input_tokens": prompt_tokens if isinstance(prompt_tokens, int) else None,
            "output_tokens": response_tokens if isinstance(response_tokens, int) else None,
        })
    return answer.strip()
