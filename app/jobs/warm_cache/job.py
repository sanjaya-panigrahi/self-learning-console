from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from app.core.config.settings import get_settings
from app.core.prompts.toon import render_prompt
from app.retrieval.index import load_local_index
from app.retrieval.service.semantic_cache import upsert_semantic_cache_entry_detailed

_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "heartbeat_at": None,
    "finished_at": None,
    "docs_total": 0,
    "docs_started": 0,
    "in_flight": 0,
    "docs_processed": 0,
    "entries_written": 0,
    "recent_sources": [],
    "errors": [],
    "models": [],
    "last_run_seconds": 0.0,
}


def _status_file_path() -> Path:
    return Path("/app/data/indexes/warm_cache_status.json")


def _manifest_file_path() -> Path:
    return Path("/app/data/indexes/warm_cache_manifest.json")


def _read_manifest() -> dict[str, Any]:
    """Load the completion manifest: {source_fingerprint: {source, cached_at, entries_written}}."""
    path = _manifest_file_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_manifest(manifest: dict[str, Any]) -> None:
    path = _manifest_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".manifest.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _manifest_key(source: str, fingerprint: str) -> str:
    return f"{source}||{fingerprint}"


def _mark_source_done(manifest: dict[str, Any], source: str, fingerprint: str, entries_written: int) -> None:
    key = _manifest_key(source, fingerprint)
    manifest[key] = {
        "source": source,
        "fingerprint": fingerprint,
        "cached_at": int(time.time()),
        "entries_written": entries_written,
    }
    _write_manifest(manifest)


def _read_status_file() -> dict[str, Any] | None:
    path = _status_file_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _write_status_file(payload: dict[str, Any]) -> None:
    path = _status_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # Status persistence is best-effort and should never crash the job.
        return


def _status_file_age_seconds() -> float | None:
    path = _status_file_path()
    try:
        if not path.exists():
            return None
        return max(time.time() - float(path.stat().st_mtime), 0.0)
    except Exception:
        return None


def _set_status(**kwargs: Any) -> None:
    with _STATUS_LOCK:
        if "heartbeat_at" not in kwargs:
            kwargs["heartbeat_at"] = int(time.time())
        _STATUS.update(kwargs)
        _write_status_file(_STATUS)


def _append_error(message: str) -> None:
    with _STATUS_LOCK:
        errs = list(_STATUS.get("errors", []))
        errs.append(message)
        _STATUS["errors"] = errs[-20:]
        _write_status_file(_STATUS)


def get_warm_cache_status() -> dict[str, Any]:
    persisted = _read_status_file()
    with _STATUS_LOCK:
        if persisted:
            _STATUS.update(persisted)
        started_at = int(_STATUS.get("started_at") or 0)
        if _STATUS.get("state") == "running" and started_at:
            _STATUS["last_run_seconds"] = max(time.time() - started_at, 0.0)
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
    digest = hashlib.sha256(first.encode()).hexdigest()[:16]
    return f"{Path(source).name}:{len(chunks)}:{digest}"


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


def _source_alias_queries(source: str) -> list[str]:
    source_name = Path(unquote(source)).name.strip()
    if not source_name:
        return []

    stem = Path(source_name).stem.strip()
    readable_stem = re.sub(r"[_-]+", " ", stem)
    readable_stem = re.sub(r"\s+", " ", readable_stem).strip()

    aliases: list[str] = []
    for candidate in [source_name, stem, readable_stem, f"{readable_stem} pdf" if source_name.lower().endswith(".pdf") else ""]:
        normalized = re.sub(r"\s+", " ", str(candidate or "")).strip()
        if normalized and normalized.lower() not in {alias.lower() for alias in aliases}:
            aliases.append(normalized)
    return aliases


def _build_source_alias_answer(source: str, chunk_texts: list[str]) -> str:
    source_name = Path(unquote(source)).name.strip() or source
    summary = ""
    for text in chunk_texts:
        cleaned = " ".join(str(text).split()).strip()
        if cleaned:
            summary = cleaned[:420].rstrip()
            break
    if summary:
        return f"This document is {source_name}. Matching content starts with: {summary}"
    return f"This document is {source_name}."


def _process_source(source: str, chunks: list[dict[str, Any]], model: str) -> dict[str, Any]:
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
            return {"inserted": 0, "complete": True, "error": ""}

    primary_inserted = 0
    primary_failed_reasons: dict[str, int] = defaultdict(int)
    alias_inserted = 0
    alias_failed_reasons: dict[str, int] = defaultdict(int)
    alias_queries = _source_alias_queries(source)
    alias_answer = _build_source_alias_answer(source, chunk_texts)
    for item in qa_items:
        response_payload = _build_response_payload(
            question=item["question"],
            answer=item["answer"],
            source=source,
            chunk_ids=chunk_ids,
            confidence=float(item["confidence"]),
            model=model,
        )
        ok, reason = upsert_semantic_cache_entry_detailed(
            query=item["question"],
            domain_context="",
            response_payload=response_payload,
            source=f"{source}|{fingerprint}",
            generated_by_model=model,
            kind="warm",
            score=float(item["confidence"]),
        )
        if ok:
            primary_inserted += 1
        else:
            primary_failed_reasons[str(reason or "unknown_upsert_failure")] += 1

    if alias_queries:
        for alias_query in alias_queries:
            alias_payload = _build_response_payload(
                question=alias_query,
                answer=alias_answer,
                source=source,
                chunk_ids=chunk_ids,
                confidence=0.92,
                model=model,
            )
            ok, reason = upsert_semantic_cache_entry_detailed(
                query=alias_query,
                domain_context="",
                response_payload=alias_payload,
                source=f"{source}|{fingerprint}|alias",
                generated_by_model=model,
                kind="warm-alias",
                score=0.92,
            )
            if ok:
                alias_inserted += 1
            else:
                alias_failed_reasons[str(reason or "unknown_upsert_failure")] += 1

    total_inserted = primary_inserted + alias_inserted

    if qa_items and primary_inserted == 0 and primary_failed_reasons:
        top_reason = max(primary_failed_reasons.items(), key=lambda pair: pair[1])
        raise RuntimeError(
            f"{source} cache upsert failed for QA items ({primary_inserted}/{len(qa_items)}): {top_reason[0]} x{top_reason[1]}"
        )

    if primary_failed_reasons:
        top_reason = max(primary_failed_reasons.items(), key=lambda pair: pair[1])
        return {
            "inserted": total_inserted,
            "complete": False,
            "error": (
                f"{source} cache upsert partial failure: {top_reason[0]} x{top_reason[1]} "
                f"(qa_inserted={primary_inserted}/{len(qa_items)}, alias_inserted={alias_inserted}/{len(alias_queries)})"
            ),
        }

    # Alias upserts improve discoverability for source-name queries but should not fail the document
    # when primary QA items are inserted successfully.
    return {"inserted": total_inserted, "complete": True, "error": ""}


def _run_job() -> None:
    settings = get_settings()
    started = time.time()
    _set_status(
        state="running",
        started_at=int(started),
        finished_at=None,
        docs_total=0,
        docs_started=0,
        in_flight=0,
        docs_processed=0,
        entries_written=0,
        recent_sources=[],
        errors=[],
        models=[],
        last_run_seconds=0.0,
    )

    try:
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

        # --- Incremental skip: filter out sources already in the completion manifest ---
        manifest = _read_manifest()
        force_refresh = bool(getattr(settings, "warm_cache_force_refresh", False))
        skipped_sources: list[str] = []
        if not force_refresh:
            pending_grouped = []
            for source, chunks in grouped:
                fp = _doc_fingerprint(source, chunks)
                if _manifest_key(source, fp) in manifest:
                    skipped_sources.append(source)
                else:
                    pending_grouped.append((source, chunks))
            grouped = pending_grouped

        already_written = sum(int(v.get("entries_written") or 0) for v in manifest.values())
        total_docs = len(grouped) + len(skipped_sources)
        _set_status(models=models, docs_total=total_docs)

        if not grouped:
            _set_status(
                state="completed",
                docs_processed=total_docs,
                entries_written=already_written,
                finished_at=int(time.time()),
                last_run_seconds=max(time.time() - started, 0.0),
            )
            return

        workers_per_model = max(int(getattr(settings, "warm_cache_workers_per_model", 1)), 1)
        max_workers = max(1, min(len(grouped), len(models) * workers_per_model))

        futures: list[concurrent.futures.Future[dict[str, Any]]] = []
        future_to_source: dict[concurrent.futures.Future[int], str] = {}
        future_to_fingerprint: dict[concurrent.futures.Future[int], str] = {}
        heartbeat_interval_seconds = max(float(getattr(settings, "warm_cache_heartbeat_seconds", 10.0)), 2.0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="warm-cache") as pool:
            for index, (source, chunks) in enumerate(grouped):
                model = models[index % len(models)]
                future = pool.submit(_process_source, source, chunks, model)
                futures.append(future)
                future_to_source[future] = source
                future_to_fingerprint[future] = _doc_fingerprint(source, chunks)

            _set_status(state="running", docs_started=len(futures), in_flight=len(futures))

            completed = len(skipped_sources)  # already-done sources count toward progress
            written_total = already_written
            recent_sources: list[str] = list(skipped_sources[-10:])
            pending: set[concurrent.futures.Future[int]] = set(futures)
            while pending:
                done, pending = concurrent.futures.wait(
                    pending,
                    timeout=heartbeat_interval_seconds,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                if not done:
                    _set_status(
                        state="running",
                        docs_processed=completed,
                        in_flight=len(pending),
                        entries_written=written_total,
                        recent_sources=recent_sources[-20:],
                    )
                    continue

                for future in done:
                    completed += 1
                    source_name = future_to_source.get(future, "")
                    fp = future_to_fingerprint.get(future, "")
                    inserted = 0
                    try:
                        result = future.result() or {}
                        inserted = int(result.get("inserted") or 0)
                        is_complete = bool(result.get("complete", True))
                        partial_error = str(result.get("error") or "").strip()
                        written_total += inserted
                        # Persist success only for fully successful sources.
                        if is_complete and inserted > 0 and source_name and fp:
                            _mark_source_done(manifest, source_name, fp, inserted)
                        if not is_complete and partial_error:
                            _append_error(partial_error)
                    except Exception as exc:
                        _append_error(str(exc))
                    if source_name:
                        recent_sources.append(source_name)
                    _set_status(
                        state="running",
                        docs_processed=completed,
                        in_flight=len(pending),
                        entries_written=written_total,
                        recent_sources=recent_sources[-20:],
                    )

        errors = list(get_warm_cache_status().get("errors", []))
        _set_status(
            state="completed" if not errors else "completed_with_errors",
            finished_at=int(time.time()),
            last_run_seconds=max(time.time() - started, 0.0),
        )
    except Exception as exc:
        _set_status(
            state="failed",
            finished_at=int(time.time()),
            last_run_seconds=max(time.time() - started, 0.0),
            errors=[f"warm-cache job crashed: {exc}"],
        )


def trigger_warm_cache_job(force: bool = False) -> dict[str, Any]:
    status = get_warm_cache_status()
    if status.get("state") == "running":
        now = time.time()
        started_at = int(status.get("started_at") or 0)
        heartbeat_at = int(status.get("heartbeat_at") or 0)
        baseline = heartbeat_at or started_at
        activity_age_seconds = int(now - baseline) if baseline else 0
        status_file_age = _status_file_age_seconds()
        stale_after_seconds = max(int(getattr(get_settings(), "warm_cache_stale_seconds", 900)), 60)
        is_stale = activity_age_seconds >= stale_after_seconds
        if status_file_age is not None:
            is_stale = is_stale or status_file_age >= stale_after_seconds

        if not is_stale and not force:
            return {"status": "already_running", "detail": status}

        if not is_stale and force:
            return {"status": "running", "detail": status, "note": "Force restart is not supported while active."}

        stale_message = (
            f"Recovered stale warm-cache run (last activity {activity_age_seconds}s ago; "
            f"status file age {int(status_file_age) if status_file_age is not None else -1}s)."
        )
        previous_errors = [str(e) for e in list(status.get("errors") or [])][-19:]
        _set_status(
            state="failed",
            finished_at=int(now),
            errors=previous_errors + [stale_message],
            last_run_seconds=max(now - float(started_at or now), 0.0),
        )

    queued_at = int(time.time())
    _set_status(
        state="queued",
        started_at=queued_at,
        heartbeat_at=queued_at,
        finished_at=None,
        docs_total=0,
        docs_started=0,
        in_flight=0,
        docs_processed=0,
        entries_written=0,
        recent_sources=[],
        errors=[],
        models=[],
        last_run_seconds=0.0,
    )

    thread = threading.Thread(target=_run_job, name="warm-cache-job", daemon=True)
    thread.start()
    return {"status": "started", "detail": get_warm_cache_status()}
