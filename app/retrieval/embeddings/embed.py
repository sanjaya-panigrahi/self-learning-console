"""Embedding generation via Ollama."""

import httpx

from app.core.config.settings import get_settings


def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for text using Ollama.

    Tries the current /api/embed endpoint first and falls back to the
    legacy /api/embeddings endpoint for older Ollama versions.

    Args:
        text: Text to embed

    Returns:
        Embedding vector as a list of floats, or [] on failure
    """
    settings = get_settings()
    # Allow up to 30s for embeddings — Ollama may be slow when LLM inference is running concurrently.
    embed_read_timeout = min(float(settings.ollama_timeout_seconds), 30.0)
    ollama_timeout = httpx.Timeout(connect=5.0, read=embed_read_timeout, write=5.0, pool=5.0)
    with httpx.Client(timeout=ollama_timeout) as client:
        # Prefer the current Ollama embedding endpoint.
        response = client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": text},
        )
        if response.status_code == 404:
            # Backward-compatibility with older Ollama versions.
            legacy = client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": settings.embedding_model, "prompt": text},
            )
            if legacy.status_code == 404:
                return []
            legacy.raise_for_status()
            return legacy.json().get("embedding", [])

        response.raise_for_status()
        payload = response.json()
        embeddings = payload.get("embeddings", [])
        if not embeddings:
            return []
        return embeddings[0]
