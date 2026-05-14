"""Background job: pre-seed semantic cache from suggested questions.

For every document in the material-insight cache, retrieves the existing
``suggested_questions`` list and runs each through the live retrieval
pipeline.  The retrieval service writes the answer to the semantic cache
automatically on every search, so subsequent identical (or semantically
similar) queries are served instantly from cache without hitting the LLM.

This is intentionally a light-weight job — it only calls
``search_retrieval_material`` which already handles:
  - semantic-cache lookup (skip if already cached)
  - retrieval + synthesis
  - semantic-cache write-back

The job therefore respects the existing ``force`` flag on the semantic
cache: if an entry already exists it is not re-written unless the caller
explicitly clears the cache first.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config.settings import get_settings
from app.retrieval.insight.cache import _cache_dir, _INSIGHT_CACHE_VERSION
from app.retrieval.service import search_retrieval_material

_JOB_LOCK = threading.Lock()
_JOB_RUNNING = False


def _load_all_insight_files() -> list[dict[str, Any]]:
    """Return all valid insight cache entries that have suggested_questions."""
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            # Disk format: {"cached_at": ..., "payload": {...}}
            payload = data.get("payload")
            if not isinstance(payload, dict):
                continue
            questions = payload.get("suggested_questions") or []
            source = payload.get("source") or ""
            if not source or not questions:
                continue
            entries.append({"source": source, "suggested_questions": list(questions)})
        except Exception:
            continue
    return entries


def _seed_question(source: str, question: str) -> dict[str, Any]:
    """Run one question through retrieval, which auto-writes to semantic cache."""
    try:
        result = search_retrieval_material(
            query=question,
            domain_context="",
            top_k=5,
        )
        answer = str(result.get("answer", "")).strip()
        cached = bool(result.get("semantic_cache_hit") or result.get("cached"))
        return {
            "source": source,
            "question": question,
            "answer_length": len(answer),
            "was_cached": cached,
            "ok": bool(answer),
        }
    except Exception as exc:
        return {
            "source": source,
            "question": question,
            "ok": False,
            "error": str(exc)[:200],
        }


def run_seed_suggested_questions(
    force: bool = False,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Seed semantic cache with answers for all suggested questions.

    Args:
        force: If True, clear semantic cache before seeding so all questions
               are re-fetched.  If False (default), already-cached questions
               are skipped by the retrieval service automatically.
        concurrency: Number of parallel retrieval calls.

    Returns:
        Summary dict with counts of sources, questions, cached entries, errors.
    """
    global _JOB_RUNNING

    with _JOB_LOCK:
        if _JOB_RUNNING:
            return {"status": "already_running"}
        _JOB_RUNNING = True

    started_at = time.time()
    try:
        if force:
            from app.retrieval.service.semantic_cache import clear_semantic_cache
            clear_semantic_cache()

        entries = _load_all_insight_files()
        if not entries:
            return {
                "status": "no_insights_found",
                "detail": "No insight cache entries found. Run material insight on documents first.",
                "sources_processed": 0,
                "questions_found": 0,
                "answers_cached": 0,
                "skipped": 0,
                "errors": 0,
                "error_details": [],
                "elapsed_seconds": round(time.time() - started_at, 1),
            }

        all_tasks: list[tuple[str, str]] = []
        for entry in entries:
            source = entry["source"]
            for question in entry["suggested_questions"]:
                q = str(question).strip()
                if q:
                    all_tasks.append((source, q))

        answers_cached = 0
        skipped = 0
        errors = 0
        error_details: list[str] = []

        effective_concurrency = max(1, min(int(concurrency), 8))

        with concurrent.futures.ThreadPoolExecutor(max_workers=effective_concurrency) as pool:
            futures = {
                pool.submit(_seed_question, source, question): (source, question)
                for source, question in all_tasks
            }
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if not result.get("ok"):
                    errors += 1
                    if result.get("error"):
                        error_details.append(f"{result['source']}: {result['error']}")
                elif result.get("was_cached"):
                    skipped += 1
                else:
                    answers_cached += 1

        return {
            "status": "ok",
            "sources_processed": len(entries),
            "questions_found": len(all_tasks),
            "answers_cached": answers_cached,
            "skipped": skipped,
            "errors": errors,
            "error_details": error_details[:10],
            "elapsed_seconds": round(time.time() - started_at, 1),
        }
    finally:
        with _JOB_LOCK:
            _JOB_RUNNING = False
