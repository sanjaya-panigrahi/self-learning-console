import json
from pathlib import Path

from app.evaluation import service


class _Settings:
    def __init__(self, report_path: Path, eval_set_path: Path) -> None:
        self.benchmark_report_path = str(report_path)
        self.benchmark_eval_set_path = str(eval_set_path)
        self.benchmark_judge_timeout_seconds = 10.0
        self.ollama_base_url = "http://localhost:11434"
        self.ollama_model = "llama3.1:8b"
        self.ollama_fast_model = "llama3.2:3b"


def test_run_llm_benchmark_uses_eval_set_and_persists_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "benchmark_report.json"
    eval_set_path = tmp_path / "benchmark_eval_set.json"
    eval_set_path.write_text(
        json.dumps(
            {
                "cases": [
                    {"query": "what is a record identifier", "expected_answer": "Unique record key"},
                    {"query": "what is an approval gate", "expected_answer": "Policy authorization checkpoint"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(service, "get_settings", lambda: _Settings(report_path, eval_set_path))

    call_count: dict[str, int] = {}

    def _fake_search(*, query: str, top_k: int = 6, domain_context=None):
        count = call_count.get(query, 0) + 1
        call_count[query] = count
        return {
            "answer": f"answer for {query}",
            "answer_confidence": 0.8,
            "result_count": top_k,
            "citations": [{"source": "Rules.txt", "chunk_id": "Rules-chunk-0001"}],
            "cached": count > 1,
            "semantic_cache_hit": count > 1,
        }

    monkeypatch.setattr(service, "search_retrieval_material", _fake_search)
    monkeypatch.setattr(
        service,
        "_judge_answer",
        lambda **kwargs: {
            "overall_score": 0.9,
            "factuality_score": 0.9,
            "relevance_score": 0.9,
            "usefulness_score": 0.9,
            "notes": "ok",
            "judge_model": "test-model",
            "judge_provider": "ollama",
        },
    )

    report = service.run_llm_benchmark(max_cases=2)

    assert report["status"] == "ok"
    assert report["summary"]["case_count"] == 2
    assert report["summary"]["repeat_cache_hit_rate"] == 1.0
    assert len(report["cases"]) == 2
    assert report_path.exists()

    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["summary"]["average_score"] == 0.9


def test_get_last_benchmark_report_not_found(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "missing_report.json"
    eval_set_path = tmp_path / "missing_eval_set.json"

    monkeypatch.setattr(service, "get_settings", lambda: _Settings(report_path, eval_set_path))

    payload = service.get_last_benchmark_report()

    assert payload["status"] == "not_found"
