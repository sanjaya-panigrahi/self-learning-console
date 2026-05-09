import json
import queue
import threading

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from app.api.routes.admin_schemas import MaterialInsightRequest, PiiApprovalRequest
from app.ingestion.pipeline import SUPPORTED_SOURCE_SUFFIXES, resolve_ingestion_source_dir
from app.jobs.ingestion import get_ingestion_status, trigger_ingestion_job
from app.retrieval.insights import get_material_insight
from app.services.ingestion_service import (
    approve_file_for_ingestion,
    get_ingestion_report,
    get_ingestion_source,
    get_pii_review_queue,
)

router = APIRouter()

ALLOWED_UPLOAD_SUFFIXES = SUPPORTED_SOURCE_SUFFIXES


@router.post("/reindex")
def reindex() -> dict[str, object]:
    """Trigger async reindex; returns immediately."""
    return trigger_ingestion_job()


@router.get("/ingestion/status")
def get_ingestion_status_endpoint() -> dict[str, object]:
    """Get current ingestion job status."""
    return get_ingestion_status()


@router.post("/upload")
async def upload_training_content(file: UploadFile = File(...)) -> dict[str, str | int]:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_SUFFIXES))
        raise HTTPException(status_code=400, detail=f"Supported file types: {allowed}")

    target_dir = resolve_ingestion_source_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(filename).name
    payload = await file.read()
    target_path = target_dir / safe_name
    target_path.write_bytes(payload)

    return {
        "status": "uploaded",
        "filename": safe_name,
        "bytes_written": len(payload),
    }


@router.get("/report")
def ingestion_report() -> dict[str, object]:
    return get_ingestion_report()


@router.get("/pii-review")
def pii_review_queue() -> dict[str, object]:
    pending = get_pii_review_queue()
    return {"pending_review_files": len(pending), "items": pending}


@router.post("/material-insight-stream")
def material_insight_stream(request: MaterialInsightRequest) -> StreamingResponse:
    event_queue: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()

    def _progress(event: str, payload: dict[str, object] | None) -> None:
        event_queue.put((event, payload or {}))

    def _run() -> None:
        try:
            result = get_material_insight(
                source=request.source,
                domain_context=request.domain_context,
                use_cache=request.use_cache,
                progress_callback=_progress,
            )
            event_queue.put(("result", result))
        except Exception as exc:  # pragma: no cover - defensive error guard
            event_queue.put(("error", {"message": str(exc)}))
        finally:
            event_queue.put(("end", {}))

    threading.Thread(target=_run, name="material-insight-stream", daemon=True).start()

    def _stream():
        while True:
            event, payload = event_queue.get()
            yield f"event: {event}\n"
            yield f"data: {json.dumps(payload)}\n\n"
            if event == "end":
                break

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/approve-pii")
def approve_pii(request: PiiApprovalRequest) -> dict[str, str]:
    return approve_file_for_ingestion(
        file_path=request.file,
        approved_by=request.approved_by,
        reason=request.reason,
    )


@router.get("/_dashboard", include_in_schema=False, response_class=HTMLResponse)
def hidden_dashboard() -> HTMLResponse:
    report = get_ingestion_report()
    rows = []
    for item in report.get("files", []):
        pii_findings = item.get("pii_findings", [])
        pii_cells = "<br>".join(
            f"{finding.get('type')} ({finding.get('severity')}): {finding.get('sample')}"
            for finding in pii_findings
        ) or "-"
        approval = item.get("approval") or {}
        approval_label = (
            f"Approved by {approval.get('approved_by', '-')}<br>{approval.get('reason', '-') }"
            if approval
            else "-"
        )
        badge_color = {
            "indexed": "#12715b",
            "pending_pii_review": "#9a6700",
            "failed": "#a40e26",
        }.get(item.get("status", ""), "#4b5563")
        rows.append(
            "<tr>"
            f"<td>{item.get('file', '-')}</td>"
            f"<td><span style='background:{badge_color};color:#fff;padding:4px 8px;border-radius:999px;font-size:12px'>{item.get('status', '-')}</span></td>"
            f"<td>{item.get('indexed_chunks', 0)}</td>"
            f"<td>{pii_cells}</td>"
            f"<td>{approval_label}</td>"
            f"<td>{item.get('reason', '-')}</td>"
            "</tr>"
        )

    body_rows = "".join(rows) or "<tr><td colspan='6'>No ingestion report available.</td></tr>"
    html = (
        "<html><head><title>Training Agent Hidden Dashboard</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px;background:#f4f7fb;color:#17202a;}"
        ".cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0;}"
        ".card{background:#fff;border:1px solid #dbe3ec;border-radius:14px;padding:16px;box-shadow:0 8px 20px rgba(0,0,0,0.04);}"
        "table{border-collapse:collapse;width:100%;background:#fff;border-radius:14px;overflow:hidden;}"
        "th,td{border:1px solid #e5e7eb;padding:10px;text-align:left;vertical-align:top;}"
        "th{background:#eef4fb;} .summary{margin-bottom:16px;} .meta{color:#5b6470;font-size:14px;}"
        "</style></head><body>"
        "<h1>Training Agent Hidden Dashboard</h1>"
        f"<div class='meta'><strong>Source directory:</strong> {report.get('source_dir', get_ingestion_source())} | "
        f"<strong>Status:</strong> {report.get('status', '-')} | "
        f"<strong>Vector backend:</strong> {report.get('vector_backend', '-')}</div>"
        "<div class='cards'>"
        f"<div class='card'><div>Processed Files</div><h2>{report.get('processed_files', 0)}</h2></div>"
        f"<div class='card'><div>Indexed Chunks</div><h2>{report.get('indexed_chunks', 0)}</h2></div>"
        f"<div class='card'><div>Password Flags</div><h2>{report.get('password_detected_files', report.get('pii_detected_files', 0))}</h2></div>"
        f"<div class='card'><div>Pending Review</div><h2>{report.get('pending_review_files', 0)}</h2></div>"
        "</div>"
        f"<div class='summary'><strong>Vector backend status:</strong> {report.get('vector_backend_status', {}).get('status', '-')}<br>"
        f"<strong>Pending review queue:</strong> {len(get_pii_review_queue())}</div>"
        "<table><thead><tr><th>File</th><th>Status</th><th>Indexed Chunks</th><th>PII Findings</th><th>Approval</th><th>Reason</th></tr></thead>"
        f"<tbody>{body_rows}</tbody></table></body></html>"
    )
    return HTMLResponse(content=html)
