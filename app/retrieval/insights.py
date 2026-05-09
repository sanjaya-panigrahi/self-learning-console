"""Material insight orchestrator - coordinates insight generation with caching.

Sub-modules:
  insight/index.py      - Local index loading and chunk preparation
  insight/content.py    - Content analysis (modules, fields, data detection)
  insight/fallback.py   - Heuristic fallback insight generation
  insight/cache.py      - In-memory insight caching with TTL
  insight/questions.py  - Question filtering and progressive question building
  insight/llm.py        - LLM-based insight and question generation via Ollama
"""

import threading
from typing import Any

from app.core.config.settings import get_settings
from app.core.observability.langsmith import traceable
from app.core.prompts.toon import render_prompt
from app.retrieval.insight.cache import (
    cache_key,
    clear_material_insight_cache,
    get_cached_material_insight,
    set_cached_material_insight,
)
from app.retrieval.insight.fallback import fallback_material_insight
from app.retrieval.insight.index import (
    get_material_chunks,
    prepare_chunks_for_insight,
    trim_excerpt,
)
from app.retrieval.insight.llm import (
    generate_insight_with_ollama,
    generate_question_bank_with_ollama,
    select_question_model,
)
from app.retrieval.insight.questions import InsightProgressCallback, emit_progress

__all__ = [
    "get_material_insight",
    "clear_material_insight_cache",
    "InsightProgressCallback",
]


_QUESTION_BACKFILL_LOCK = threading.Lock()
_ACTIVE_QUESTION_BACKFILLS: set[str] = set()


def _start_async_question_backfill(
    source: str,
    domain_context: str | None,
    prepared_chunks: list[str],
    question_model: str,
    base_result: dict[str, Any],
) -> None:
    backfill_key = cache_key(source, domain_context)
    with _QUESTION_BACKFILL_LOCK:
        if backfill_key in _ACTIVE_QUESTION_BACKFILLS:
            return
        _ACTIVE_QUESTION_BACKFILLS.add(backfill_key)

    def _run() -> None:
        try:
            questions = generate_question_bank_with_ollama(
                source,
                prepared_chunks,
                [],
                question_model=question_model,
                strict_model_only=True,
                callback=None,
            )
            if not questions:
                return

            cached_payload = get_cached_material_insight(source, domain_context)
            payload = dict(cached_payload or base_result)
            payload.pop("cached", None)
            payload.pop("cache_age_seconds", None)
            payload["suggested_questions"] = questions
            payload["question_source"] = "question_model_async_backfill"
            payload["question_model"] = question_model
            set_cached_material_insight(source, domain_context, payload)
        finally:
            with _QUESTION_BACKFILL_LOCK:
                _ACTIVE_QUESTION_BACKFILLS.discard(backfill_key)

    threading.Thread(target=_run, name="material-insight-qwen-backfill", daemon=True).start()


def _compute_material_insight(
    source: str,
    domain_context: str | None = None,
    callback: InsightProgressCallback | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    question_model = select_question_model(settings)
    chunks = get_material_chunks(source)
    if not chunks:
        emit_progress(callback, "not_searchable", {})
        return {
            "source": source,
            "summary": "This material is not currently searchable. It may be blocked for PII review or failed during ingestion.",
            "key_topics": [],
            "critical_points": [],
            "suggested_questions": [],
            "cached": False,
            "partial": False,
            "question_model": question_model,
        }

    prepared_chunks = prepare_chunks_for_insight(chunks)
    domain_block = f"Domain context: {domain_context.strip()}\n" if domain_context and domain_context.strip() else ""
    prompt_budgets: list[tuple[int, int]] = [(4, 900), (3, 700), (2, 550)]
    prompt_candidates = [
        render_prompt(
            "retrieval.material_insight.v1",
            values={
                "domain_block": domain_block,
                "source": source,
                "combined": "\n\n".join(trim_excerpt(chunk, limit=char_limit) for chunk in prepared_chunks[:chunk_limit]),
            },
        )
        for chunk_limit, char_limit in prompt_budgets
    ]

    fallback = fallback_material_insight(source, chunks)
    if str(getattr(settings, "llm_provider", "")).lower() != "ollama":
        return {
            **fallback,
            "cached": False,
            "partial": False,
            "model": "fallback",
            "generation_ms": 0,
            "question_model": question_model,
        }

    result = generate_insight_with_ollama(source, prompt_candidates, fallback, callback=callback)
    timeout_exhausted = bool(result.get("insight_timeout_exhausted"))
    skip_questions_on_timeout = bool(getattr(settings, "material_insight_skip_questions_on_timeout", True))
    async_backfill_on_timeout = bool(getattr(settings, "material_insight_async_question_backfill_on_timeout", True))

    # When a question model is configured, enforce model-only questions.
    # This avoids heuristic template backfill leaking into the UI.
    if question_model and question_model.lower() != "disabled" and not (skip_questions_on_timeout and timeout_exhausted):
        qwen_questions = generate_question_bank_with_ollama(
            source,
            prepared_chunks,
            [],
            question_model=question_model,
            strict_model_only=True,
            callback=callback,
        )
        result["suggested_questions"] = qwen_questions
        result["question_source"] = "question_model"
    elif question_model and question_model.lower() != "disabled" and skip_questions_on_timeout and timeout_exhausted:
        result["question_source"] = "question_model_skipped_timeout"
        emit_progress(
            callback,
            "questions_skipped",
            {"source": source, "reason": "insight_timeout_exhausted", "question_model": question_model},
        )
        if async_backfill_on_timeout:
            _start_async_question_backfill(
                source=source,
                domain_context=domain_context,
                prepared_chunks=prepared_chunks,
                question_model=question_model,
                base_result=result,
            )
            emit_progress(
                callback,
                "questions_backfill_started",
                {"source": source, "question_model": question_model},
            )
    else:
        result["question_source"] = "insight_model_or_fallback"

    result["question_model"] = question_model
    return result


@traceable(
    name="retrieval.material_insight",
    run_type="chain",
    tags=["retrieval", "insight", "material"],
    metadata={"component": "retrieval", "stage": "insight"},
)
def get_material_insight(
    source: str,
    domain_context: str | None = None,
    use_cache: bool = True,
    progress_callback: InsightProgressCallback | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    question_model = select_question_model(settings)
    emit_progress(progress_callback, "start", {"source": source})
    if use_cache:
        cached = get_cached_material_insight(source, domain_context)
        if cached is not None:
            cached["question_model"] = str(cached.get("question_model") or question_model)
            emit_progress(progress_callback, "cache_hit", {"source": source})
            return cached

    result = _compute_material_insight(source, domain_context=domain_context, callback=progress_callback)
    result["question_model"] = str(result.get("question_model") or question_model)

    should_skip_cache = bool(
        str(result.get("question_source") or "").strip().lower() == "question_model"
        and str(result.get("question_model") or "").strip().lower() not in {"", "disabled"}
        and not result.get("suggested_questions")
    )
    if not should_skip_cache:
        set_cached_material_insight(source, domain_context, result)
    emit_progress(progress_callback, "done", {"source": source, "cached": False})
    return result
