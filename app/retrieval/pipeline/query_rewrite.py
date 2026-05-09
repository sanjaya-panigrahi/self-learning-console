"""Query rewriting for improved RAG retrieval."""

import httpx

from app.core.config.settings import get_settings
from app.core.observability.langsmith import traceable
from app.core.prompts.toon import render_prompt


def _rewrite_query_with_ollama(query: str, domain_context: str | None = None) -> str:
    """Rewrite a query using Ollama LLM for better retrieval coverage.

    Args:
        query: Original user query
        domain_context: Optional domain context hint

    Returns:
        Rewritten query string optimized for RAG retrieval
    """
    settings = get_settings()
    domain_line = f"Domain context: {domain_context.strip()}\n" if domain_context and domain_context.strip() else ""
    prompt = render_prompt(
        "retrieval.query_rewrite.v1",
        values={"domain_line": domain_line, "query": query},
    )
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    rewrite_timeout = httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0)
    with httpx.Client(timeout=rewrite_timeout) as client:
        response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        rewritten = response.json().get("response", "").strip()
    return rewritten


@traceable(
    name="retrieval.rewrite_query",
    run_type="chain",
    tags=["retrieval", "query-rewrite"],
    metadata={"component": "retrieval", "stage": "rewrite"},
)
def rewrite_query_for_retrieval(query: str, domain_context: str | None = None) -> str:
    """Rewrite a query for improved RAG retrieval using Ollama.

    Short-circuits if:
    - Query is blank
    - Query rewriting is disabled in settings
    - LLM provider is not Ollama

    Args:
        query: Original user query
        domain_context: Optional domain-specific context hint

    Returns:
        Rewritten query, or original query if rewriting fails or is disabled
    """
    settings = get_settings()
    if not query.strip():
        return query
    if not getattr(settings, "enable_query_rewrite", True):
        return query
    if str(getattr(settings, "llm_provider", "")).lower() != "ollama":
        return query

    try:
        rewritten = _rewrite_query_with_ollama(query, domain_context=domain_context)
    except httpx.HTTPError:
        return query

    cleaned = rewritten.splitlines()[0].strip().strip('"') if rewritten else ""
    if not cleaned:
        return query

    max_chars = int(getattr(settings, "query_rewrite_max_chars", 220))
    return cleaned[:max_chars]
