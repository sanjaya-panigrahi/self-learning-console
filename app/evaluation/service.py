from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from app.core.config.settings import get_settings
from app.core.prompts.toon import render_prompt
from app.feedback.collector.service import get_feedback_summary
from app.retrieval.service import search_retrieval_material


@dataclass(frozen=True)
class BenchmarkCase:
    query: str
    expected_answer: str = ""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _benchmark_report_path() -> Path:
    settings = get_settings()
    return Path(str(settings.benchmark_report_path))


def _benchmark_eval_set_path() -> Path:
    settings = get_settings()
    return Path(str(settings.benchmark_eval_set_path))


def _benchmark_questions_path() -> Path:
    settings = get_settings()
    configured = str(getattr(settings, "benchmark_questions_path", "")).strip()
    if configured:
        return Path(configured)
    return _benchmark_eval_set_path()


def _parse_benchmark_cases(path: Path, max_cases: int) -> list[BenchmarkCase]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    raw_cases = payload.get("cases", []) if isinstance(payload, dict) else []
    parsed: list[BenchmarkCase] = []
    for item in raw_cases:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        parsed.append(
            BenchmarkCase(
                query=query,
                expected_answer=str(item.get("expected_answer", "")).strip(),
            )
        )
    return parsed[: max(1, max_cases)] if parsed else []


def _load_benchmark_cases(max_cases: int) -> list[BenchmarkCase]:
    paths = [_benchmark_questions_path(), _benchmark_eval_set_path()]
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        parsed = _parse_benchmark_cases(path=path, max_cases=max_cases)
        if parsed:
            return parsed
    return []


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return float(ordered[idx])


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        loaded = json.loads(stripped)
        return loaded if isinstance(loaded, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidate = stripped[start : end + 1]
        try:
            loaded = json.loads(candidate)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _judge_with_ollama(
    *,
    query: str,
    answer: str,
    citations: list[dict[str, Any]],
    expected_answer: str,
) -> dict[str, Any]:
    settings = get_settings()
    prompt = render_prompt(
        "evaluation.judge_answer.v1",
        values={
            "query": query,
            "expected_answer": expected_answer or "N/A",
            "answer": answer,
            "citations_json": json.dumps(citations, ensure_ascii=False),
        },
    )
    payload = {
        "model": str(settings.ollama_fast_model or settings.ollama_model),
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    timeout = max(5.0, float(getattr(settings, "benchmark_judge_timeout_seconds", 40.0)))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        response.raise_for_status()
        body = response.json() if response.content else {}
    raw = str(body.get("response", "")).strip() if isinstance(body, dict) else ""
    parsed = _extract_json_object(raw) or {}

    def _score(name: str, fallback: float = 0.0) -> float:
        value = parsed.get(name, fallback)
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return fallback

    return {
        "overall_score": _score("overall_score"),
        "factuality_score": _score("factuality_score"),
        "relevance_score": _score("relevance_score"),
        "usefulness_score": _score("usefulness_score"),
        "notes": str(parsed.get("notes", "")).strip(),
        "judge_model": str(settings.ollama_fast_model or settings.ollama_model),
        "judge_provider": "ollama",
    }


def _judge_answer(
    *,
    query: str,
    answer: str,
    citations: list[dict[str, Any]],
    expected_answer: str,
) -> dict[str, Any]:
    try:
        return _judge_with_ollama(
            query=query,
            answer=answer,
            citations=citations,
            expected_answer=expected_answer,
        )
    except Exception as exc:
        fallback = 0.35 if answer.strip() else 0.0
        return {
            "overall_score": fallback,
            "factuality_score": fallback,
            "relevance_score": fallback,
            "usefulness_score": fallback,
            "notes": f"LLM judge unavailable: {type(exc).__name__}",
            "judge_model": "",
            "judge_provider": "fallback",
        }


def run_llm_benchmark(max_cases: int = 8) -> dict[str, Any]:
    max_cases = max(1, min(int(max_cases), 50))
    cases = _load_benchmark_cases(max_cases=max_cases)
    run_started = _utc_now_iso()

    if not cases:
        report = {
            "status": "no_cases",
            "generated_at": _utc_now_iso(),
            "run_started_at": run_started,
            "cases": [],
            "summary": {
                "case_count": 0,
                "average_score": 0.0,
                "score_p50": 0.0,
                "score_p90": 0.0,
                "cold_latency_ms_avg": 0.0,
                "cold_latency_ms_p95": 0.0,
                "repeat_latency_ms_avg": 0.0,
                "repeat_latency_ms_p95": 0.0,
                "repeat_cache_hit_rate": 0.0,
                "repeat_under_1000ms_rate": 0.0,
            },
            "message": "No benchmark cases found. Add JSON cases under the configured benchmark_questions_path or benchmark_eval_set_path.",
        }
        path = _benchmark_report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    rows: list[dict[str, Any]] = []
    cold_latencies: list[float] = []
    repeat_latencies: list[float] = []
    scores: list[float] = []
    repeat_cache_hits = 0

    for case in cases:
        cold_t0 = perf_counter()
        cold = search_retrieval_material(query=case.query, top_k=6)
        cold_latency_ms = (perf_counter() - cold_t0) * 1000.0

        repeat_t0 = perf_counter()
        repeat = search_retrieval_material(query=case.query, top_k=6)
        repeat_latency_ms = (perf_counter() - repeat_t0) * 1000.0

        citations = cold.get("citations", [])
        normalized_citations = citations if isinstance(citations, list) else []
        judge = _judge_answer(
            query=case.query,
            answer=str(cold.get("answer", "")),
            citations=[c for c in normalized_citations if isinstance(c, dict)],
            expected_answer=case.expected_answer,
        )

        score = float(judge.get("overall_score", 0.0) or 0.0)
        repeat_cache_hit = bool(repeat.get("cached") or repeat.get("semantic_cache_hit"))
        if repeat_cache_hit:
            repeat_cache_hits += 1

        cold_latencies.append(cold_latency_ms)
        repeat_latencies.append(repeat_latency_ms)
        scores.append(score)

        rows.append(
            {
                "query": case.query,
                "expected_answer": case.expected_answer,
                "score": round(score, 4),
                "judge": judge,
                "cold_latency_ms": round(cold_latency_ms, 2),
                "repeat_latency_ms": round(repeat_latency_ms, 2),
                "repeat_cache_hit": repeat_cache_hit,
                "answer_confidence": float(cold.get("answer_confidence", 0.0) or 0.0),
                "result_count": int(cold.get("result_count", 0) or 0),
                "answer_preview": str(cold.get("answer", ""))[:200],
            }
        )

    case_count = len(rows)
    report = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "run_started_at": run_started,
        "cases": rows,
        "summary": {
            "case_count": case_count,
            "average_score": round(statistics.fmean(scores), 4) if scores else 0.0,
            "score_p50": round(_percentile(scores, 0.50), 4),
            "score_p90": round(_percentile(scores, 0.90), 4),
            "cold_latency_ms_avg": round(statistics.fmean(cold_latencies), 2) if cold_latencies else 0.0,
            "cold_latency_ms_p95": round(_percentile(cold_latencies, 0.95), 2),
            "repeat_latency_ms_avg": round(statistics.fmean(repeat_latencies), 2) if repeat_latencies else 0.0,
            "repeat_latency_ms_p95": round(_percentile(repeat_latencies, 0.95), 2),
            "repeat_cache_hit_rate": round((repeat_cache_hits / case_count), 4) if case_count else 0.0,
            "repeat_under_1000ms_rate": (
                round(sum(1 for x in repeat_latencies if x < 1000.0) / case_count, 4) if case_count else 0.0
            ),
        },
    }

    path = _benchmark_report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def get_last_benchmark_report() -> dict[str, Any]:
    path = _benchmark_report_path()
    if not path.exists():
        return {
            "status": "not_found",
            "message": "No benchmark report available yet. Run /api/admin/benchmark/run first.",
            "path": str(path),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "message": f"Failed to read benchmark report: {type(exc).__name__}",
            "path": str(path),
        }
    if not isinstance(payload, dict):
        return {
            "status": "error",
            "message": "Benchmark report format is invalid.",
            "path": str(path),
        }
    return payload


def get_evaluation_summary(limit: int = 200) -> dict[str, Any]:
    summary = get_feedback_summary(limit=limit)
    total = int(summary.get("total", 0) or 0)
    helpful_ratio = float(summary.get("helpful_ratio", 0.0) or 0.0)

    thresholds = {
        "healthy": 0.75,
        "watch": 0.55,
        "min_sample": 20,
    }

    if total < thresholds["min_sample"]:
        status = "insufficient_data"
        recommendation = "Collect more feedback samples before evaluating drift trends."
    elif helpful_ratio >= thresholds["healthy"]:
        status = "healthy"
        recommendation = "Answer quality is stable. Keep monitoring trend over time."
    elif helpful_ratio >= thresholds["watch"]:
        status = "watch"
        recommendation = "Quality is degrading. Review low-rated queries and improve retrieval context."
    else:
        status = "drift_risk"
        recommendation = "High drift risk. Reindex priority sources and tune retrieval/answer fallback behavior."

    return {
        "status": status,
        "helpful_ratio": helpful_ratio,
        "total_feedback": total,
        "helpful": int(summary.get("helpful", 0) or 0),
        "not_helpful": int(summary.get("not_helpful", 0) or 0),
        "thresholds": thresholds,
        "recommendation": recommendation,
        "generated_at": datetime.now(UTC).isoformat(),
    }
