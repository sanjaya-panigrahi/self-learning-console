"""Tests for the standardized ingestion data lifecycle contract."""

from pathlib import Path

from app.ingestion import lifecycle


def test_lifecycle_dirs_and_manifest_round_trip(monkeypatch, tmp_path) -> None:
    class FakeSettings:
        data_raw_dir = str(tmp_path / "data" / "raw")
        data_processed_dir = str(tmp_path / "data" / "processed")
        data_indexes_dir = str(tmp_path / "data" / "indexes")
        data_traces_dir = str(tmp_path / "data" / "traces")
        local_index_path = str(tmp_path / "data" / "indexes" / "local_index.json")
        ingestion_report_path = str(tmp_path / "data" / "indexes" / "ingestion_report.json")
        local_trace_log_path = str(tmp_path / "data" / "traces" / "trace_events.jsonl")

    monkeypatch.setattr(lifecycle, "get_settings", lambda: FakeSettings())

    dirs = lifecycle.ensure_data_lifecycle_dirs()
    assert Path(dirs["raw_dir"]).exists()
    assert Path(dirs["processed_dir"]).exists()
    assert Path(dirs["indexes_dir"]).exists()
    assert Path(dirs["traces_dir"]).exists()

    manifest = lifecycle.build_data_lifecycle_manifest(
        source_dir=tmp_path / "Resource",
        indexed_items_count=7,
        file_results=[
            {"file": "docs/a.txt", "status": "indexed"},
            {"file": "docs/b.txt", "status": "failed"},
        ],
        vector_backend_status={"status": "completed"},
    )

    saved_path = lifecycle.save_data_lifecycle_manifest(manifest)
    assert saved_path.exists()

    loaded = lifecycle.load_data_lifecycle_manifest()
    assert loaded["contract"]["raw_dir"] == str(tmp_path / "data" / "raw")
    assert loaded["summary"]["indexed_items_count"] == 7
    assert loaded["summary"]["failed_files"] == 1
    assert loaded["indexes"]["data_lifecycle_manifest_path"].endswith("lifecycle_manifest.json")
