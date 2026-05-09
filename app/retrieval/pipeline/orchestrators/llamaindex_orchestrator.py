import logging
from functools import lru_cache
from pathlib import Path

from app.core.config.settings import get_settings
from app.retrieval.pipeline import RetrievedContext

logger = logging.getLogger(__name__)


def _sanitize_source_label(source: str) -> str:
    source_path = Path(source)
    if len(source_path.parts) > 1:
        return source_path.name
    return source


@lru_cache
def _build_vector_index():
    settings = get_settings()

    from llama_index.core import VectorStoreIndex
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.vector_stores.qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.qdrant_url)
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=settings.qdrant_collection,
    )
    embedding_model = OllamaEmbedding(
        model_name=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )

    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embedding_model,
    )


def retrieve_context_with_llamaindex(query: str, top_k: int) -> list[RetrievedContext]:
    if not query.strip():
        return []

    try:
        index = _build_vector_index()
    except ImportError:
        logger.warning(
            "LlamaIndex dependencies are not installed. Falling back to custom retrieval orchestrator.",
        )
        return []
    except Exception as exc:
        logger.warning("Failed to initialize LlamaIndex retriever: %s", exc)
        return []

    try:
        retriever = index.as_retriever(similarity_top_k=max(1, int(top_k)))
        nodes = retriever.retrieve(query)
    except Exception as exc:
        logger.warning("LlamaIndex retrieval failed: %s", exc)
        return []

    contexts: list[RetrievedContext] = []
    for position, node in enumerate(nodes):
        metadata = getattr(node, "metadata", {}) or {}
        source = str(metadata.get("source", "unknown"))
        chunk_id = str(metadata.get("chunk_id", f"chunk-{position:03d}"))
        text = ""

        if hasattr(node, "text"):
            text = str(node.text or "").strip()
        if not text and hasattr(node, "get_content"):
            text = str(node.get_content() or "").strip()
        if not text:
            continue

        contexts.append(
            RetrievedContext(
                source=_sanitize_source_label(source),
                chunk_id=chunk_id,
                text=text,
            )
        )

    return contexts
