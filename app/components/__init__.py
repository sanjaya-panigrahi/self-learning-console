"""Component facades for retrieval-oriented building blocks.

These modules provide a stable compatibility layer over the underlying
retrieval/search implementation so the blueprint can reference a dedicated
components package without duplicating business logic.
"""

from app.components.retrieval import (
    RetrievedContext,
    cosine_similarity,
    is_lexical_first_query,
    lexical_context_search,
    retrieve_context,
    retrieve_context_with_llamaindex,
    rewrite_query_for_retrieval,
    sanitize_source_label,
    search_qdrant_items,
)

__all__ = [
    "RetrievedContext",
    "cosine_similarity",
    "is_lexical_first_query",
    "lexical_context_search",
    "retrieve_context",
    "retrieve_context_with_llamaindex",
    "rewrite_query_for_retrieval",
    "sanitize_source_label",
    "search_qdrant_items",
]