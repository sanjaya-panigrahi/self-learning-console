from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "training-agent"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    log_json_format: bool = False  # NEW: Structured JSON logging
    vector_backend: str = "qdrant"
    llm_provider: str = "openai"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_fast_model: str = "llama3.2:3b"
    ollama_question_model: str = ""
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    ollama_timeout_seconds: float = 45.0
    ollama_insight_timeout_seconds: float = 35.0
    ollama_question_timeout_seconds: float = 35.0
    ollama_circuit_breaker_enabled: bool = True  # NEW: Circuit breaker for Ollama
    ollama_circuit_breaker_failure_threshold: int = 3  # NEW: Failures before opening
    ollama_circuit_breaker_recovery_seconds: int = 60  # NEW: Recovery timeout
    material_insight_skip_questions_on_timeout: bool = True
    material_insight_async_question_backfill_on_timeout: bool = True
    material_insight_cache_ttl_seconds: int = 10800
    material_insight_cache_dir: str = str(PROJECT_ROOT / "data" / "indexes" / "material_insight_cache")
    material_insight_background_top_n: int = 3
    enable_query_rewrite: bool = True
    query_rewrite_max_chars: int = 220
    local_index_path: str = str(PROJECT_ROOT / "data" / "indexes" / "local_index.json")
    data_raw_dir: str = str(PROJECT_ROOT / "data" / "raw")
    data_processed_dir: str = str(PROJECT_ROOT / "data" / "processed")
    data_indexes_dir: str = str(PROJECT_ROOT / "data" / "indexes")
    data_traces_dir: str = str(PROJECT_ROOT / "data" / "traces")
    ingestion_source_dir: str = str(PROJECT_ROOT / "Resource")
    ingestion_report_path: str = str(PROJECT_ROOT / "data" / "indexes" / "ingestion_report.json")
    ingestion_ocr_enabled: bool = False
    ingestion_ocr_min_chars: int = 120
    ingestion_ocr_max_pages: int = 20
    ingestion_ocr_dpi: int = 200
    pii_validation_enabled: bool = False
    pii_approval_path: str = str(PROJECT_ROOT / "data" / "indexes" / "pii_approvals.json")
    feedback_log_path: str = str(PROJECT_ROOT / "data" / "indexes" / "feedback_log.json")
    benchmark_report_path: str = str(PROJECT_ROOT / "data" / "indexes" / "benchmark_report.json")
    benchmark_eval_set_path: str = str(PROJECT_ROOT / "data" / "indexes" / "benchmark_eval_set.json")
    deploy_intel_report_path: str = str(PROJECT_ROOT / "data" / "indexes" / "deploy_intelligence_report.json")
    deploy_intel_knowledge_cards_path: str = str(PROJECT_ROOT / "data" / "indexes" / "knowledge_cards.json")
    deploy_intel_clusters_path: str = str(PROJECT_ROOT / "data" / "indexes" / "similarity_clusters.json")
    deploy_intel_max_docs: int = 0
    deploy_intel_questions_per_doc: int = 16
    deploy_intel_generation_timeout_seconds: float = 180.0
    deploy_intel_retry_max: int = 2
    deploy_intel_retry_backoff_seconds: float = 1.5
    deploy_intel_fast_mode: bool = False
    deploy_intel_skip_contradictions: bool = False
    deploy_intel_skip_lint: bool = False
    deploy_intel_enable_on_deploy: bool = True
    deploy_intel_blocking_on_deploy: bool = False
    deploy_intel_required_min_questions: int = 30
    deploy_intel_required_repeat_hit_rate: float = 0.6
    deploy_intel_required_under_1000ms_rate: float = 0.8
    deploy_intel_wiki_dir: str = str(PROJECT_ROOT / "data" / "wiki")
    deploy_intel_wiki_min_entity_docs: int = 2
    wiki_learning_requires_explicit_trigger: bool = True
    wiki_allowed_update_triggers: str = "deploy-intelligence,feedback-auto-helpful,admin-api"
    wiki_require_sources_for_answer_pages: bool = True
    wiki_enforce_feedback_confidence: bool = True
    wiki_auto_file_min_confidence: float = 0.8
    session_store_path: str = str(PROJECT_ROOT / "data" / "indexes" / "chat_sessions.json")
    session_context_max_messages: int = 6
    chunk_size_chars: int = 1000
    chunk_overlap_chars: int = 150
    retrieval_top_k: int = 3
    retrieval_orchestrator: str = "custom"
    retrieval_entity_max_terms: int = 5
    retrieval_entity_definition_max_terms: int = 10
    retrieval_lexical_short_query_max_terms: int = 4
    retrieval_lexical_short_phrase_max_terms: int = 3
    retrieval_lexical_acronym_min_len: int = 2
    retrieval_lexical_acronym_max_len: int = 6
    retrieval_answer_timeout_seconds: float = 20.0
    retrieval_search_cache_enabled: bool = True
    retrieval_search_cache_ttl_seconds: int = 10800
    retrieval_search_cache_max_entries: int = 200
    cache_multilevel_enabled: bool = True  # NEW: Enable L1/L2/L3 caching
    cache_l1_max_size: int = 500  # NEW: In-memory cache size
    cache_l1_ttl_seconds: int = 300  # NEW: L1 TTL (5 min)
    cache_l2_ttl_seconds: int = 3600  # NEW: L2 TTL (1 hour)
    retrieval_wiki_first_enabled: bool = True
    retrieval_wiki_top_k: int = 4
    retrieval_wiki_min_score: float = 1.4
    semantic_cache_enabled: bool = True
    semantic_cache_collection: str = "training_semantic_cache"
    semantic_cache_similarity_threshold: float = 0.88
    semantic_cache_mid_similarity_threshold: float = 0.80
    semantic_cache_top_k: int = 5
    semantic_cache_ttl_days: int = 30
    semantic_cache_learn_from_runtime: bool = True
    semantic_cache_max_answer_chars: int = 2200
    warm_cache_enabled: bool = True
    warm_cache_on_deploy: bool = True
    warm_cache_blocking: bool = False
    warm_cache_max_models: int = 3
    warm_cache_workers_per_model: int = 1
    warm_cache_max_docs: int = 0
    warm_cache_questions_per_doc: int = 8
    warm_cache_retry_max: int = 2
    warm_cache_generation_timeout_seconds: float = 180.0
    warm_cache_retry_backoff_seconds: float = 1.5
    warm_cache_models: str = ""
    warm_cache_prompt_max_chars: int = 7000
    benchmark_judge_timeout_seconds: float = 40.0
    query_similarity_tracking_enabled: bool = True
    query_similarity_collection: str = "training_query_signatures"
    query_similarity_threshold: float = 0.9
    query_similarity_top_k: int = 5
    exact_cache_backend: str = "memory"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_exact_cache_ttl_seconds: int = 10800
    redis_exact_cache_prefix: str = "retrieval:exact"
    retrieval_llm_fallback_enabled: bool = True
    retrieval_llm_fallback_min_chars: int = 80
    retrieval_llm_entity_fallback_min_chars: int = 140
    retrieval_llm_fallback_phrases: str = (
        "i cannot provide,i can't provide,not related,insufficient context,"
        "not enough context,do not have enough information,don't have enough information,"
        "anything else i can help"
    )
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "training_chunks"
    langsmith_enabled: bool = False
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "self-learning-console"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    local_trace_log_enabled: bool = False
    local_trace_log_path: str = str(PROJECT_ROOT / "data" / "traces" / "trace_events.jsonl")
    cleanup_job_enabled: bool = True  # NEW: Enable log rotation/cleanup
    cleanup_log_rotation_max_mb: int = 10  # NEW: Rotate when >10MB
    cleanup_log_retention_days: int = 30  # NEW: Delete logs >30 days old
    cleanup_cache_retention_days: int = 60  # NEW: Delete cache >60 days old

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env",),
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
