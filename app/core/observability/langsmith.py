from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config.settings import get_settings

logger = logging.getLogger(__name__)
_trace_file_lock = threading.Lock()

try:
    from langsmith import traceable as _ls_traceable
except Exception:  # pragma: no cover - optional dependency fallback
    try:
        from langsmith.run_helpers import traceable as _ls_traceable  # type: ignore
    except Exception:  # pragma: no cover - optional dependency fallback
        _ls_traceable = None


def _is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.langsmith_enabled and settings.langsmith_tracing)


def _is_local_trace_enabled() -> bool:
    settings = get_settings()
    return bool(getattr(settings, "local_trace_log_enabled", False))


def _resolve_local_trace_path() -> Path:
    settings = get_settings()
    configured = Path(getattr(settings, "local_trace_log_path", "data/traces/trace_events.jsonl"))
    if configured.is_absolute():
        return configured
    project_root = Path(__file__).resolve().parents[3]
    return (project_root / configured).resolve(strict=False)


def _append_local_trace(event: dict[str, Any]) -> None:
    if not _is_local_trace_enabled():
        return
    try:
        trace_path = _resolve_local_trace_path()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"
        with _trace_file_lock:
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception as exc:
        logger.debug("Failed to write local trace event: %s", exc)


def emit_local_observability_event(event: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a lightweight custom observability event into local trace storage."""

    if not _is_local_trace_enabled():
        return

    custom_event = {
        "event": event,
        "kind": "custom",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }
    if payload:
        custom_event.update(payload)

    _append_local_trace(custom_event)


def _sync_env() -> None:
    settings = get_settings()
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    if settings.langsmith_project:
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"


def configure_langsmith() -> bool:
    """Synchronize LangSmith environment for SDK usage.

    Returns True when tracing is enabled, otherwise False.
    """

    if not _is_enabled():
        return False
    _sync_env()
    return True


def get_langsmith_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": bool(settings.langsmith_enabled),
        "tracing": bool(settings.langsmith_tracing),
        "configured": bool(settings.langsmith_enabled and settings.langsmith_tracing and settings.langsmith_api_key),
        "api_key_present": bool(settings.langsmith_api_key),
        "project": settings.langsmith_project,
        "endpoint": settings.langsmith_endpoint,
        "local_trace_log_enabled": bool(getattr(settings, "local_trace_log_enabled", False)),
        "local_trace_log_path": str(_resolve_local_trace_path()),
    }


def _as_mapping_value(run: Any, key: str) -> Any:
    if isinstance(run, dict):
        return run.get(key)
    return getattr(run, key, None)


def _to_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_langsmith_traces(limit: int = 10) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.langsmith_enabled or not settings.langsmith_tracing or not settings.langsmith_api_key:
        return []

    try:
        from langsmith import Client
    except Exception:
        logger.warning("LangSmith Client is not available; cannot fetch traces.")
        return []

    _sync_env()
    safe_limit = max(1, min(int(limit), 50))

    traces: list[dict[str, Any]] = []
    try:
        client = Client(api_key=settings.langsmith_api_key, api_url=settings.langsmith_endpoint)
        runs = client.list_runs(project_name=settings.langsmith_project, limit=safe_limit)

        for run in runs:
            run_id = str(_as_mapping_value(run, "id") or "").strip()
            if not run_id:
                continue

            start_time = _as_mapping_value(run, "start_time")
            end_time = _as_mapping_value(run, "end_time")
            error = _as_mapping_value(run, "error")

            duration_ms: float | None = None
            if start_time is not None and end_time is not None:
                try:
                    duration_ms = max(0.0, float((end_time - start_time).total_seconds() * 1000.0))
                except Exception:
                    duration_ms = None

            status = "running"
            if error:
                status = "error"
            elif end_time is not None:
                status = "success"

            traces.append(
                {
                    "id": run_id,
                    "name": str(_as_mapping_value(run, "name") or "unnamed").strip() or "unnamed",
                    "status": status,
                    "created_at": _to_iso(start_time),
                    "duration_ms": duration_ms,
                }
            )
    except Exception as exc:
        logger.warning("Failed to fetch LangSmith traces: %s", exc)
        return []

    return traces


def get_local_trace_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent local trace events from JSONL file.

    Reads the configured local trace file when local tracing is enabled.
    Invalid JSON lines are ignored so one bad entry does not break debugging.
    """

    settings = get_settings()
    if not bool(getattr(settings, "local_trace_log_enabled", False)):
        return []

    safe_limit = max(1, min(int(limit), 500))
    trace_path = _resolve_local_trace_path()
    if not trace_path.exists() or not trace_path.is_file():
        return []

    try:
        lines = trace_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    recent = lines[-safe_limit:]
    events: list[dict[str, Any]] = []
    for line in recent:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def traceable(
    name: str,
    run_type: str = "chain",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Return LangSmith traceable decorator when enabled, otherwise no-op.

    This keeps instrumentation safe in local/dev setups where LangSmith is not configured.
    """

    def _decorate_with_local_trace(func: Callable[..., Any]) -> Callable[..., Any]:
        if not _is_local_trace_enabled():
            return func

        def _base_event_for(func_obj: Callable[..., Any], trace_id: str, started_at: str) -> dict[str, Any]:
            return {
                "trace_id": trace_id,
                "name": name,
                "run_type": run_type,
                "tags": tags or [],
                "metadata": metadata or {},
                "function": f"{func_obj.__module__}.{func_obj.__qualname__}",
                "started_at": started_at,
                "pid": os.getpid(),
            }

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def _wrapped_async(*args: Any, **kwargs: Any) -> Any:
                trace_id = str(uuid.uuid4())
                start = time.perf_counter()
                started_at = datetime.now(timezone.utc).isoformat()
                base_event = _base_event_for(func, trace_id, started_at)
                _append_local_trace({**base_event, "event": "start"})

                try:
                    result = await func(*args, **kwargs)
                    duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
                    _append_local_trace(
                        {
                            **base_event,
                            "event": "end",
                            "duration_ms": round(duration_ms, 3),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    return result
                except Exception as exc:
                    duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
                    _append_local_trace(
                        {
                            **base_event,
                            "event": "error",
                            "duration_ms": round(duration_ms, 3),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )
                    raise

            return _wrapped_async

        @functools.wraps(func)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            trace_id = str(uuid.uuid4())
            start = time.perf_counter()
            started_at = datetime.now(timezone.utc).isoformat()
            base_event = _base_event_for(func, trace_id, started_at)
            _append_local_trace({**base_event, "event": "start"})

            try:
                result = func(*args, **kwargs)
                duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
                _append_local_trace(
                    {
                        **base_event,
                        "event": "end",
                        "duration_ms": round(duration_ms, 3),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                return result
            except Exception as exc:
                duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
                _append_local_trace(
                    {
                        **base_event,
                        "event": "error",
                        "duration_ms": round(duration_ms, 3),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
                raise

        return _wrapped

    def _decorate_with_langsmith(func: Callable[..., Any]) -> Callable[..., Any]:
        if not _is_enabled() or _ls_traceable is None:
            return func
        _sync_env()
        return _ls_traceable(name=name, run_type=run_type, tags=tags, metadata=metadata)(func)

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        decorated = _decorate_with_local_trace(func)
        decorated = _decorate_with_langsmith(decorated)
        return decorated

    return _decorator
