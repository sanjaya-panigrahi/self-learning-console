"""Planner agent for retrieval query strategy."""

from typing import Any


def build_retrieval_plan(
    query_clean: str,
    normalized_query: str,
    rewrite_enabled: bool,
    rewrite_func: Any,
    domain_context: str | None,
) -> dict[str, Any]:
    """Return a deterministic plan describing which query to run for retrieval."""
    local_normalized = normalized_query.strip().lower() != query_clean.strip().lower()

    if local_normalized:
        retrieval_query = normalized_query
        strategy = "normalized"
    elif not rewrite_enabled:
        retrieval_query = query_clean
        strategy = "original"
    else:
        retrieval_query = rewrite_func(query_clean, domain_context=domain_context)
        strategy = "rewritten"

    return {
        "retrieval_query": retrieval_query,
        "strategy": strategy,
        "local_normalized": local_normalized,
    }
