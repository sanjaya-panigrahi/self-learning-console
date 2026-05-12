from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
import tempfile
import os

from app.core.config.settings import get_settings

_LOCK = Lock()

def _feedback_log_path() -> Path:
    settings = get_settings()
    return Path(settings.feedback_log_path)


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    records = data.get("records", []) if isinstance(data, dict) else []
    return records if isinstance(records, list) else []


def _save_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "count": len(records),
        "records": records,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def record_feedback(
    session_id: str,
    helpful: bool,
    *,
    query: str | None = None,
    retrieval_query: str | None = None,
    answer_model: str | None = None,
    answer_confidence: float | None = None,
    result_count: int | None = None,
    sources: list[str] | None = None,
    comment: str | None = None,
    answer: str | None = None,
) -> dict[str, Any]:
    path = _feedback_log_path()
    event = {
        "id": f"fb-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
        "timestamp": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "helpful": bool(helpful),
        "query": (query or "").strip(),
        "retrieval_query": (retrieval_query or "").strip(),
        "answer_model": (answer_model or "").strip(),
        "answer_confidence": answer_confidence,
        "result_count": result_count,
        "sources": sources or [],
        "comment": (comment or "").strip(),
    }

    with _LOCK:
        records = _load_records(path)
        records.append(event)
        _save_records(path, records)

    # Auto-file confident helpful answers to the wiki in a background thread
    if (
        helpful
        and answer
        and answer.strip()
        and query
        and query.strip()
        and (answer_confidence or 0.0) >= float(getattr(get_settings(), "wiki_auto_file_min_confidence", 0.8) or 0.8)
    ):
        def _file_to_wiki() -> None:
            try:
                from app.jobs.deploy_intelligence.wiki_writer import write_answer_page

                settings = get_settings()
                wiki_dir = Path(
                    getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki"
                )
                write_answer_page(
                    question=query,
                    answer=answer,
                    wiki_dir=wiki_dir,
                    confidence=answer_confidence or 0.0,
                    sources=sources,
                    session_id=session_id,
                    filed_by="auto-helpful",
                    trigger="feedback-auto-helpful",
                )
            except Exception:
                pass  # Do not fail the feedback call if wiki filing fails

        threading.Thread(target=_file_to_wiki, daemon=True).start()

    return {
        "status": "recorded",
        "id": event["id"],
        "session_id": session_id,
        "helpful": bool(helpful),
    }


def get_feedback_summary(limit: int = 200) -> dict[str, Any]:
    path = _feedback_log_path()
    records = _load_records(path)
    recent = records[-max(1, limit) :]

    helpful_count = sum(1 for item in recent if bool(item.get("helpful")))
    total = len(recent)
    not_helpful_count = total - helpful_count
    helpful_ratio = (helpful_count / total) if total else 0.0

    return {
        "total": total,
        "helpful": helpful_count,
        "not_helpful": not_helpful_count,
        "helpful_ratio": helpful_ratio,
        "latest": recent[-10:],
    }


def get_source_feedback_penalties(limit: int = 2000, min_events: int = 3) -> dict[str, float]:
    path = _feedback_log_path()
    records = _load_records(path)
    recent = records[-max(1, limit) :]

    by_source: dict[str, dict[str, int]] = {}
    for item in recent:
        if not isinstance(item, dict):
            continue
        helpful = bool(item.get("helpful"))
        sources = item.get("sources", [])
        if not isinstance(sources, list):
            continue
        unique_sources = {
            str(source).strip().lower()
            for source in sources
            if str(source).strip()
        }
        for source in unique_sources:
            metrics = by_source.setdefault(source, {"total": 0, "not_helpful": 0})
            metrics["total"] += 1
            if not helpful:
                metrics["not_helpful"] += 1

    penalties: dict[str, float] = {}
    for source, metrics in by_source.items():
        total = int(metrics.get("total", 0) or 0)
        not_helpful = int(metrics.get("not_helpful", 0) or 0)
        if total < max(1, min_events):
            continue
        not_helpful_ratio = not_helpful / total
        # Keep penalties moderate and bounded to avoid hard exclusion.
        penalties[source] = min(0.8, max(0.0, not_helpful_ratio * 0.7))

    return penalties
