import json
from pathlib import Path

from app.jobs.deploy_intelligence import job


class _Settings:
    def __init__(self, tmp_path: Path) -> None:
        self.deploy_intel_report_path = str(tmp_path / "deploy_intel_report.json")
        self.deploy_intel_knowledge_cards_path = str(tmp_path / "knowledge_cards.json")
        self.deploy_intel_clusters_path = str(tmp_path / "clusters.json")
        self.benchmark_eval_set_path = str(tmp_path / "benchmark_eval_set.json")
        self.deploy_intel_max_docs = 0
        self.deploy_intel_questions_per_doc = 4
        self.deploy_intel_required_min_questions = 1
        self.deploy_intel_required_repeat_hit_rate = 0.5
        self.deploy_intel_required_under_1000ms_rate = 0.5
        self.ollama_question_model = "qwen2.5:14b"
        self.ollama_fast_model = "llama3.2:3b"
        self.ollama_model = "llama3.1:8b"
        self.ollama_base_url = "http://localhost:11434"
        self.ollama_timeout_seconds = 20.0
        self.warm_cache_prompt_max_chars = 6000


def test_run_deploy_intelligence_pipeline_persists_artifacts(tmp_path, monkeypatch) -> None:
    settings = _Settings(tmp_path)
    monkeypatch.setattr(job, "get_settings", lambda: settings)

    monkeypatch.setattr(
        job,
        "load_local_index",
        lambda: [
            {"source": "A.pdf", "chunk_id": "A-1", "text": "A definition and policy notes"},
            {"source": "A.pdf", "chunk_id": "A-2", "text": "A implementation details"},
            {"source": "B.pdf", "chunk_id": "B-1", "text": "B troubleshooting details"},
        ],
    )
    monkeypatch.setattr(
        job,
        "_build_knowledge_card",
        lambda source, chunks: {
            "title": source,
            "summary": "summary",
            "key_points": ["p1"],
            "entities": [],
            "policy_flags": [],
            "expected_questions": ["what is this"],
        },
    )
    monkeypatch.setattr(
        job,
        "_collect_questions",
        lambda source, chunks, model: [
            {
                "source": source,
                "question": f"what is in {source}",
                "expected_answer": "details",
                "expected_confidence": 0.8,
            }
        ],
    )
    monkeypatch.setattr(job, "_process_source", lambda source, chunks, model: 2)
    monkeypatch.setattr(job, "get_similarity_stats", lambda: {"enabled": True, "points": 4})
    monkeypatch.setattr(
        job,
        "run_llm_benchmark",
        lambda max_cases: {
            "summary": {
                "repeat_semantic_cache_hit_rate": 1.0,
                "repeat_under_1000ms_rate": 1.0,
            },
            "cases": [{"query": "what is in A.pdf"}],
        },
    )

    report = job.run_deploy_intelligence_pipeline()

    assert report["gate_passed"] is True
    assert Path(settings.deploy_intel_report_path).exists()
    assert Path(settings.deploy_intel_knowledge_cards_path).exists()
    assert Path(settings.benchmark_eval_set_path).exists()
    assert Path(settings.deploy_intel_clusters_path).exists()

    persisted = json.loads(Path(settings.deploy_intel_report_path).read_text(encoding="utf-8"))
    assert persisted["summary"]["documents"] == 2


def test_get_last_deploy_intelligence_report_not_found(tmp_path, monkeypatch) -> None:
    settings = _Settings(tmp_path)
    monkeypatch.setattr(job, "get_settings", lambda: settings)

    payload = job.get_last_deploy_intelligence_report()

    assert payload["status"] == "not_found"
