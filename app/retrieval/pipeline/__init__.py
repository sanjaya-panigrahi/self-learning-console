"""Retrieval pipeline orchestrator - coordinates context retrieval for RAG."""

from typing import TypedDict

from app.core.config.settings import get_settings
from app.core.observability.langsmith import traceable
from app.retrieval.embeddings.embed import embed_text as _embed_text
from app.retrieval.index import load_local_index as _load_local_index
from app.retrieval.pipeline.query_rewrite import rewrite_query_for_retrieval
from app.retrieval.search.lexical import is_lexical_first_query as _is_lexical_first_query
from app.retrieval.search.lexical import lexical_context_search as _lexical_context_search
from app.retrieval.search.lexical import sanitize_source_label as _sanitize_source_label
from app.retrieval.search.vector import cosine_similarity as _cosine_similarity
from app.retrieval.vectorstore.qdrant_store import search_items as search_qdrant_items

# Re-export query rewrite for backward compatibility
__all__ = [
    "retrieve_context",
    "rewrite_query_for_retrieval",
    "RetrievedContext",
]


class RetrievedContext(TypedDict):
    source: str
    chunk_id: str
    text: str


@traceable(
    name="retrieval.retrieve_context",
    run_type="retriever",
    tags=["retrieval", "context"],
    metadata={"component": "retrieval", "stage": "retrieve"},
)
def retrieve_context(query: str, top_k: int | None = None) -> list[RetrievedContext]:
    """Retrieve top-k semantically similar chunks from Qdrant or local index."""
    settings = get_settings()
    k = top_k or settings.retrieval_top_k
    items = _load_local_index()
    if not items and settings.vector_backend.lower() != "qdrant":
        return []

    # For short acronym/entity queries, lexical search is faster and usually more reliable.
    if _is_lexical_first_query(query):
        lexical_hits = _lexical_context_search(query=query, items=items, k=k)
        if lexical_hits:
            return [RetrievedContext(**hit) for hit in lexical_hits]

    query_vector = _embed_text(query)
    if settings.vector_backend.lower() == "qdrant" and query_vector:
        try:
            qdrant_hits = search_qdrant_items(query_vector, k)
            if qdrant_hits:
                return [
                    RetrievedContext(
                        source=_sanitize_source_label(str(item.get("source", "unknown"))),
                        chunk_id=str(item.get("chunk_id", "chunk-unknown")),
                        text=str(item.get("text", "")),
                    )
                    for item in qdrant_hits
                ]
        except Exception:
            pass

        # If vector backend is available but returns no hits for this query,
        # fall back to lexical search so users still receive best-effort context.
        lexical_hits = _lexical_context_search(query=query, items=items, k=k)
        if lexical_hits:
            return [RetrievedContext(**hit) for hit in lexical_hits]

    if not query_vector:
        return [RetrievedContext(**hit) for hit in _lexical_context_search(query=query, items=items, k=k)]

    scored: list[tuple[float, dict[str, str | list[float]]]] = []
    for item in items:
        vector = item.get("embedding", [])
        if not isinstance(vector, list) or not vector:
            continue
        score = _cosine_similarity(query_vector, vector)
        scored.append((score, item))

    if not scored:
        return [RetrievedContext(**hit) for hit in _lexical_context_search(query=query, items=items, k=k)]

    scored.sort(key=lambda row: row[0], reverse=True)
    top_items = scored[:k]

    return [
        RetrievedContext(
            source=_sanitize_source_label(str(item.get("source", "unknown"))),
            chunk_id=str(item.get("chunk_id", "chunk-unknown")),
            text=str(item.get("text", "")),
        )
        for _, item in top_items
    ]
