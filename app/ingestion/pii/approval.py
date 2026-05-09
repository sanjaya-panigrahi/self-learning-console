"""PII approval store and management."""

import json
from pathlib import Path
from typing import Any

from app.core.config.settings import PROJECT_ROOT, get_settings


def get_approval_store() -> dict[str, dict[str, str]]:
    """Load PII approval store from disk.

    Returns:
        Dictionary of approved files with approval metadata
    """
    settings = get_settings()
    approval_path = Path(
        getattr(settings, "pii_approval_path", str(PROJECT_ROOT / "data" / "indexes" / "pii_approvals.json"))
    )
    if not approval_path.exists():
        return {}
    try:
        with approval_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_approval_store(store: dict[str, dict[str, str]]) -> None:
    """Save PII approval store to disk.

    Args:
        store: Approval dictionary to persist
    """
    settings = get_settings()
    approval_path = Path(
        getattr(settings, "pii_approval_path", str(PROJECT_ROOT / "data" / "indexes" / "pii_approvals.json"))
    )
    approval_path.parent.mkdir(parents=True, exist_ok=True)
    with approval_path.open("w", encoding="utf-8") as file:
        json.dump(store, file)


def approve_pii_file(file_path: str, approved_by: str, reason: str) -> dict[str, str]:
    """Mark a file as approved for ingestion despite PII.

    Args:
        file_path: Relative path of the file
        approved_by: Name/identifier of approver
        reason: Approval reason

    Returns:
        Approval response with status and metadata
    """
    store = get_approval_store()
    store[file_path] = {"approved_by": approved_by, "reason": reason}
    write_approval_store(store)
    return {"status": "approved", "file": file_path, "approved_by": approved_by}


def get_pending_pii_reviews(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract pending PII review items from ingestion report.

    Args:
        report: Ingestion report dictionary

    Returns:
        List of files pending PII review
    """
    return [item for item in report.get("files", []) if item.get("status") == "pending_pii_review"]
