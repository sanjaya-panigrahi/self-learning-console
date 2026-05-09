from typing import Any

from app.ingestion.pipeline import (
    approve_pii_file,
    get_last_ingestion_report,
    get_pending_pii_reviews,
    resolve_ingestion_source_dir,
)
from app.jobs.ingestion import run_ingestion_once, run_post_ingestion_tasks


def run_ingestion_job() -> dict[str, Any]:
    report = run_ingestion_once()
    run_post_ingestion_tasks()
    return report


def get_ingestion_report() -> dict[str, Any]:
    return get_last_ingestion_report()


def get_pii_review_queue() -> list[dict[str, Any]]:
    return get_pending_pii_reviews()


def approve_file_for_ingestion(file_path: str, approved_by: str, reason: str) -> dict[str, Any]:
    return approve_pii_file(file_path=file_path, approved_by=approved_by, reason=reason)


def get_ingestion_source() -> str:
    return str(resolve_ingestion_source_dir())
