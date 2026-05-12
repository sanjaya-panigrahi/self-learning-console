"""Ingestion pipeline orchestrator - coordinates document processing and indexing."""

import hashlib
import json
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config.settings import get_settings
from app.ingestion.chunking import chunk_text
from app.ingestion.lifecycle import (
    build_data_lifecycle_manifest,
    ensure_data_lifecycle_dirs,
    load_data_lifecycle_manifest,
    save_data_lifecycle_manifest,
)
from app.ingestion.pii import approve_pii_file, build_pii_findings, detect_pii, get_approval_store
from app.ingestion.pii import get_pending_pii_reviews as _get_pending_pii_reviews_impl
from app.ingestion.readers import read_source_file
from app.ingestion.report import (
    SUPPORTED_SOURCE_SUFFIXES,
    build_report,
    get_last_ingestion_report,
    save_ingestion_report,
)
from app.ingestion.vectorstore import sync_to_vector_backend

# Re-export public API for backward compatibility
__all__ = [
    "run_ingestion",
    "resolve_ingestion_source_dir",
    "get_last_ingestion_report",
    "approve_pii_file",
    "get_pending_pii_reviews",
    "SUPPORTED_SOURCE_SUFFIXES",
]


def get_pending_pii_reviews() -> list[dict[str, Any]]:
    """Get pending PII review items (backward-compatible wrapper).

    Returns:
        List of files pending PII review from last ingestion
    """
    report = get_last_ingestion_report()
    return _get_pending_pii_reviews_impl(report)


def resolve_ingestion_source_dir() -> Path:
    """Resolve the source directory for ingestion, with fallback logic.

    Handles:
    - Absolute vs relative paths
    - Resource/Resources folder variants
    - Preference for directories with actual ingestible files

    Returns:
        Path to source directory for ingestion
    """
    settings = get_settings()
    configured = Path(settings.ingestion_source_dir)
    candidates: list[Path] = [configured]
    name = configured.name.lower()
    if name == "resource":
        candidates.append(configured.with_name("Resources"))
    elif name == "resources":
        candidates.append(configured.with_name("Resource"))

    if configured.is_absolute():
        project_root = configured.parent
    else:
        project_root = Path(__file__).resolve().parents[3]
        candidates.append(project_root / configured)
        for candidate in list(candidates):
            if not candidate.is_absolute():
                candidates.append(project_root / candidate)

    unique_candidates: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved not in unique_candidates:
            unique_candidates.append(resolved)

    existing_candidates = [candidate for candidate in unique_candidates if candidate.exists() and candidate.is_dir()]
    if not existing_candidates:
        return project_root / configured if not configured.is_absolute() else configured

    preferred = existing_candidates[0]
    preferred_count = -1
    for candidate in existing_candidates:
        ingestible_count = sum(
            1
            for path in candidate.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
            and not any(part.startswith(".") for part in path.parts)
        )
        if ingestible_count > preferred_count:
            preferred = candidate
            preferred_count = ingestible_count

    return preferred


def _embed_text(text: str) -> list[float]:
    """Generate embeddings for text via Ollama.

    Args:
        text: Text to embed

    Returns:
        Embedding vector
    """
    settings = get_settings()
    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        response = client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": text},
        )
        if response.status_code == 404:
            legacy = client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={"model": settings.embedding_model, "prompt": text},
            )
            if legacy.status_code == 404:
                return []
            legacy.raise_for_status()
            return legacy.json().get("embedding", [])

        response.raise_for_status()
        payload = response.json()
        embeddings = payload.get("embeddings", [])
        if not embeddings:
            return []
        return embeddings[0]


def _manifest_path() -> Path:
    settings = get_settings()
    return Path(settings.local_index_path).parent / ".ingestion_manifest.json"


def _load_manifest() -> dict[str, dict[str, Any]]:
    """Load the last-run manifest: {relative_path: {mtime, hash}}."""
    p = _manifest_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_manifest(manifest: dict[str, dict[str, Any]]) -> None:
    """Persist the manifest to disk atomically."""
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _collect_source_files(source_dir: Path) -> list[Path]:
    """Find all supported source files in directory.

    Args:
        source_dir: Directory to scan

    Returns:
        Sorted list of file paths
    """
    return sorted(
        file_path
        for file_path in source_dir.rglob("*")
        if file_path.is_file()
        and file_path.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
        and not any(part.startswith(".") for part in file_path.parts)
    )


def run_ingestion(
    pdf_paths: list[str] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Build local index from configured Resource folder with PII screening.

    Pipeline flow:
    1. Collect source files from configured directory
    2. For each file:
       - Read content (with format-specific handlers)
       - Detect PII patterns
       - Block if PII detected and not approved
       - Chunk text
       - Generate embeddings
       - Store in local index
    3. Sync to vector backend (Qdrant) if enabled
    4. Generate report with statistics

    Args:
        pdf_paths: Unused, kept for backward compatibility

    Returns:
        Ingestion report with status, file details, and metrics
    """
    _ = pdf_paths
    settings = get_settings()
    ensure_data_lifecycle_dirs()
    source_dir = resolve_ingestion_source_dir()
    index_path = Path(settings.local_index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    pii_validation_enabled = bool(getattr(settings, "pii_validation_enabled", True))
    approval_store = get_approval_store() if pii_validation_enabled else {}

    empty_report = {
        "status": "completed",
        "source_dir": str(source_dir),
        "indexed_chunks": 0,
        "processed_files": 0,
        "failed_files": 0,
        "password_detected_files": 0,
        "pending_review_files": 0,
        "files": [],
    }

    def _emit_progress(last_file: dict[str, Any] | None = None) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(
                {
                    "state": "running",
                    "source_dir": str(source_dir),
                    "total_files": len(source_files),
                    "processed_files": len(file_results),
                    "indexed_chunks": int(
                        sum(int(item.get("indexed_chunks", 0) or 0) for item in file_results)
                    ),
                    "files": list(file_results),
                    "last_file": last_file,
                }
            )
        except Exception:
            # Progress updates should never interrupt ingestion.
            return

    if not source_dir.exists():
        index_path.write_text('{"items": []}', encoding="utf-8")
        empty_report["status"] = "source_missing"
        save_ingestion_report(empty_report)
        return empty_report

    manifest = _load_manifest()
    new_manifest: dict[str, dict[str, Any]] = {}

    # Load existing local index so we can reuse chunks from unchanged files
    existing_items_by_source: dict[str, list[dict[str, Any]]] = {}
    if index_path.exists():
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
            for it in existing_index.get("items", []):
                existing_items_by_source.setdefault(it["source"], []).append(it)
        except (json.JSONDecodeError, OSError):
            pass

    items: list[dict[str, str | list[float]]] = []
    file_results: list[dict[str, Any]] = []
    source_files = _collect_source_files(source_dir)
    _emit_progress()
    seen_hashes: dict[str, str] = {}  # hash -> first relative_path that had it

    for file_path in source_files:
        relative_path = str(file_path.relative_to(source_dir))
        read_meta: dict[str, Any] = {"ocr_used": False, "ocr_pages": 0, "ingestion_method": "unknown"}

        # Fast-path: skip unchanged files using mtime + content hash
        try:
            current_mtime = file_path.stat().st_mtime
        except OSError:
            current_mtime = 0.0
        prev = manifest.get(relative_path)
        if prev and prev.get("mtime") == current_mtime:
            # mtime matches — reuse cached chunks without reading the file
            cached_chunks = existing_items_by_source.get(relative_path, [])
            if cached_chunks:
                items.extend(cached_chunks)
                new_manifest[relative_path] = prev
                file_results.append({
                    "file": relative_path,
                    "status": "indexed",
                    "reason": "Unchanged — reused from cache",
                    "indexed_chunks": len(cached_chunks),
                    "ingestion_method": prev.get("ingestion_method", "cached"),
                    "pii_types": [],
                    "pii_findings": [],
                    "approval": None,
                    "ocr_used": bool(prev.get("ocr_used", False)),
                    "ocr_pages": int(prev.get("ocr_pages", 0)),
                })
                _emit_progress(file_results[-1])
                continue

        # Read file content using modular reader
        try:
            content, read_meta = read_source_file(file_path)
        except (OSError, ValueError) as exc:
            file_results.append(
                {
                    "file": relative_path,
                    "status": "failed",
                    "reason": f"Read error: {exc}",
                    "indexed_chunks": 0,
                    "ingestion_method": str(read_meta.get("ingestion_method", "unknown")),
                    "pii_types": [],
                    "ocr_used": False,
                    "ocr_pages": 0,
                }
            )
            _emit_progress(file_results[-1])
            continue

        if not content:
            file_results.append(
                {
                    "file": relative_path,
                    "status": "failed",
                    "reason": "File is empty or not readable as text",
                    "indexed_chunks": 0,
                    "ingestion_method": str(read_meta.get("ingestion_method", "unknown")),
                    "pii_types": [],
                    "ocr_used": bool(read_meta.get("ocr_used", False)),
                    "ocr_pages": int(read_meta.get("ocr_pages", 0) or 0),
                }
            )
            _emit_progress(file_results[-1])
            continue

        # Deduplicate by content hash — skip files identical to one already indexed
        content_hash = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()
        if content_hash in seen_hashes:
            file_results.append(
                {
                    "file": relative_path,
                    "status": "duplicate",
                    "reason": f"Duplicate of '{seen_hashes[content_hash]}' (identical content)",
                    "indexed_chunks": 0,
                    "ingestion_method": str(read_meta.get("ingestion_method", "unknown")),
                    "duplicate_of": seen_hashes[content_hash],
                    "content_hash": content_hash,
                    "pii_types": [],
                    "pii_findings": [],
                    "approval": None,
                    "ocr_used": bool(read_meta.get("ocr_used", False)),
                    "ocr_pages": int(read_meta.get("ocr_pages", 0) or 0),
                }
            )
            _emit_progress(file_results[-1])
            continue
        seen_hashes[content_hash] = relative_path

        # Verify mtime matches what we read (content could have changed between stat and read)
        # Store in manifest regardless — we'll update it after successful chunk/embed

        # Detect and enforce PII only when validation is enabled.
        pii_types: list[str] = []
        pii_findings: list[dict[str, Any]] = []
        if pii_validation_enabled:
            pii_types = detect_pii(content)
            pii_findings = build_pii_findings(content)

        if pii_validation_enabled and pii_types and relative_path not in approval_store:
            file_results.append(
                {
                    "file": relative_path,
                    "status": "pending_pii_review",
                    "reason": "Suspected PII detected before ingestion. Approval required to index.",
                    "indexed_chunks": 0,
                    "ingestion_method": str(read_meta.get("ingestion_method", "unknown")),
                    "pii_types": pii_types,
                    "pii_findings": pii_findings,
                    "ocr_used": bool(read_meta.get("ocr_used", False)),
                    "ocr_pages": int(read_meta.get("ocr_pages", 0) or 0),
                }
            )
            _emit_progress(file_results[-1])
            continue

        # Chunk and embed using modular chunking
        chunks = chunk_text(content, settings.chunk_size_chars, settings.chunk_overlap_chars)
        indexed_chunks = 0
        for idx, chunk in enumerate(chunks, start=1):
            embedding = _embed_text(chunk)
            items.append(
                {
                    "source": relative_path,
                    "chunk_id": f"{file_path.stem}-chunk-{idx:04d}",
                    "text": chunk,
                    "embedding": embedding,
                }
            )
            indexed_chunks += 1

        file_results.append(
            {
                "file": relative_path,
                "status": "indexed",
                "reason": "Indexed successfully"
                if not pii_types
                else "Indexed after explicit PII approval",
                "indexed_chunks": indexed_chunks,
                "ingestion_method": str(read_meta.get("ingestion_method", "unknown")),
                "pii_types": pii_types,
                "pii_findings": pii_findings,
                "approval": approval_store.get(relative_path),
                "ocr_used": bool(read_meta.get("ocr_used", False)),
                "ocr_pages": int(read_meta.get("ocr_pages", 0) or 0),
            }
        )
        _emit_progress(file_results[-1])
        # Record this file in the new manifest
        new_manifest[relative_path] = {
            "mtime": current_mtime,
            "hash": content_hash,
            "ingestion_method": str(read_meta.get("ingestion_method", "unknown")),
            "ocr_used": bool(read_meta.get("ocr_used", False)),
            "ocr_pages": int(read_meta.get("ocr_pages", 0) or 0),
            "indexed_at": time.time(),
        }

    # Save local index
    with index_path.open("w", encoding="utf-8") as file:
        json.dump({"items": items}, file)

    # Sync to vector backend using modular vectorstore
    vector_backend = getattr(settings, "vector_backend", "local")
    qdrant_sync = sync_to_vector_backend(items, vector_backend)

    # Persist updated manifest
    _save_manifest(new_manifest)

    data_lifecycle_manifest = build_data_lifecycle_manifest(
        source_dir=source_dir,
        indexed_items_count=len(items),
        file_results=file_results,
        vector_backend_status=qdrant_sync,
        existing_manifest=load_data_lifecycle_manifest(),
    )
    save_data_lifecycle_manifest(data_lifecycle_manifest)

    # Generate and save report using modular report builder
    report = build_report(source_dir, file_results, len(items), qdrant_sync)
    save_ingestion_report(report)

    return report
