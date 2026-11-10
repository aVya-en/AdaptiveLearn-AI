"""Small local timing helpers for diagnosing Streamlit page and database work."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import logging
import os
import re
from time import perf_counter
from typing import Any, Callable, Iterator, TypeVar

_LOGGER = logging.getLogger("adaptivelearn.performance")
_ENABLED = os.getenv("ADAPTIVELEARN_PERF_LOG", "1").strip().casefold() not in {"0", "false", "no"}
_LOGGER.setLevel(logging.INFO if _ENABLED else logging.CRITICAL)
_F = TypeVar("_F", bound=Callable[..., Any])


def _safe_label(value: str | None) -> str:
    if not value:
        return "na"
    return re.sub(r"[^A-Za-z0-9_.:/+-]", "_", value)[:96] or "na"


def log_performance_event(
    operation: str,
    duration_ms: float,
    *,
    provider: str | None = None,
    model: str | None = None,
    task: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    started_at_utc: str | None = None,
) -> None:
    """Log only bounded performance metadata; never pass prompts or user content."""
    if not _ENABLED:
        return
    completed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    _LOGGER.info(
        "event=performance operation=%s provider=%s model=%s task=%s "
        "started_at_utc=%s completed_at_utc=%s duration_ms=%.2f input_tokens=%s output_tokens=%s",
        _safe_label(operation), _safe_label(provider), _safe_label(model), _safe_label(task),
        started_at_utc or "na", completed_at, duration_ms,
        input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else "na",
        output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else "na",
    )


def _log_duration(
    operation: str,
    started: float,
    *,
    provider: str | None = None,
    model: str | None = None,
    task: str | None = None,
    started_at_utc: str | None = None,
) -> None:
    log_performance_event(
        operation, (perf_counter() - started) * 1000,
        provider=provider, model=model, task=task, started_at_utc=started_at_utc,
    )


@contextmanager
def measure_stage(
    operation: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    task: str | None = None,
) -> Iterator[dict[str, int | None]]:
    """Measure one stage and optionally attach provider token counts."""
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    metadata: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
    try:
        yield metadata
    finally:
        log_performance_event(
            operation,
            (perf_counter() - started) * 1000,
            provider=provider,
            model=model,
            task=task,
            input_tokens=metadata["input_tokens"],
            output_tokens=metadata["output_tokens"],
            started_at_utc=started_at,
        )


def measure_function(
    operation: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    task: str | None = None,
) -> Callable[[_F], _F]:
    """Measure a function without recording arguments or return values."""
    def decorate(function: _F) -> _F:
        @wraps(function)
        def measured(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            try:
                return function(*args, **kwargs)
            finally:
                _log_duration(
                    operation, started, provider=provider, model=model, task=task,
                    started_at_utc=started_at,
                )
        return measured  # type: ignore[return-value]
    return decorate


def finish_page_timer(timer: tuple[str, float]) -> None:
    """Log a page script's elapsed execution time."""
    page_name, started = timer
    _log_duration(f"page.{page_name}", started)
