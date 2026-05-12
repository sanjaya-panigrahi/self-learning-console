"""Retrieval component facades used by the blueprint alignment layer."""

from app.retrieval.pipeline import RetrievedContext, retrieve_context, rewrite_query_for_retrieval
from app.retrieval.pipeline.orchestrators.llamaindex_orchestrator import retrieve_context_with_llamaindex
from app.retrieval.search.lexical import is_lexical_first_query, lexical_context_search, sanitize_source_label
from app.retrieval.search.vector import cosine_similarity
from app.retrieval.vectorstore.qdrant_store import search_items as search_qdrant_items

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