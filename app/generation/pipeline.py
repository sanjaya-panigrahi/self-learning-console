import logging

import httpx

from app.api.schemas.chat import ChatResponse, Citation
from app.core.config.settings import get_settings
from app.core.observability.langsmith import traceable
from app.core.prompts.toon import render_prompt
from app.retrieval.pipeline import RetrievedContext

logger = logging.getLogger(__name__)


def _build_grounded_prompt(
    query: str,
    contexts: list[RetrievedContext],
    domain_context: str | None = None,
) -> str:
    context_lines = []
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


@traceable(
    name="generation.call_ollama",
    run_type="llm",
    tags=["generation", "ollama", "answer"],
    metadata={"component": "generation", "provider": "ollama"},
)
def _call_ollama(prompt: str) -> str:
    settings = get_settings()
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        data = response.json()
    return data.get("response", "").strip()


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
    """Generate grounded answers, using Ollama when configured."""
    citations = [Citation(source=c["source"], chunk_id=c["chunk_id"]) for c in contexts]
    settings = get_settings()

    if settings.llm_provider.lower() == "ollama":
        prompt = _build_grounded_prompt(query, contexts, domain_context=domain_context)
        try:
            answer = _call_ollama(prompt)
            if answer:
                return ChatResponse(answer=answer, citations=citations, confidence=0.75)
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed: %s", exc)

        return ChatResponse(
            answer=(
                "I could not reach the local Ollama model. "
                "Please check that Ollama is running and the configured model is pulled."
            ),
            citations=citations,
            confidence=0.2,
        )

    answer = f"This is a starter response for: {query}"
    return ChatResponse(answer=answer, citations=citations, confidence=0.5)
