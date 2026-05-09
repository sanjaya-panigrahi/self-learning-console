import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.api.routes.admin_schemas import FileAnswerRequest, WikiReviewUpdateRequest
from app.core.config.settings import get_settings as _get_settings
from app.jobs.deploy_intelligence.wiki_linter import run_wiki_lint as _run_wiki_lint
from app.jobs.deploy_intelligence.wiki_writer import write_answer_page as _write_answer_page
from app.jobs.deploy_intelligence.wiki_writer import (
    get_page_review_status as _get_page_review_status,
    get_review_summary as _get_review_summary,
    set_page_review_status as _set_page_review_status,
)

router = APIRouter()


@router.get("/wiki/index")
def wiki_index() -> dict[str, object]:
    """Return the wiki index as structured JSON."""
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    sources_dir = wiki_dir / "sources"
    entities_dir = wiki_dir / "entities"
    answers_dir = wiki_dir / "answers"

    source_pages = sorted([p.stem for p in sources_dir.glob("*.md")] if sources_dir.exists() else [])
    entity_pages = sorted([p.stem for p in entities_dir.glob("*.md")] if entities_dir.exists() else [])
    answer_pages = sorted(
        [p.stem for p in answers_dir.glob("*.md")] if answers_dir.exists() else [],
        reverse=True,
    )

    concepts_dir = wiki_dir / "concepts"
    concept_pages = sorted([p.stem for p in concepts_dir.glob("*.md")] if concepts_dir.exists() else [])

    index_path = wiki_dir / "index.md"
    index_content = index_path.read_text(encoding="utf-8") if index_path.exists() else None

    return {
        "source_pages": source_pages,
        "entity_pages": entity_pages,
        "answer_pages": answer_pages,
        "concept_pages": concept_pages,
        "source_count": len(source_pages),
        "entity_count": len(entity_pages),
        "answer_count": len(answer_pages),
        "concept_count": len(concept_pages),
        "index_markdown": index_content,
        "review_summary": _get_review_summary(wiki_dir),
        "wiki_dir": str(wiki_dir),
    }


@router.get("/wiki/page")
def wiki_page(
    kind: str = Query(default="source", pattern="^(source|entity|answer|concept)$"),
    name: str = Query(..., min_length=1),
) -> dict[str, object]:
    """Return the markdown content of a single wiki page."""
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    subdir_map = {"source": "sources", "entity": "entities", "answer": "answers", "concept": "concepts"}
    page_path = wiki_dir / subdir_map[kind] / f"{name}.md"

    if not page_path.exists():
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {kind}/{name}")

    try:
        page_path.resolve().relative_to(wiki_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page path")

    return {
        "kind": kind,
        "name": name,
        "content": page_path.read_text(encoding="utf-8"),
        "review": _get_page_review_status(wiki_dir, f"{subdir_map[kind]}/{name}.md"),
    }


@router.get("/wiki/log")
def wiki_log() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    log_path = wiki_dir / "log.md"

    if not log_path.exists():
        return {"log": None}

    return {"log": log_path.read_text(encoding="utf-8")}


@router.post("/wiki/file-answer")
def wiki_file_answer(request: FileAnswerRequest) -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    try:
        page = _write_answer_page(
            question=request.question,
            answer=request.answer,
            wiki_dir=wiki_dir,
            confidence=request.confidence,
            sources=request.sources,
            session_id=request.session_id,
            filed_by="admin-api",
            trigger="admin-api",
        )
        return {"status": "filed", "page": page.name, "path": str(page)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/wiki/ui-aligned-qa")
def wiki_ui_aligned_qa() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    qa_path = wiki_dir / "answers" / "ui-aligned-qa.json"

    if not qa_path.exists():
        return {"items": []}

    try:
        data = json.loads(qa_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not isinstance(data, list):
        return {"items": []}

    items: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        question = str(row.get("question", "")).strip()
        answer = str(row.get("answer", "")).strip()
        if question and answer:
            items.append({"question": question, "answer": answer})

    return {"items": items}


@router.get("/wiki/contradictions")
def wiki_contradictions() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    contradiction_path = wiki_dir / "contradictions.json"

    if not contradiction_path.exists():
        return {"contradictions": [], "pairs_checked": 0, "contradictions_found": 0, "generated_at": None}

    try:
        data = json.loads(contradiction_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return data


@router.get("/wiki/lint")
def wiki_lint_report() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    lint_path = wiki_dir / "lint_report.md"

    if not lint_path.exists():
        return {"report": None}

    return {"report": lint_path.read_text(encoding="utf-8")}


@router.post("/wiki/lint")
def wiki_lint_run() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    cards_path = Path(getattr(settings, "deploy_intel_knowledge_cards_path", "") or "data/indexes/knowledge_cards.json")

    if not cards_path.exists():
        raise HTTPException(status_code=404, detail="No knowledge cards found. Run deploy-intelligence first.")

    try:
        cards_data = json.loads(cards_path.read_text(encoding="utf-8"))
        knowledge_cards = cards_data.get("items", [])
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not knowledge_cards:
        raise HTTPException(status_code=404, detail="Knowledge cards list is empty.")

    try:
        model = getattr(settings, "ollama_fast_model", None) or getattr(settings, "ollama_model", "llama3.2:3b")
        result = _run_wiki_lint(
            knowledge_cards=knowledge_cards,
            wiki_dir=wiki_dir,
            model=model,
            ollama_base_url=settings.ollama_base_url,
            timeout_seconds=float(settings.ollama_timeout_seconds) * 2,
        )
        return {"status": "completed", **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/wiki/impact-report")
def wiki_impact_report() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    impact_path = wiki_dir / "impact_report.json"

    if not impact_path.exists():
        return {
            "generated_at": None,
            "changed_sources": [],
            "unchanged_sources": [],
            "deleted_sources": [],
            "counts": {
                "changed_sources": 0,
                "unchanged_sources": 0,
                "deleted_sources": 0,
                "affected_entities": 0,
                "affected_concepts": 0,
            },
            "affected": {
                "source_pages": [],
                "deleted_source_pages": [],
                "entity_pages": [],
                "concept_pages": [],
            },
        }

    try:
        return json.loads(impact_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/wiki/review-summary")
def wiki_review_summary() -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    return _get_review_summary(wiki_dir)


@router.get("/wiki/review-state")
def wiki_review_state(
    kind: str = Query(..., pattern="^(source|entity|concept|answer)$"),
    name: str = Query(..., min_length=1),
) -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    subdir_map = {"source": "sources", "entity": "entities", "concept": "concepts", "answer": "answers"}
    rel_path = f"{subdir_map[kind]}/{name}.md"
    abs_path = wiki_dir / rel_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {kind}/{name}")
    return {"kind": kind, "name": name, "review": _get_page_review_status(wiki_dir, rel_path)}


@router.post("/wiki/review-state")
def wiki_review_state_update(request: WikiReviewUpdateRequest) -> dict[str, object]:
    settings = _get_settings()
    wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
    subdir_map = {"source": "sources", "entity": "entities", "concept": "concepts", "answer": "answers"}
    rel_path = f"{subdir_map[request.kind]}/{request.name}.md"
    abs_path = wiki_dir / rel_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {request.kind}/{request.name}")

    try:
        review = _set_page_review_status(
            wiki_dir,
            rel_path,
            request.status,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "updated",
        "kind": request.kind,
        "name": request.name,
        "review": review,
        "summary": _get_review_summary(wiki_dir),
    }
