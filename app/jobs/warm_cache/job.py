from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from app.core.config.settings import get_settings
from app.core.prompts.toon import render_prompt
from app.retrieval.index import load_local_index
from app.retrieval.service.semantic_cache import upsert_semantic_cache_entry

_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "docs_total": 0,
    "docs_processed": 0,
    "entries_written": 0,
    "recent_sources": [],
    "errors": [],
    "models": [],
    "last_run_seconds": 0.0,
}


def _set_status(**kwargs: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(kwargs)


def _append_error(message: str) -> None:
    with _STATUS_LOCK:
        errs = list(_STATUS.get("errors", []))
        errs.append(message)
        _STATUS["errors"] = errs[-20:]


def get_warm_cache_status() -> dict[str, Any]:
    with _STATUS_LOCK:
        return dict(_STATUS)


def _pick_models(settings) -> list[str]:
    configured = [m.strip() for m in str(getattr(settings, "warm_cache_models", "")).split(",") if m.strip()]
    base_candidates = []
    for model_name in [settings.ollama_question_model, settings.ollama_fast_model, settings.ollama_model]:
        if model_name and model_name.strip() and model_name.strip() not in base_candidates:
            base_candidates.append(model_name.strip())

    available: list[str] = []
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0)) as client:
            tags = client.get(f"{settings.ollama_base_url}/api/tags")
            tags.raise_for_status()
            installed = {
                str(model.get("name", "")).strip()
                for model in tags.json().get("models", [])
                if str(model.get("name", "")).strip()
            }
    except Exception:
        installed = set()

    candidates = configured or base_candidates
    for candidate in candidates:
        if candidate in installed or f"{candidate}:latest" in installed:
            available.append(candidate)

    if not available and installed:
        available = list(installed)[: max(int(getattr(settings, "warm_cache_max_models", 3)), 1)]

    return available[: max(int(getattr(settings, "warm_cache_max_models", 3)), 1)]


def _group_chunks_by_source(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        source = str(item.get("source", "unknown"))
        grouped[source].append(item)

    grouped_items = sorted(grouped.items(), key=lambda pair: pair[0].lower())
    return grouped_items


def _build_prompt(source: str, chunk_texts: list[str], questions_per_doc: int, max_chars: int) -> str:
    merged = "\n\n".join(text for text in chunk_texts if text).strip()
    merged = merged[:max_chars]
    return render_prompt(
        "warm_cache.qa_generation.v1",
        values={
            "questions_per_doc": questions_per_doc,
            "source": source,
            "merged": merged,
        },
    )


def _generate_qa_items(
    model: str,
    source: str,
    chunk_texts: list[str],
    questions_per_doc: int | None = None,
    prompt_max_chars: int | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    effective_questions = max(
        int(questions_per_doc if questions_per_doc is not None else getattr(settings, "warm_cache_questions_per_doc", 8)),
        2,
    )
    effective_prompt_chars = max(
        int(prompt_max_chars if prompt_max_chars is not None else getattr(settings, "warm_cache_prompt_max_chars", 7000)),
        2000,
    )
    prompt = _build_prompt(
        source=source,
        chunk_texts=chunk_texts,
        questions_per_doc=effective_questions,
        max_chars=effective_prompt_chars,
    )

    read_timeout = max(
        float(getattr(settings, "warm_cache_generation_timeout_seconds", settings.ollama_timeout_seconds)),
        float(settings.ollama_timeout_seconds),
        30.0,
    )
    timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=10.0, pool=5.0)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        raw = str(response.json().get("response", "")).strip()

    parsed = json.loads(raw) if raw else {}
    items = parsed.get("items", [])
    if not isinstance(items, list):
        return []

    clean: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question", "")).split()).strip()
        answer = " ".join(str(item.get("answer", "")).split()).strip()
        if not question or not answer:
            continue
        key = question.lower()
        if key in seen_questions:
            continue
        seen_questions.add(key)
        confidence = float(item.get("confidence", 0.75) or 0.75)
        confidence = max(0.0, min(confidence, 1.0))
        clean.append({"question": question, "answer": answer, "confidence": confidence})
    return clean


def _doc_fingerprint(source: str, chunks: list[dict[str, Any]]) -> str:
    first = "|".join(str(chunk.get("chunk_id", "")) for chunk in chunks[:6])
    return f"{Path(source).name}:{len(chunks)}:{hash(first)}"


def _build_timeout_fallback_items(source: str, chunk_texts: list[str], max_items: int) -> list[dict[str, Any]]:
    topic = Path(source).stem.replace("_", " ").replace("-", " ").strip() or "this document"
    snippets: list[str] = []
    for text in chunk_texts:
        cleaned = " ".join(text.split()).strip()
        if cleaned:
            snippets.append(cleaned[:260])
        if len(snippets) >= max_items:
            break

    if not snippets:
        return []

    templates = [
        "What are the key operational details in {topic}?",
        "How is {topic} expected to be handled?",
        "What should users know first about {topic}?",
    ]
    items: list[dict[str, Any]] = []
    for index, snippet in enumerate(snippets):
        question = templates[index % len(templates)].format(topic=topic)
        question = re.sub(r"\s+", " ", question).strip()
        items.append(
            {
                "question": question,
                "answer": snippet,
                "confidence": 0.55,
            }
        )
    return items


def _build_response_payload(question: str, answer: str, source: str, chunk_ids: list[str], confidence: float, model: str) -> dict[str, Any]:
    return {
        "query": question,
        "retrieval_query": question,
        "orchestrator": "semantic-cache",
        "answer": answer,
        "answer_confidence": confidence,
        "answer_confidence_source": "warm-cache-llm",
        "answer_model": model,
        "answer_path": "semantic-cache",
        "llm_answer": answer,
        "llm_answer_confidence": confidence,
        "llm_answer_confidence_source": "warm-cache-llm",
        "llm_answer_model": model,
        "retrieval_answer": answer,
        "retrieval_answer_confidence": confidence,
        "retrieval_answer_confidence_source": "warm-cache-llm",
        "retrieval_answer_model": model,
        "fallback_used": False,
        "fallback_reason": "",
        "citations": [{"source": source, "chunk_id": chunk_id} for chunk_id in chunk_ids[:4]],
        "visual_references": [],
        "result_count": min(len(chunk_ids), 4),
        "results": [
            {
                "source": source,
                "chunk_id": chunk_id,
                "excerpt": "",
                "page_image_url": "",
            }
            for chunk_id in chunk_ids[:4]
        ],
        "cached": False,
        "cache_age_seconds": 0,
        "semantic_cache_hit": False,
        "semantic_cache_score": 0.0,
        "semantic_cache_kind": "warm",
        "semantic_cache_source": "warm-cache",
    }


def _process_source(source: str, chunks: list[dict[str, Any]], model: str) -> int:
    settings = get_settings()
    retries = max(int(getattr(settings, "warm_cache_retry_max", 2)), 0)
    retry_backoff = max(float(getattr(settings, "warm_cache_retry_backoff_seconds", 1.5)), 0.0)
    chunk_texts = [str(chunk.get("text", "")).strip() for chunk in chunks[:10]]
    chunk_ids = [str(chunk.get("chunk_id", "")).strip() for chunk in chunks[:10]]
    fingerprint = _doc_fingerprint(source, chunks)
    base_questions = max(int(getattr(settings, "warm_cache_questions_per_doc", 8)), 2)
    base_prompt_chars = max(int(getattr(settings, "warm_cache_prompt_max_chars", 7000)), 2000)

    qa_items: list[dict[str, Any]] = []
    last_error = None
    for attempt in range(retries + 1):
        # On retries, progressively reduce generation load to avoid repeated timeouts.
        attempt_questions = max(2, base_questions // (2**attempt))
        attempt_prompt_chars = max(2000, base_prompt_chars // (2**attempt))
        try:
            qa_items = _generate_qa_items(
                model=model,
                source=source,
                chunk_texts=chunk_texts,
                questions_per_doc=attempt_questions,
                prompt_max_chars=attempt_prompt_chars,
            )
            if qa_items:
                break
        except Exception as exc:
            last_error = exc
            if attempt < retries and retry_backoff > 0:
                time.sleep(retry_backoff * (attempt + 1))

    if not qa_items:
        if last_error is not None:
            if isinstance(last_error, TimeoutError) or isinstance(last_error, httpx.TimeoutException):
                fallback_items = _build_timeout_fallback_items(
                    source=source,
                    chunk_texts=chunk_texts,
                    max_items=max(1, min(base_questions, 3)),
                )
                if fallback_items:
                    qa_items = fallback_items
                else:
                    raise RuntimeError(
                        f"{source} generation failed: timed out after retries (model={model})"
                    ) from last_error
            else:
                raise RuntimeError(f"{source} generation failed: {last_error}") from last_error
        if not qa_items:
            return 0

    inserted = 0
    for item in qa_items:
        response_payload = _build_response_payload(
            question=item["question"],
            answer=item["answer"],
            source=source,
            chunk_ids=chunk_ids,
            confidence=float(item["confidence"]),
            model=model,
        )
        ok = upsert_semantic_cache_entry(
            query=item["question"],
            domain_context="",
            response_payload=response_payload,
            source=f"{source}|{fingerprint}",
            generated_by_model=model,
            kind="warm",
            score=float(item["confidence"]),
        )
        if ok:
            inserted += 1

    return inserted


def _run_job() -> None:
    settings = get_settings()
    started = time.time()
    _set_status(
        state="running",
        started_at=int(started),
        finished_at=None,
        docs_total=0,
        docs_processed=0,
        entries_written=0,
        recent_sources=[],
        errors=[],
        models=[],
        last_run_seconds=0.0,
    )

    if not bool(getattr(settings, "warm_cache_enabled", True)):
        _set_status(state="skipped", finished_at=int(time.time()), last_run_seconds=0.0)
        return

    models = _pick_models(settings)
    if not models:
        _set_status(
            state="failed",
            finished_at=int(time.time()),
            last_run_seconds=max(time.time() - started, 0.0),
            errors=["No healthy local models found for warm cache job."],
        )
        return

    index_items = load_local_index()
    grouped = _group_chunks_by_source(index_items)
    max_docs = int(getattr(settings, "warm_cache_max_docs", 0) or 0)
    if max_docs > 0:
        grouped = grouped[:max_docs]

    _set_status(models=models, docs_total=len(grouped))

    if not grouped:
        _set_status(state="completed", finished_at=int(time.time()), last_run_seconds=max(time.time() - started, 0.0))
        return

    workers_per_model = max(int(getattr(settings, "warm_cache_workers_per_model", 1)), 1)
    max_workers = max(1, min(len(grouped), len(models) * workers_per_model))

    futures: list[concurrent.futures.Future[int]] = []
    future_to_source: dict[concurrent.futures.Future[int], str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="warm-cache") as pool:
        for index, (source, chunks) in enumerate(grouped):
            model = models[index % len(models)]
            future = pool.submit(_process_source, source, chunks, model)
            futures.append(future)
            future_to_source[future] = source

        completed = 0
        written_total = 0
        recent_sources: list[str] = []
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            source_name = future_to_source.get(future, "")
            try:
                written_total += int(future.result() or 0)
            except Exception as exc:
                _append_error(str(exc))
            if source_name:
                recent_sources.append(source_name)
            _set_status(
                docs_processed=completed,
                entries_written=written_total,
                recent_sources=recent_sources[-20:],
            )

    errors = list(get_warm_cache_status().get("errors", []))
    _set_status(
        state="completed" if not errors else "completed_with_errors",
        finished_at=int(time.time()),
        last_run_seconds=max(time.time() - started, 0.0),
    )


def trigger_warm_cache_job(force: bool = False) -> dict[str, Any]:
    status = get_warm_cache_status()
    if status.get("state") == "running" and not force:
        return {"status": "already_running", "detail": status}

    if status.get("state") == "running" and force:
        return {"status": "running", "detail": status, "note": "Force restart is not supported while active."}

    thread = threading.Thread(target=_run_job, name="warm-cache-job", daemon=True)
    thread.start()
    return {"status": "started", "detail": get_warm_cache_status()}
