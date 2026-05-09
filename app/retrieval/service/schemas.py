from typing import TypedDict


class RetrievalCitation(TypedDict):
    source: str
    chunk_id: str


class RetrievalResultItem(TypedDict):
    source: str
    chunk_id: str
    excerpt: str
    page_image_url: str


class RetrievalVisualReference(TypedDict):
    source: str
    kind: str
    preview_url: str
    document_url: str
    note: str


class RetrievalSearchResponse(TypedDict):
    query: str
    retrieval_query: str
    orchestrator: str
    answer: str
    answer_confidence: float
    answer_confidence_source: str
    answer_model: str
    answer_path: str
    llm_answer: str
    llm_answer_confidence: float
    llm_answer_confidence_source: str
    llm_answer_model: str
    retrieval_answer: str
    retrieval_answer_confidence: float
    retrieval_answer_confidence_source: str
    retrieval_answer_model: str
    fallback_used: bool
    fallback_reason: str
    citations: list[RetrievalCitation]
    visual_references: list[RetrievalVisualReference]
    result_count: int
    results: list[RetrievalResultItem]
    cached: bool
    cache_age_seconds: int
    semantic_cache_hit: bool
    semantic_cache_score: float
    semantic_cache_kind: str
    semantic_cache_source: str
