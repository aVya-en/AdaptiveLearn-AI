"""Safe, one-request-per-credential provider connectivity diagnostics."""

from __future__ import annotations

import argparse
import logging
import os
import re
from typing import Any

from utils.config import (
    get_gemini_model,
    get_groq_api_key,
    get_groq_model,
    groq_api_usage_allowed,
    load_configuration,
)


def _project_groups(project_ids: list[str]) -> list[str]:
    labels: dict[str, str] = {}
    output = []
    for project_id in project_ids:
        if not project_id:
            output.append("project ID not configured")
        else:
            labels.setdefault(project_id, f"project group {len(labels) + 1}")
            output.append(labels[project_id])
    return output


def _safe_groq_error_fields(body: Any, api_key: str) -> dict[str, str]:
    """Return short, sanitized error metadata without including raw responses."""
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    fields = error if isinstance(error, dict) else body
    result: dict[str, str] = {}
    for name in ("code", "type"):
        value = fields.get(name)
        if isinstance(value, (str, int)):
            safe_value = re.sub(r"[^A-Za-z0-9_.-]", "", str(value))[:64]
            if safe_value:
                result[name] = safe_value
    message = fields.get("message")
    if isinstance(message, str):
        message = message.replace(api_key, "[redacted]")
        message = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", message)
        message = re.sub(r"\bgsk_[A-Za-z0-9_-]{8,}\b", "[redacted]", message)
        message = " ".join("".join(char for char in message if char.isprintable()).split())
        if message:
            result["message"] = message[:240]
    return result


def _test_gemini_slot(api_key: str, model: str) -> str:
    """Make one small request without touching credential-manager state."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15_000))
        client.models.generate_content(
            model=model,
            contents="Reply with OK only.",
            config=types.GenerateContentConfig(max_output_tokens=8),
        )
        return "success"
    except Exception as error:
        status = getattr(error, "code", None)
        if isinstance(status, int):
            if status == 401:
                return "authentication failure"
            if status == 403:
                return "permission failure"
            if status == 429:
                return "quota exhaustion or rate limit"
            if status == 404:
                return "model error"
            if status >= 500:
                return "network/server failure"
            return "provider request error"
        return "network/server failure"


def _test_groq(api_key: str, model: str) -> dict[str, Any]:
    """Make exactly one small Groq SDK chat-completions request."""
    from groq import APIConnectionError, APIStatusError, Groq

    try:
        client = Groq(
            api_key=api_key,
            timeout=15.0,
            max_retries=0,
        )
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK only."}],
            max_completion_tokens=32,
        )
        return {"result": "success"}
    except APIStatusError as error:
        status = error.status_code
        if status == 401:
            result = "authentication failure"
        elif status == 403:
            result = "permission failure"
        elif status == 429:
            result = "rate limit or quota exhaustion"
        elif status == 404:
            result = "model error"
        elif status in (400, 422):
            result = "model/request error"
        elif status >= 500:
            result = "network/server failure"
        else:
            result = "provider failure"
        return {
            "status": status,
            "result": result,
            **_safe_groq_error_fields(getattr(error, "body", None), api_key),
        }
    except APIConnectionError:
        return {"status": None, "result": "network/server failure"}
    except Exception:
        return {"status": None, "result": "provider failure"}


def collect_provider_diagnostics(*, test_gemini: bool = True) -> dict[str, Any]:
    load_configuration()
    keys = [os.getenv(f"GEMINI_API_KEY_{slot}", "").strip() for slot in (1, 2, 3)]
    projects = [os.getenv(f"GEMINI_PROJECT_ID_{slot}", "").strip() for slot in (1, 2, 3)]
    groups = _project_groups(projects)
    gemini_model = get_gemini_model()
    gemini_slots = []
    for slot, (key, project_group) in enumerate(zip(keys, groups), start=1):
        result = (
            _test_gemini_slot(key, gemini_model)
            if key and test_gemini
            else "not configured" if not key
            else "not tested"
        )
        gemini_slots.append({
            "slot": slot,
            "configured": bool(key),
            "project_id_configured": bool(projects[slot - 1]),
            "project_group": project_group,
            "result": result,
        })

    groq_key = get_groq_api_key()
    groq_allowed = groq_api_usage_allowed()
    if not groq_key:
        groq = {"configured": False, "enabled": groq_allowed, "tested": False, "result": "not configured"}
    elif not groq_allowed:
        groq = {"configured": True, "enabled": False, "tested": False, "result": "disabled; explicit opt-in required"}
    else:
        groq = {
            "configured": True,
            "enabled": True,
            "tested": True,
            **_test_groq(groq_key, get_groq_model()),
        }
    return {
        "gemini_model": gemini_model,
        "gemini_slots": gemini_slots,
        "groq_model_configured": bool(os.getenv("GROQ_MODEL", "").strip()),
        "groq_model": get_groq_model(),
        "groq_allow_api_usage": groq_allowed,
        "groq": groq,
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description="Safe one-request AI provider diagnostics")
    parser.add_argument("--groq-only", action="store_true", help="test Groq without sending Gemini requests")
    arguments = parser.parse_args()
    report = collect_provider_diagnostics(test_gemini=not arguments.groq_only)
    print(f"Gemini model: {report['gemini_model']}")
    for slot in report["gemini_slots"]:
        print(
            f"Gemini slot {slot['slot']}: configured={slot['configured']}; "
            f"project ID configured={slot['project_id_configured']}; "
            f"{slot['project_group']}; result={slot['result']}"
        )
    print(
        f"Groq: configured={report['groq']['configured']}; enabled={report['groq']['enabled']}; "
        f"tested={report['groq']['tested']}; model={report['groq_model']}"
    )
    for field in ("status", "code", "type", "message", "result"):
        if report["groq"].get(field) is not None:
            print(f"Groq {field}: {report['groq'][field]}")
    print("Matching configured project IDs can share applicable project quota; quota limits may also vary by model and dimension.")


if __name__ == "__main__":
    main()
