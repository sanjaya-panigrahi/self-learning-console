"""Semantic retrieval cache backed by Qdrant for similar-query matching."""

from __future__ import annotations

import time
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config.settings import get_settings
from app.retrieval.embeddings.embed import embed_text


def _client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


def _cache_id(query: str, domain_context: str | None) -> str:
    raw = f"{_normalize(query)}||{_normalize(domain_context)}"
    # Qdrant point IDs must be uint or UUID; UUID5 gives stable deterministic IDs.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def _ensure_collection(vector_size: int) -> None:
    settings = get_settings()
    client = _client()
    collection = settings.semantic_cache_collection
    try:
        client.get_collection(collection)
        return
    except Exception:
        pass

    client.recreate_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )


def clear_semantic_cache() -> None:
    settings = get_settings()
    client = _client()
    try:
        client.delete_collection(settings.semantic_cache_collection)
    except Exception:
        return


def get_semantic_cache_stats() -> dict[str, Any]:
    settings = get_settings()
    client = _client()
    try:
        info = client.get_collection(settings.semantic_cache_collection)
    except Exception:
        return {
            "enabled": bool(getattr(settings, "semantic_cache_enabled", True)),
            "collection": settings.semantic_cache_collection,
            "points": 0,
        }

    points_count = int(getattr(info, "points_count", 0) or 0)
    return {
        "enabled": bool(getattr(settings, "semantic_cache_enabled", True)),
        "collection": settings.semantic_cache_collection,
        "points": points_count,
    }


def upsert_semantic_cache_entry(
    query: str,
    domain_context: str | None,
    response_payload: dict[str, Any],
    source: str,
    generated_by_model: str,
    kind: str,
    score: float | None = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "semantic_cache_enabled", True)):
        return False

    query_norm = _normalize(query)
    if not query_norm:
        return False

    try:
        vector = embed_text(query_norm)
        if not vector:
            return False
    except Exception:
        return False

    try:
        _ensure_collection(len(vector))
    except Exception:
        return False

    now = int(time.time())
    ttl_days = max(int(getattr(settings, "semantic_cache_ttl_days", 30)), 1)
    expires_at = now + (ttl_days * 86400)

    answer_text = str(response_payload.get("answer", "")).strip()
    max_answer_chars = max(int(getattr(settings, "semantic_cache_max_answer_chars", 2200)), 400)
    if len(answer_text) > max_answer_chars:
        response_payload = dict(response_payload)
        response_payload["answer"] = answer_text[:max_answer_chars].rstrip() + "..."

    try:
        point = models.PointStruct(
            id=_cache_id(query_norm, domain_context),
            vector=vector,
            payload={
                "query": query,
                "query_norm": query_norm,
                "domain_context": (domain_context or "").strip(),
                "response": dict(response_payload),
                "source": source,
                "generated_by_model": generated_by_model,
                "kind": kind,
                "created_at": now,
                "expires_at": expires_at,
                "score_hint": float(score) if score is not None else None,
            },
        )
    except Exception:
        return False


    try:
        client = _client()
        client.upsert(collection_name=settings.semantic_cache_collection, points=[point])
        return True
    except Exception:
        return False


def find_semantic_cache_hit(
    query: str,
    domain_context: str | None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not bool(getattr(settings, "semantic_cache_enabled", True)):
        return None

    query_norm = _normalize(query)
    if not query_norm:
        return None

    try:
        vector = embed_text(query_norm)
    except Exception:
        return None
    if not vector:
        return None

    client = _client()
    collection = settings.semantic_cache_collection
    try:
        client.get_collection(collection)
    except Exception:
        return None

    top_k = max(int(getattr(settings, "semantic_cache_top_k", 5)), 1)
    high_threshold = float(getattr(settings, "semantic_cache_similarity_threshold", 0.88))
    mid_threshold = float(getattr(settings, "semantic_cache_mid_similarity_threshold", 0.80))
    now = int(time.time())

    try:
        hits = client.search(collection_name=collection, query_vector=vector, limit=top_k)
    except Exception:
        return None
    best: dict[str, Any] | None = None
    for hit in hits:
        payload = dict(hit.payload or {})
        expires_at = int(payload.get("expires_at") or 0)
        if expires_at and expires_at < now:
            continue

        hit_domain = _normalize(str(payload.get("domain_context", "")))
        req_domain = _normalize(domain_context)
        if hit_domain and req_domain and hit_domain != req_domain:
            continue

        score = float(getattr(hit, "score", 0.0) or 0.0)
        if score < mid_threshold:
            continue

        response = payload.get("response")
        if not isinstance(response, dict):
            continue

        candidate = {
            "score": score,
            "response": dict(response),
            "source": str(payload.get("source", "semantic-cache")),
            "kind": str(payload.get("kind", "runtime")),
            "created_at": int(payload.get("created_at") or now),
            "generated_by_model": str(payload.get("generated_by_model", "")),
            "high_confidence": score >= high_threshold,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best
