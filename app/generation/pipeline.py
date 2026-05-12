import logging
from typing import Any

import httpx

from app.api.schemas.chat import ChatResponse, Citation
from app.core.config.settings import get_settings
from app.core.observability.langsmith import traceable
from app.core.observability.metrics import timeit_stage
from app.core.prompts.toon import render_prompt
from app.core.resilience import CircuitBreaker, CircuitBreakerOpenError, exponential_backoff_retry
from app.retrieval.pipeline import RetrievedContext

logger = logging.getLogger(__name__)

_OLLAMA_BREAKER = CircuitBreaker(
    name="ollama",
    failure_threshold=3,
    recovery_timeout_seconds=60,
    expected_exception=httpx.HTTPError,
)


def _build_grounded_prompt(
    query: str,
    contexts: list[RetrievedContext],
    domain_context: str | None = None,
) -> str:
    """Build prompt for grounded answer generation."""
    context_lines: list[str] = []
    for idx, context in enumerate(contexts, start=1):
        context_lines.append(
            f"[{idx}] source={context['source']} chunk={context['chunk_id']}\\n{context['text']}"
        )

    joined_context = "\\n\\n".join(context_lines) if context_lines else "No context retrieved."
    domain_block = f"Domain Context:\n{domain_context.strip()}\n\n" if domain_context and domain_context.strip() else ""
    prompt = render_prompt(
        "generation.grounded_answer.v1",
        values={
            "domain_block": domain_block,
            "query": query,
            "joined_context": joined_context,
        },
    )
    return prompt or ""


@exponential_backoff_retry(
    max_retries=2,
    initial_delay_ms=100,
    max_delay_ms=1000,
    exception_types=(httpx.TimeoutException, TimeoutError),
)
@timeit_stage("generate")
@traceable(
    name="generation.call_ollama",
    run_type="llm",
    tags=["generation", "ollama", "answer"],
    metadata={"component": "generation", "provider": "ollama"},
)
def _call_ollama(prompt: str) -> str:
    """
    Call Ollama for generation with retry logic.
    
    Raises:
        httpx.HTTPError: If request fails (after retries)
        CircuitBreakerOpenError: If circuit breaker is open (too many failures)
    """
    settings = get_settings()
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    
    # Apply circuit breaker
    def _make_request() -> str:
        with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
            response = client.post(
                f"{settings.ollama_base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data.get("response", "").strip()
    
    return _OLLAMA_BREAKER.call(_make_request)


@traceable(
    name="generation.generate_answer",
    run_type="chain",
    tags=["generation", "answer"],
    metadata={"component": "generation"},
)
def generate_answer(
    query: str,
    contexts: list[RetrievedContext],
    domain_context: str | None = None,
) -> ChatResponse:
    """
    Generate grounded answers with graceful degradation.
    
    If Ollama is unavailable (circuit breaker open or timeout),
    returns top search results without synthesis.
    
    Args:
        query: User question
        contexts: Retrieved context chunks
        domain_context: Optional domain-specific context
    
    Returns:
        ChatResponse with answer + citations
    """
    citations = [Citation(source=c["source"], chunk_id=c["chunk_id"]) for c in contexts]
    settings = get_settings()

    if settings.llm_provider.lower() == "ollama":
        prompt = _build_grounded_prompt(query, contexts, domain_context=domain_context)
        try:
            answer = _call_ollama(prompt)
            if answer:
                return ChatResponse(answer=answer, citations=citations, confidence=0.75)
        except CircuitBreakerOpenError as exc:
            logger.warning(
                "Ollama circuit breaker OPEN (too many failures), returning search results: %s",
                exc,
            )
            # Graceful degradation: return top search result
            if contexts:
                fallback_answer = (
                    f"(LLM unavailable, showing top search result)\n\n{contexts[0]['text']}"
                )
                return ChatResponse(
                    answer=fallback_answer,
                    citations=citations,
                    confidence=0.5,
                )
        except (httpx.HTTPError, httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("Ollama request failed: %s", exc)
            # Graceful degradation: return top search result
            if contexts:
                fallback_answer = (
                    f"(LLM timeout, showing top search result)\n\n{contexts[0]['text']}"
                )
                return ChatResponse(
                    answer=fallback_answer,
                    citations=citations,
                    confidence=0.5,
                )

        # Fallback if no contexts
        return ChatResponse(
            answer=(
                "I could not reach the local Ollama model. "
                "Please check that Ollama is running and the configured model is pulled."
            ),
            citations=citations,
            confidence=0.2,
        )

    # Default fallback (non-Ollama provider)
    answer = f"This is a starter response for: {query}"
    return ChatResponse(answer=answer, citations=citations, confidence=0.5)
