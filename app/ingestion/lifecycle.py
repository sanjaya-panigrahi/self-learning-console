"""Data lifecycle contract for raw, processed, indexes, and traces artifacts."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from app.core.config.settings import get_settings


@dataclass(frozen=True)
class DataLifecycleContract:
    """Canonical data layout used by ingestion and downstream jobs."""

    contract_version: str
    raw_dir: str
    processed_dir: str
    indexes_dir: str
    traces_dir: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_data_lifecycle_contract() -> DataLifecycleContract:
    """Build the canonical lifecycle contract from settings."""
    settings = get_settings()
    return DataLifecycleContract(
        contract_version="1.0",
        raw_dir=str(Path(getattr(settings, "data_raw_dir", Path("data/raw")))),
        processed_dir=str(Path(getattr(settings, "data_processed_dir", Path("data/processed")))),
        indexes_dir=str(Path(getattr(settings, "data_indexes_dir", Path("data/indexes")))),
        traces_dir=str(Path(getattr(settings, "data_traces_dir", Path("data/traces")))),
    )


def ensure_data_lifecycle_dirs() -> dict[str, str]:
    """Create the canonical lifecycle directories if they are missing."""
    contract = get_data_lifecycle_contract()
    directories = {
        "raw_dir": contract.raw_dir,
        "processed_dir": contract.processed_dir,
        "indexes_dir": contract.indexes_dir,
        "traces_dir": contract.traces_dir,
    }
    for path in directories.values():
        Path(path).mkdir(parents=True, exist_ok=True)
    return directories


def lifecycle_manifest_path() -> Path:
    """Return the standardized lifecycle manifest path."""
    contract = get_data_lifecycle_contract()
    return Path(contract.indexes_dir) / "lifecycle_manifest.json"


def build_data_lifecycle_manifest(
    *,
    source_dir: Path,
    indexed_items_count: int,
    file_results: list[dict[str, Any]],
    vector_backend_status: dict[str, Any],
    existing_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a manifest that documents the raw/processed/index artifact contract."""
    contract = get_data_lifecycle_contract()
    source_dir = source_dir.resolve(strict=False)
    now = int(time.time())
    processed_count = sum(1 for item in file_results if item.get("status") == "indexed")
    failed_count = sum(1 for item in file_results if item.get("status") != "indexed")

    manifest = {
        "generated_at": now,
        "contract": contract.to_dict(),
        "raw": {
            "source_dir": str(source_dir),
            "sources": sorted(
                str(Path(item.get("file", "")))
                for item in file_results
                if item.get("file")
            ),
        },
        "processed": {
            "directory": contract.processed_dir,
            "processed_files": processed_count,
            "failed_files": failed_count,
        },
        "indexes": {
            "directory": contract.indexes_dir,
            "local_index_path": str(Path(get_settings().local_index_path)),
            "ingestion_report_path": str(Path(get_settings().ingestion_report_path)),
            "data_lifecycle_manifest_path": str(lifecycle_manifest_path()),
        },
        "traces": {
            "directory": contract.traces_dir,
            "local_trace_log_path": str(Path(getattr(get_settings(), "local_trace_log_path", str(Path(contract.traces_dir) / "trace_events.jsonl")))),
        },
        "vector_backend": vector_backend_status,
        "summary": {
            "indexed_items_count": indexed_items_count,
            "indexed_files": processed_count,
            "failed_files": failed_count,
        },
    }

    if existing_manifest:
        manifest["previous_manifest"] = existing_manifest

    return manifest


def save_data_lifecycle_manifest(manifest: dict[str, Any]) -> Path:
    """Persist the lifecycle manifest atomically."""
    path = lifecycle_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def load_data_lifecycle_manifest() -> dict[str, Any]:
    """Load the lifecycle manifest if it exists."""
    path = lifecycle_manifest_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}
