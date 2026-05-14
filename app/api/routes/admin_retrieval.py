from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.routes.admin_schemas import (
    FeedbackRecordRequest,
    MaterialInsightRequest,
    RetrievalSearchRequest,
    SeedSuggestedQuestionsRequest,
    WarmCacheRunRequest,
)
from app.feedback.collector.service import get_feedback_summary, record_feedback
from app.jobs.ingestion import get_ingestion_status
from app.jobs.seed_questions import run_seed_suggested_questions
from app.jobs.warm_cache import get_warm_cache_status, trigger_warm_cache_job
from app.retrieval.insights import clear_material_insight_cache, get_material_insight
from app.retrieval.service import (
    get_retrieval_overview,
    render_chunk_page_image,
    resolve_visual_reference_source,
    search_retrieval_material,
)
from app.retrieval.service.cache import clear_retrieval_search_cache
from app.retrieval.service.semantic_cache import clear_semantic_cache, get_semantic_cache_stats
from app.retrieval.service.similarity_tracker import get_similarity_stats

router = APIRouter()


@router.get("/retrieval-overview")
def retrieval_overview() -> dict[str, object]:
    return get_retrieval_overview()


@router.post("/retrieval-search")
def retrieval_search(request: RetrievalSearchRequest) -> dict[str, object]:
    return search_retrieval_material(
        query=request.query,
        domain_context=request.domain_context,
        top_k=request.top_k,
        orchestrator=request.orchestrator,
    )


@router.post("/material-insight")
def material_insight(request: MaterialInsightRequest) -> dict[str, object]:
    return get_material_insight(
        source=request.source,
        domain_context=request.domain_context,
        use_cache=request.use_cache,
    )


@router.post("/material-insight-cache/clear")
def clear_material_insight_cache_route() -> dict[str, str]:
    clear_material_insight_cache()
    return {"status": "cleared"}


@router.post("/retrieval-search-cache/clear")
def clear_retrieval_search_cache_route() -> dict[str, str]:
    clear_retrieval_search_cache()
    return {"status": "cleared"}


@router.post("/semantic-cache/clear")
def clear_semantic_cache_route() -> dict[str, str]:
    clear_semantic_cache()
    return {"status": "cleared"}


@router.get("/semantic-cache/stats")
def semantic_cache_stats() -> dict[str, object]:
    return get_semantic_cache_stats()


@router.get("/similarity/stats")
def similarity_stats() -> dict[str, object]:
    return get_similarity_stats()


@router.post("/warm-cache/run")
def warm_cache_run(request: WarmCacheRunRequest) -> dict[str, object]:
    ingestion_status = get_ingestion_status()
    if str(ingestion_status.get("state", "")).strip().lower() == "running":
        return {
            "status": "blocked_by_indexing",
            "detail": {
                "message": "Warm cache can start only after indexing completes.",
                "ingestion": ingestion_status,
            },
        }
    return trigger_warm_cache_job(force=request.force)


@router.get("/warm-cache/status")
def warm_cache_status() -> dict[str, object]:
    return get_warm_cache_status()


@router.post("/seed-suggested-questions")
def seed_suggested_questions(request: SeedSuggestedQuestionsRequest) -> dict[str, object]:
    """Pre-seed the semantic cache with answers for all suggested questions.

    Reads ``suggested_questions`` from every material-insight cache entry,
    runs each through the live retrieval pipeline, and stores the answers in
    the semantic cache so users get instant responses when they click a
    suggested question in the UI.
    """
    return run_seed_suggested_questions(
        force=request.force,
        concurrency=request.concurrency,
    )


@router.post("/feedback")
def submit_feedback(request: FeedbackRecordRequest) -> dict[str, object]:
    return record_feedback(
        session_id=request.session_id,
        helpful=request.helpful,
        query=request.query,
        retrieval_query=request.retrieval_query,
        answer_model=request.answer_model,
        answer_confidence=request.answer_confidence,
        result_count=request.result_count,
        sources=request.sources,
        comment=request.comment,
        answer=request.answer,
    )


@router.get("/feedback-summary")
def feedback_summary(limit: int = Query(default=200, ge=1, le=2000)) -> dict[str, object]:
    return get_feedback_summary(limit=limit)


@router.get("/chunk-page-image")
def chunk_page_image(
    source: str = Query(..., min_length=1),
    chunk_text: str = Query(..., min_length=4),
) -> FileResponse:
    img_path = render_chunk_page_image(source=source, chunk_text=chunk_text)
    if not img_path or not img_path.exists():
        raise HTTPException(status_code=404, detail="Page image could not be generated")
    return FileResponse(img_path, media_type="image/png", filename=img_path.name)


@router.get("/visual-reference-document")
def visual_reference_document(source: str = Query(..., min_length=1)) -> FileResponse:
    source_path = resolve_visual_reference_source(source)
    if not source_path or not source_path.exists():
        raise HTTPException(status_code=404, detail="Visual reference source not found")
    if source_path.suffix.lower() == ".pdf":
        return FileResponse(
            source_path,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=\"{source_path.name}\""},
        )
    return FileResponse(source_path, filename=source_path.name)
