"""Vector store operations (Qdrant integration)."""

from typing import Any

from app.retrieval.vectorstore.qdrant_store import upsert_items as upsert_qdrant_items


def sync_to_vector_backend(items: list[dict[str, Any]], vector_backend: str) -> dict[str, Any]:
    """Sync indexed items to vector backend.

    Args:
        items: List of indexed items with embeddings
        vector_backend: Backend name (e.g., "qdrant", "local")

    Returns:
        Sync status dictionary
    """
    if vector_backend.lower() != "qdrant":
        return {"status": "not_requested", "points_upserted": 0}

    try:
        return upsert_qdrant_items(items)
    except Exception as exc:
        return {
            "status": "failed",
            "points_upserted": 0,
            "reason": f"Qdrant sync failed: {exc}",
        }
