"""Application configuration loaded from environment variables."""

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


def get_gemini_api_key() -> str | None:
    """Return the first configured Gemini credential (legacy slot included)."""
    return next(iter(get_gemini_api_keys()), None)


def get_gemini_api_keys() -> list[str]:
    """Return configured key slots in priority order; empty slots are ignored."""
    values = [os.getenv(f"GEMINI_API_KEY_{slot}", "").strip() for slot in (1, 2, 3)]
    legacy = os.getenv("GEMINI_API_KEY", "").strip()
    if legacy and legacy not in values:
        values.append(legacy)
    return list(dict.fromkeys(value for value in values if value))


def get_gemini_credentials() -> list[dict[str, str | None]]:
    """Return ordered credentials with optional configured project identities."""
    credentials = []
    seen = set()
    for slot in (1, 2, 3):
        key = os.getenv(f"GEMINI_API_KEY_{slot}", "").strip()
        if key and key not in seen:
            credentials.append({"key": key, "project_id": os.getenv(f"GEMINI_PROJECT_ID_{slot}", "").strip() or None})
            seen.add(key)
    legacy = os.getenv("GEMINI_API_KEY", "").strip()
    if legacy and legacy not in seen:
        credentials.append({"key": legacy, "project_id": os.getenv("GEMINI_PROJECT_ID", "").strip() or None})
    return credentials


def get_gemini_model() -> str:
    """Return the configured Gemini model name."""
    return os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.6-flash"


def get_gemini_fallback_model() -> str:
    return os.getenv("GEMINI_FALLBACK_MODEL", "").strip() or "gemini-3.5-flash"


def get_gemini_cooldown_seconds() -> float:
    return _positive_seconds("GEMINI_FALLBACK_COOLDOWN_SECONDS", 30.0)


def get_gemini_max_cooldown_seconds() -> float:
    return max(get_gemini_cooldown_seconds(), _positive_seconds("GEMINI_MAX_COOLDOWN_SECONDS", 900.0))


def gemini_credential_wait_seconds() -> float:
    return _positive_seconds("GEMINI_CREDENTIAL_WAIT_SECONDS", 30.0)


def _positive_seconds(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 and math.isfinite(value) else default


def get_groq_api_key() -> str | None:
    return os.getenv("GROQ_API_KEY", "").strip() or None


def get_groq_model() -> str:
    return os.getenv("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b"


def groq_api_usage_allowed() -> bool:
    """Require explicit opt-in before making any Groq API request."""
    return os.getenv("GROQ_ALLOW_API_USAGE", "").strip().casefold() == "true"
