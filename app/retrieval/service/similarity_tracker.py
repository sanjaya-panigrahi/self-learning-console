"""Track similar user queries to improve cache routing and observability."""

from __future__ import annotations

import hashlib
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


def _ensure_collection(vector_size: int) -> None:
    settings = get_settings()
    client = _client()
    collection = settings.query_similarity_collection
    try:
        client.get_collection(collection)
        return
    except Exception:
        pass

    client.recreate_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )


def _stable_point_id(query_norm: str) -> str:
    digest = hashlib.sha1(query_norm.encode("utf-8")).hexdigest()[:32]
    return str(uuid.UUID(digest))


def find_similar_query(query: str, domain_context: str | None = None) -> dict[str, Any] | None:
    settings = get_settings()
    if not bool(getattr(settings, "query_similarity_tracking_enabled", True)):
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
    collection = settings.query_similarity_collection
    try:
        client.get_collection(collection)
    except Exception:
        return None

    try:
        hits = client.search(
            collection_name=collection,
            query_vector=vector,
            limit=max(int(getattr(settings, "query_similarity_top_k", 5)), 1),
        )
    except Exception:
        return None

    min_similarity = float(getattr(settings, "query_similarity_threshold", 0.9))
    request_domain = _normalize(domain_context)

    for hit in hits:
        payload = dict(hit.payload or {})
        candidate_domain = _normalize(str(payload.get("domain_context", "")))
        if candidate_domain and request_domain and candidate_domain != request_domain:
            continue

        candidate_query = _normalize(str(payload.get("query_norm", "")))
        if not candidate_query or candidate_query == query_norm:
            continue

        score = float(getattr(hit, "score", 0.0) or 0.0)
        if score < min_similarity:
            continue

        return {
            "query": str(payload.get("query", "")) or candidate_query,
            "query_norm": candidate_query,
            "score": score,
            "domain_context": str(payload.get("domain_context", "")),
            "seen_count": int(payload.get("seen_count", 0) or 0),
            "last_seen_at": int(payload.get("last_seen_at", 0) or 0),
            "signature": str(payload.get("signature", "")),
        }

    return None


def record_query_signature(query: str, domain_context: str | None = None) -> None:
    settings = get_settings()
    if not bool(getattr(settings, "query_similarity_tracking_enabled", True)):
        return

    query_norm = _normalize(query)
    if not query_norm:
        return

    try:
        vector = embed_text(query_norm)
    except Exception:
        return
    if not vector:
        return

    try:
        _ensure_collection(len(vector))
    except Exception:
        return

    client = _client()
    collection = settings.query_similarity_collection
    now = int(time.time())

    payload = {
        "query": query,
        "query_norm": query_norm,
        "domain_context": (domain_context or "").strip(),
        "signature": hashlib.md5(query_norm.encode("utf-8")).hexdigest()[:12],
        "seen_count": 1,
        "first_seen_at": now,
        "last_seen_at": now,
    }

    point_id = _stable_point_id(f"{query_norm}||{_normalize(domain_context)}")
    try:
        existing = client.retrieve(collection_name=collection, ids=[point_id], with_payload=True)
    except Exception:
        existing = []

    if existing:
        current = dict(existing[0].payload or {})
        payload["seen_count"] = int(current.get("seen_count", 0) or 0) + 1
        payload["first_seen_at"] = int(current.get("first_seen_at", now) or now)

    point = models.PointStruct(id=point_id, vector=vector, payload=payload)
    try:
        client.upsert(collection_name=collection, points=[point])
    except Exception:
        return


def get_similarity_stats() -> dict[str, Any]:
    settings = get_settings()
    if not bool(getattr(settings, "query_similarity_tracking_enabled", True)):
        return {
            "enabled": False,
            "collection": settings.query_similarity_collection,
            "points": 0,
        }

    client = _client()
    try:
        info = client.get_collection(settings.query_similarity_collection)
    except Exception:
        return {
            "enabled": True,
            "collection": settings.query_similarity_collection,
            "points": 0,
        }

    return {
        "enabled": True,
        "collection": settings.query_similarity_collection,
        "points": int(getattr(info, "points_count", 0) or 0),
        "similarity_threshold": float(getattr(settings, "query_similarity_threshold", 0.9)),
    }
