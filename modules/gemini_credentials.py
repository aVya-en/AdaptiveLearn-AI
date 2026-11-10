"""Thread-safe, process-local Gemini credential availability and reservations."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from utils.config import get_gemini_credentials, get_gemini_cooldown_seconds, get_gemini_max_cooldown_seconds

_condition = threading.Condition(threading.RLock())
_reserved: set[str] = set()
_unavailable_keys: dict[str, float] = {}
_unavailable_projects: dict[str, float] = {}
_unavailable_models: dict[tuple[str, str], float] = {}
_unavailable_project_models: dict[tuple[str, str], float] = {}
_failure_counts: dict[tuple[str, str], int] = {}
_unavailable_shared_unknown: float | None = None
_unavailable_unknown_scope: float | None = None
_quota_context_by_model: dict[str, dict[str, Any]] = {}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _configured(preferred_key: str | None = None) -> list[dict[str, Any]]:
    credentials = get_gemini_credentials()
    if preferred_key:
        match = next((row for row in credentials if row["key"] == preferred_key), None)
        if match:
            credentials.remove(match)
            credentials.insert(0, match)
        else:
            credentials.insert(0, {"key": preferred_key, "project_id": None})
    return credentials


def configured_credentials(preferred_key: str | None = None) -> list[dict[str, Any]]:
    """Return configured credential metadata in priority order."""
    return [row.copy() for row in _configured(preferred_key)]


def shared_quota_identity_unknown() -> bool:
    with _condition:
        return _unavailable_shared_unknown is not None and _unavailable_shared_unknown > time.time()


def quota_scope_unknown() -> bool:
    with _condition:
        return _unavailable_unknown_scope is not None and _unavailable_unknown_scope > time.time()


def quota_context(model: str) -> dict[str, Any] | None:
    """Return the latest unexpired sanitized quota classification for a model."""
    with _condition:
        context = _quota_context_by_model.get(model)
        if not context:
            return None
        if context["expires_at"] <= time.time():
            del _quota_context_by_model[model]
            return None
        return {key: value for key, value in context.items() if key != "expires_at"}


def _remember_quota_context(
    model: str | None, expiry: float, *, reported_scope: str | None,
    quota_type: str | None, temporary_rate_limit: bool, status_code: int | None,
    retry_delay_seconds: float | None,
) -> None:
    if model:
        _quota_context_by_model[model] = {
            "scope": reported_scope,
            "quota_type": quota_type,
            "temporary_rate_limit": temporary_rate_limit,
            "status_code": status_code or 429,
            "retry_delay_seconds": retry_delay_seconds,
            "expires_at": expiry,
        }


def _expire(now: float) -> None:
    for store in (_unavailable_keys, _unavailable_projects, _unavailable_models, _unavailable_project_models):
        for key, expiry in list(store.items()):
            if expiry <= now:
                del store[key]


def eligible_credentials(preferred_key: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    """Return currently eligible keys (reservation status is not considered)."""
    configured = _configured(preferred_key)
    now = time.time()
    with _condition:
        _expire(now)
        if _unavailable_shared_unknown is not None and _unavailable_shared_unknown > now:
            return []
        return [row for row in configured
                if _unavailable_keys.get(_fingerprint(row["key"]), 0) <= now
                and (not row.get("project_id") or _unavailable_projects.get(row["project_id"], 0) <= now)
                and (not model or _unavailable_models.get((_fingerprint(row["key"]), model), 0) <= now)
                and (not model or not row.get("project_id") or
                     _unavailable_project_models.get((row["project_id"], model), 0) <= now)]


def reserve_credential(
    preferred_key: str | None = None,
    *,
    model: str | None = None,
    excluded_keys: set[str] | None = None,
    wait_timeout: float = 30.0,
) -> dict[str, Any] | None:
    """Atomically reserve an eligible key, waiting briefly when all are in flight."""
    excluded = excluded_keys or set()
    configured = _configured(preferred_key)
    deadline = time.monotonic() + max(0.0, wait_timeout)
    with _condition:
        while True:
            now = time.time()
            _expire(now)
            if _unavailable_shared_unknown is not None and _unavailable_shared_unknown > now:
                return None
            eligible = [row for row in configured
                        if row["key"] not in excluded
                        and _unavailable_keys.get(_fingerprint(row["key"]), 0) <= now
                        and (not row.get("project_id") or _unavailable_projects.get(row["project_id"], 0) <= now)
                        and (not model or _unavailable_models.get((_fingerprint(row["key"]), model), 0) <= now)
                        and (not model or not row.get("project_id") or
                             _unavailable_project_models.get((row["project_id"], model), 0) <= now)]
            for row in eligible:
                fingerprint = _fingerprint(row["key"])
                if fingerprint not in _reserved:
                    _reserved.add(fingerprint)
                    return row.copy()
            has_inflight = any(_fingerprint(row["key"]) in _reserved for row in eligible)
            remaining = deadline - time.monotonic()
            if not has_inflight or remaining <= 0:
                return None
            _condition.wait(remaining)


def release_credential(credential: dict[str, Any]) -> None:
    with _condition:
        _reserved.discard(_fingerprint(credential["key"]))
        _condition.notify_all()


def record_success(credential: dict[str, Any], model: str) -> None:
    """Reset repeated-failure backoff after a successful provider response."""
    key_id = _fingerprint(credential["key"])
    with _condition:
        for failure_key in list(_failure_counts):
            if failure_key[1] == key_id or (
                credential.get("project_id") and failure_key == ("project", credential["project_id"])
            ) or (
                credential.get("project_id") and failure_key == ("project_model", f"{credential['project_id']}:{model}")
            ):
                del _failure_counts[failure_key]
        _failure_counts.pop(("shared_unknown", "pool"), None)
        _condition.notify_all()


def mark_unavailable(
    credential: dict[str, Any], cooldown_seconds: float | None, *,
    scope: str = "key", model: str | None = None,
    reported_scope: str | None = None, quota_type: str | None = None,
    temporary_rate_limit: bool = False, status_code: int | None = 429,
) -> float:
    """Apply bounded backoff at the narrowest known quota scope and release lease."""
    global _unavailable_shared_unknown, _unavailable_unknown_scope
    key_id = _fingerprint(credential["key"])
    project_id = credential.get("project_id")
    scope_id = "pool" if scope == "shared_unknown" else (
        project_id if scope in ("project", "project_model") and project_id else key_id
    )
    if scope == "project_model" and model:
        scope_id = f"{scope_id}:{model}"
    failure_key = (str(scope), str(scope_id))
    with _condition:
        failures = _failure_counts.get(failure_key, 0)
        fallback = min(get_gemini_cooldown_seconds() * (2 ** failures), get_gemini_max_cooldown_seconds())
        delay = fallback if cooldown_seconds is None else max(0.0, float(cooldown_seconds))
        expiry = time.time() + delay
        _remember_quota_context(
            model, expiry, reported_scope=reported_scope or scope, quota_type=quota_type,
            temporary_rate_limit=temporary_rate_limit, status_code=status_code,
            retry_delay_seconds=cooldown_seconds,
        )
        _failure_counts[failure_key] = failures + 1
        if scope == "shared_unknown":
            _unavailable_shared_unknown = expiry
        elif scope == "unknown":
            _unavailable_unknown_scope = expiry
            _unavailable_keys[key_id] = expiry
        elif scope == "project" and project_id:
            _unavailable_projects[project_id] = expiry
        elif scope == "project_model" and project_id and model:
            _unavailable_project_models[(project_id, model)] = expiry
        elif scope == "model_specific" and model:
            _unavailable_models[(key_id, model)] = expiry
        else:
            _unavailable_keys[key_id] = expiry
        _reserved.discard(key_id)
        _condition.notify_all()
        return expiry


def mark_model_cooldown(
    credential: dict[str, Any], model: str, cooldown_seconds: float | None,
    *, project_wide: bool = False,
    reported_scope: str | None = None, quota_type: str | None = None,
    temporary_rate_limit: bool = True, status_code: int | None = 429,
) -> float:
    """Mark just one model unavailable while retaining the active key lease."""
    key_id = _fingerprint(credential["key"])
    project_id = credential.get("project_id")
    scope = "project_model" if project_wide and project_id else "model_specific"
    scope_id = f"{project_id}:{model}" if scope == "project_model" else key_id
    failure_key = (scope, scope_id)
    with _condition:
        failures = _failure_counts.get(failure_key, 0)
        fallback = min(get_gemini_cooldown_seconds() * (2 ** failures), get_gemini_max_cooldown_seconds())
        delay = fallback if cooldown_seconds is None else max(0.0, float(cooldown_seconds))
        expiry = time.time() + delay
        _remember_quota_context(
            model, expiry, reported_scope=reported_scope or scope, quota_type=quota_type,
            temporary_rate_limit=temporary_rate_limit, status_code=status_code,
            retry_delay_seconds=cooldown_seconds,
        )
        _failure_counts[failure_key] = failures + 1
        if scope == "project_model":
            _unavailable_project_models[(project_id, model)] = expiry
        else:
            _unavailable_models[(key_id, model)] = expiry
        _condition.notify_all()
        return expiry


def earliest_retry_time(credentials: list[dict[str, Any]], model: str | None = None) -> float | None:
    """Return the soonest time any supplied credential can be used again."""
    with _condition:
        now = time.time()
        available_at: list[float] = []
        for row in credentials:
            key_id = _fingerprint(row["key"])
            expiries = [
                _unavailable_keys.get(key_id),
                _unavailable_projects.get(row.get("project_id")) if row.get("project_id") else None,
                _unavailable_models.get((key_id, model)) if model else None,
                _unavailable_project_models.get((row.get("project_id"), model))
                if model and row.get("project_id") else None,
            ]
            active = [expiry for expiry in expiries if expiry is not None and expiry > now]
            if _unavailable_shared_unknown is not None and _unavailable_shared_unknown > now:
                active.append(_unavailable_shared_unknown)
            # One credential is usable only after all of its applicable
            # cooldowns expire. The pool becomes usable at the earliest such
            # per-credential time.
            if not active:
                return None
            available_at.append(max(active))
        return min(available_at) if available_at else None


def clear_state() -> None:
    """Reset process-local state for isolated tests."""
    global _unavailable_shared_unknown, _unavailable_unknown_scope
    with _condition:
        _reserved.clear()
        _unavailable_keys.clear()
        _unavailable_projects.clear()
        _unavailable_models.clear()
        _unavailable_project_models.clear()
        _failure_counts.clear()
        _unavailable_shared_unknown = None
        _unavailable_unknown_scope = None
        _quota_context_by_model.clear()
        _condition.notify_all()
