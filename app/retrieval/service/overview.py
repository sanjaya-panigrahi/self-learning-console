from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.ingestion.pipeline import get_last_ingestion_report, resolve_ingestion_source_dir
from app.retrieval.index import load_local_index
from app.retrieval.service.scoring import trim_excerpt


def get_retrieval_overview(
    ingestion_report_getter: Callable[[], dict[str, Any]] = get_last_ingestion_report,
    index_loader: Callable[[], list[dict[str, Any]]] = load_local_index,
) -> dict[str, Any]:
    report = ingestion_report_getter()
    report_files = {item.get("file"): item for item in report.get("files", [])}
    indexed_items = index_loader()

    materials_by_source: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "source": "",
            "chunk_count": 0,
            "preview": "",
            "sample_chunks": [],
            "status": "indexed",
            "pii_types": [],
            "reason": "Indexed successfully",
        }
    )

    for item in indexed_items:
        source = str(item.get("source", "unknown"))
        text = str(item.get("text", ""))
        entry = materials_by_source[source]
        entry["source"] = source
        entry["chunk_count"] += 1
        if text and not entry["preview"]:
            entry["preview"] = trim_excerpt(text)
        if text and len(entry["sample_chunks"]) < 2:
            entry["sample_chunks"].append(trim_excerpt(text, limit=180))

        report_item = report_files.get(source)
        if report_item:
            entry["status"] = report_item.get("status", entry["status"])
            entry["pii_types"] = report_item.get("pii_types", [])
            entry["reason"] = report_item.get("reason", entry["reason"])

    for source, report_item in report_files.items():
        if source in materials_by_source:
            continue
        materials_by_source[source] = {
            "source": source,
            "chunk_count": int(report_item.get("indexed_chunks", 0)),
            "preview": "",
            "sample_chunks": [],
            "status": report_item.get("status", "unknown"),
            "pii_types": report_item.get("pii_types", []),
            "reason": report_item.get("reason", ""),
        }

    materials = sorted(
        materials_by_source.values(),
        key=lambda item: (-int(item.get("chunk_count", 0)), str(item.get("source", ""))),
    )

    indexed_materials = [item for item in materials if item.get("status") == "indexed"]
    blocked_materials = [item for item in materials if item.get("status") == "pending_pii_review"]
    failed_materials = [item for item in materials if item.get("status") == "failed"]

    return {
        "source_dir": report.get("source_dir", str(resolve_ingestion_source_dir())),
        "material_count": len(materials),
        "searchable_material_count": len(indexed_materials),
        "blocked_material_count": len(blocked_materials),
        "failed_material_count": len(failed_materials),
        "chunk_count": sum(int(item.get("chunk_count", 0)) for item in materials),
        "materials": materials,
        "top_materials": materials[:5],
    }


__all__ = ["get_retrieval_overview"]
