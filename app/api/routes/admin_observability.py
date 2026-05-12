from fastapi import APIRouter, Query

from app.api.routes.admin_schemas import BenchmarkRunRequest, DeployIntelligenceRunRequest
from app.core.observability.metrics import MetricsCollector
from app.core.observability.langsmith import get_langsmith_status, get_langsmith_traces, get_local_trace_events
from app.core.prompts.toon import prompt_catalog_summary, prompt_usage_summary
from app.evaluation.service import get_evaluation_summary, get_last_benchmark_report, run_llm_benchmark
from app.jobs.deploy_intelligence import (
    get_deploy_intelligence_status,
    get_last_deploy_intelligence_report,
    trigger_deploy_intelligence_job,
)
from app.jobs.ingestion import get_ingestion_status
from app.retrieval.service.cache import get_retrieval_cache_stats

router = APIRouter()


@router.get("/evaluation-summary")
def evaluation_summary(limit: int = Query(default=200, ge=1, le=2000)) -> dict[str, object]:
    return get_evaluation_summary(limit=limit)


@router.post("/benchmark/run")
def benchmark_run(request: BenchmarkRunRequest) -> dict[str, object]:
    return run_llm_benchmark(max_cases=request.max_cases)


@router.get("/benchmark/last")
def benchmark_last() -> dict[str, object]:
    return get_last_benchmark_report()


@router.post("/deploy-intelligence/run")
def deploy_intelligence_run(request: DeployIntelligenceRunRequest) -> dict[str, object]:
    ingestion_status = get_ingestion_status()
    if str(ingestion_status.get("state", "")).strip().lower() == "running":
        return {
            "status": "blocked_by_indexing",
            "detail": {
                "message": "Deploy intelligence can start only after indexing completes.",
                "ingestion": ingestion_status,
            },
        }
    return trigger_deploy_intelligence_job(force=request.force, blocking=request.blocking)


@router.get("/deploy-intelligence/status")
def deploy_intelligence_status() -> dict[str, object]:
    return get_deploy_intelligence_status()


@router.get("/deploy-intelligence/last")
def deploy_intelligence_last() -> dict[str, object]:
    return get_last_deploy_intelligence_report()


@router.get("/observability-status")
def observability_status() -> dict[str, object]:
    return {"langsmith": get_langsmith_status()}


@router.get("/langsmith-traces")
def langsmith_traces(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, object]:
    return {"traces": get_langsmith_traces(limit=limit)}


@router.get("/local-traces")
def local_traces(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    return {"traces": get_local_trace_events(limit=limit)}


@router.get("/prompt-catalog")
def prompt_catalog() -> dict[str, object]:
    return prompt_catalog_summary()


@router.get("/prompt-usage")
def prompt_usage(limit: int = Query(default=2000, ge=50, le=10000)) -> dict[str, object]:
    return prompt_usage_summary(limit=limit)


@router.get("/runtime-metrics")
def runtime_metrics(limit: int = Query(default=50, ge=1, le=300)) -> dict[str, object]:
    return {
        "query_metrics": MetricsCollector.snapshot(limit=limit),
        "retrieval_cache": get_retrieval_cache_stats(),
    }
