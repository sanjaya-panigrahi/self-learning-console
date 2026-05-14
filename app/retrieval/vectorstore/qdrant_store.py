import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config.settings import get_settings


def _chunk_id_to_uuid(chunk_id: str) -> str:
    """Convert an arbitrary chunk_id string to a deterministic UUID v5."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def _build_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


def upsert_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    vector_items = [item for item in items if item.get("embedding")]
    if not vector_items:
        return {"status": "skipped", "points_upserted": 0, "reason": "No embeddings available"}

    client = _build_client()
    vector_size = len(vector_items[0]["embedding"])

    existing_collections = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing_collections:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )

    points = [
        models.PointStruct(
            id=_chunk_id_to_uuid(item["chunk_id"]),
            vector=item["embedding"],
            payload={
                "source": item["source"],
                "chunk_id": item["chunk_id"],
                "text": item["text"],
                "page_number": item.get("page_number"),
            },
        )
        for item in vector_items
    ]
    client.upsert(collection_name=settings.qdrant_collection, points=points)
    return {"status": "synced", "points_upserted": len(points)}


def search_items(query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
    settings = get_settings()
    if not query_vector:
        return []

    client = _build_client()
    hits = client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        limit=top_k,
    )
    return [
        {
            "source": str(hit.payload.get("source", "unknown")),
            "chunk_id": str(hit.payload.get("chunk_id", "chunk-unknown")),
            "text": str(hit.payload.get("text", "")),
            "page_number": hit.payload.get("page_number"),
        }
        for hit in hits
    ]
