"""Async ingestion job with background thread and status tracking."""

from __future__ import annotations

import threading
import time
from typing import Any

from app.ingestion.pipeline import run_ingestion as run_ingestion_sync
from app.retrieval.coordinator import prewarm_material_insights
from app.retrieval.insights import clear_material_insight_cache
from app.jobs.warm_cache import trigger_warm_cache_job
from app.core.config.settings import get_settings

_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "total_files": 0,
    "processed_files": 0,
    "indexed_chunks": 0,
    "source_dir": "",
    "files": [],
    "errors": [],
}
_CURRENT_RUN_TOKEN = 0


def run_ingestion_once(progress_callback=None) -> dict[str, Any]:
    """Run synchronous ingestion and return its report."""
    return run_ingestion_sync(progress_callback=progress_callback)


def run_post_ingestion_tasks() -> None:
    """Run cache/prewarm tasks after ingestion completes."""
    clear_material_insight_cache()
    prewarm_material_insights()
    settings = get_settings()
    if bool(getattr(settings, "warm_cache_enabled", True)):
        trigger_warm_cache_job(force=True)


def _set_status(**kwargs: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(kwargs)


def _append_error(message: str) -> None:
    with _STATUS_LOCK:
        errors = list(_STATUS.get("errors", []))
        errors.append(message)
        _STATUS["errors"] = errors[-10:]  # Keep last 10 errors


def get_ingestion_status() -> dict[str, Any]:
    """Get current ingestion job status."""
    with _STATUS_LOCK:
        return dict(_STATUS)


def _next_run_token() -> int:
    global _CURRENT_RUN_TOKEN
    with _STATUS_LOCK:
        _CURRENT_RUN_TOKEN += 1
        return _CURRENT_RUN_TOKEN


def _is_run_active(run_token: int) -> bool:
    with _STATUS_LOCK:
        return _CURRENT_RUN_TOKEN == run_token


def _run_ingestion_background(run_token: int) -> None:
    """Run ingestion in background thread and update status."""
    started = time.time()
    _set_status(
        state="running",
        started_at=int(started),
        finished_at=None,
        total_files=0,
        processed_files=0,
        indexed_chunks=0,
        files=[],
        errors=[],
    )
    
    try:
        if not _is_run_active(run_token):
            _set_status(state="cancelled", finished_at=int(time.time()))
            return
        
        def _progress_update(snapshot: dict[str, Any]) -> None:
            if not _is_run_active(run_token):
                return
            _set_status(
                state=str(snapshot.get("state", "running")),
                source_dir=str(snapshot.get("source_dir", "") or ""),
                total_files=int(snapshot.get("total_files", 0) or 0),
                processed_files=int(snapshot.get("processed_files", 0) or 0),
                indexed_chunks=int(snapshot.get("indexed_chunks", 0) or 0),
                files=list(snapshot.get("files", []) or []),
            )

        # Run the actual ingestion
        report = run_ingestion_once(progress_callback=_progress_update)
        
        if not _is_run_active(run_token):
            _set_status(state="cancelled", finished_at=int(time.time()))
            return
        
        # Extract stats from report
        processed = report.get("processed_files", 0) or 0
        chunks = report.get("indexed_chunks", 0) or 0
        source = report.get("source_dir", "") or ""
        
        _set_status(
            total_files=int(report.get("processed_files", 0) or 0),
            processed_files=processed,
            indexed_chunks=chunks,
            source_dir=source,
            files=list(report.get("files", []) or []),
            state="completed",
            finished_at=int(time.time()),
        )
        
        run_post_ingestion_tasks()
    
    except Exception as exc:
        _append_error(str(exc))
        _set_status(state="failed", finished_at=int(time.time()))


def trigger_ingestion_job() -> dict[str, Any]:
    """Trigger async ingestion job, return immediately with status."""
    status = get_ingestion_status()
    
    if status.get("state") == "running":
        return {
            "status": "already_running",
            "detail": status,
        }
    
    # Start background thread
    run_token = _next_run_token()
    thread = threading.Thread(
        target=_run_ingestion_background,
        args=(run_token,),
        daemon=True,
    )
    thread.start()
    
    return {
        "status": "started",
        "detail": get_ingestion_status(),
    }
