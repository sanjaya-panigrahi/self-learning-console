"""Ingestion report generation and retrieval."""

import json
from pathlib import Path
from typing import Any

from app.core.config.settings import get_settings

SUPPORTED_SOURCE_SUFFIXES = {
    ".txt",
    ".md",
    ".pdf",
    ".csv",
    ".json",
    ".yml",
    ".yaml",
    ".log",
    ".xml",
    ".html",
    ".htm",
}


def get_last_ingestion_report() -> dict[str, Any]:
    """Load the most recent ingestion report from disk.

    Returns:
        Ingestion report dictionary with status and file details
    """
    settings = get_settings()
    report_path = Path(settings.ingestion_report_path)
    if not report_path.exists():
        return {
            "status": "not_run",
            "source_dir": "",
            "indexed_chunks": 0,
            "processed_files": 0,
            "failed_files": 0,
            "password_detected_files": 0,
            "pending_review_files": 0,
            "files": [],
        }

    with report_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_ingestion_report(report: dict[str, Any]) -> None:
    """Save ingestion report to disk.

    Args:
        report: Report dictionary to persist
    """
    settings = get_settings()
    report_path = Path(settings.ingestion_report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as file:
        json.dump(report, file)


def build_report(
    source_dir: Path,
    file_results: list[dict[str, Any]],
    indexed_items_count: int,
    vector_backend_status: dict[str, Any],
) -> dict[str, Any]:
    """Construct a complete ingestion report.

    Args:
        source_dir: Source directory path
        file_results: List of file processing results
        indexed_items_count: Total number of indexed chunks
        vector_backend_status: Status from vector store sync

    Returns:
        Complete ingestion report
    """
    failed_files = [item for item in file_results if item["status"] != "indexed"]
    pii_files = [item for item in file_results if item.get("pii_types")]
    pending_review_files = [item for item in file_results if item["status"] == "pending_pii_review"]
    duplicate_files = [item for item in file_results if item["status"] == "duplicate"]
    has_warning = bool(failed_files) or vector_backend_status.get("status") == "failed"

    vector_backend = getattr(get_settings(), "vector_backend", "local")
    data_indexes_dir = Path(getattr(get_settings(), "data_indexes_dir", Path("data/indexes")))

    return {
        "status": "completed_with_warnings" if has_warning else "completed",
        "source_dir": str(source_dir),
        "indexed_chunks": indexed_items_count,
        "processed_files": len(file_results),
        "failed_files": len(failed_files),
        "duplicate_files": len(duplicate_files),
        "password_detected_files": len(pii_files),
        "pending_review_files": len(pending_review_files),
        "vector_backend": vector_backend,
        "data_lifecycle_manifest_path": str(data_indexes_dir / "lifecycle_manifest.json"),
        "vector_backend_status": vector_backend_status,
        "files": file_results,
    }
