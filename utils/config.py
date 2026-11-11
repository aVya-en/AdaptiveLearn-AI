"""Application configuration loaded from environment variables and Streamlit secrets."""

import os
import math
from pathlib import Path

from dotenv import load_dotenv
from utils.performance import measure_function

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "database" / "adaptivelearn.db"


@measure_function("configuration.load_environment")
def load_configuration() -> None:
    """Load optional local environment settings from the project .env file."""
    load_dotenv(PROJECT_ROOT / ".env")


def _get_streamlit_secret(name: str) -> object | None:
    """Return a Streamlit secret when available, without requiring a secrets file."""
    try:
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError

        return st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        return None


def _get_setting(name: str) -> str:
    """Read a setting from the environment first, then Streamlit secrets."""
    value = os.getenv(name, "").strip()
    if value:
        return value

    secret = _get_streamlit_secret(name)
    if secret is None:
        return ""
    return str(secret).strip()


def get_database_url() -> str | None:
    """Return the optional PostgreSQL URL from environment or Streamlit secrets."""
    return _get_setting("DATABASE_URL") or None


def get_gemini_api_key() -> str | None:
    """Return the first configured Gemini credential (legacy slot included)."""
    return next(iter(get_gemini_api_keys()), None)


def get_gemini_api_keys() -> list[str]:
    """Return configured key slots in priority order; empty slots are ignored."""
    values = [_get_setting(f"GEMINI_API_KEY_{slot}") for slot in (1, 2, 3)]
    legacy = _get_setting("GEMINI_API_KEY")
    if legacy and legacy not in values:
        values.append(legacy)
    return list(dict.fromkeys(value for value in values if value))


def get_gemini_credentials() -> list[dict[str, str | None]]:
    """Return ordered credentials with optional configured project identities."""
    credentials = []
    seen = set()
    for slot in (1, 2, 3):
        key = _get_setting(f"GEMINI_API_KEY_{slot}")
        if key and key not in seen:
            credentials.append({"key": key, "project_id": _get_setting(f"GEMINI_PROJECT_ID_{slot}") or None})
            seen.add(key)
    legacy = _get_setting("GEMINI_API_KEY")
    if legacy and legacy not in seen:
        credentials.append({"key": legacy, "project_id": _get_setting("GEMINI_PROJECT_ID") or None})
    return credentials


def get_gemini_model() -> str:
    """Return the configured Gemini model name."""
    return _get_setting("GEMINI_MODEL") or "gemini-3.6-flash"


def get_gemini_fallback_model() -> str:
    return _get_setting("GEMINI_FALLBACK_MODEL") or "gemini-3.5-flash"


def get_gemini_cooldown_seconds() -> float:
    return _positive_seconds(_get_setting("GEMINI_FALLBACK_COOLDOWN_SECONDS"), 30.0)


def get_gemini_max_cooldown_seconds() -> float:
    return max(get_gemini_cooldown_seconds(), _positive_seconds(_get_setting("GEMINI_MAX_COOLDOWN_SECONDS"), 900.0))


def gemini_credential_wait_seconds() -> float:
    return _positive_seconds(_get_setting("GEMINI_CREDENTIAL_WAIT_SECONDS"), 30.0)


def _positive_seconds(value: str, default: float) -> float:
    try:
        seconds = float(value)
    except ValueError:
        return default
    return seconds if seconds > 0 and math.isfinite(seconds) else default


def get_groq_api_key() -> str | None:
    return _get_setting("GROQ_API_KEY") or None


def get_groq_model() -> str:
    return _get_setting("GROQ_MODEL") or "openai/gpt-oss-120b"


def groq_api_usage_allowed() -> bool:
    """Require explicit opt-in before making any Groq API request."""
    return _get_setting("GROQ_ALLOW_API_USAGE").casefold() == "true"
