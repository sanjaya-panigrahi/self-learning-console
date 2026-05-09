from fastapi.testclient import TestClient
import httpx
import json

from app.ingestion.pipeline import run_ingestion
from app.main import app
from app.retrieval.pipeline import retrieve_context


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reindex_endpoint(monkeypatch) -> None:
    client = TestClient(app)

    def fake_run_reindex() -> dict[str, object]:
        return {
            "status": "completed_with_warnings",
            "indexed_chunks": 2,
            "processed_files": 3,
            "failed_files": 1,
            "password_detected_files": 1,
            "files": [],
        }

    monkeypatch.setattr("app.api.routes.admin.run_reindex", fake_run_reindex)

    response = client.post("/api/admin/reindex")
    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_warnings"
    assert response.json()["password_detected_files"] == 1


def test_upload_training_content(monkeypatch, tmp_path) -> None:
    client = TestClient(app)

    monkeypatch.setattr("app.api.routes.admin.resolve_ingestion_source_dir", lambda: tmp_path)

    response = client.post(
        "/api/admin/upload",
        files={"file": ("policy.txt", b"manifest upload policy", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert response.json()["filename"] == "policy.txt"
    assert (tmp_path / "policy.txt").read_text(encoding="utf-8") == "manifest upload policy"


def test_upload_accepts_pdf_extension(monkeypatch, tmp_path) -> None:
    client = TestClient(app)

    monkeypatch.setattr("app.api.routes.admin.resolve_ingestion_source_dir", lambda: tmp_path)

    response = client.post(
        "/api/admin/upload",
        files={"file": ("policy.pdf", b"pdf payload", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert (tmp_path / "policy.pdf").read_bytes() == b"pdf payload"


def test_upload_accepts_csv_extension(monkeypatch, tmp_path) -> None:
    client = TestClient(app)

    monkeypatch.setattr("app.api.routes.admin.resolve_ingestion_source_dir", lambda: tmp_path)

    response = client.post(
        "/api/admin/upload",
        files={"file": ("policy.csv", b"a,b\n1,2", "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert (tmp_path / "policy.csv").read_bytes() == b"a,b\n1,2"


def test_upload_rejects_unsupported_extension(monkeypatch, tmp_path) -> None:
    client = TestClient(app)

    monkeypatch.setattr("app.api.routes.admin.resolve_ingestion_source_dir", lambda: tmp_path)

    response = client.post(
        "/api/admin/upload",
        files={"file": ("policy.exe", b"not supported", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Supported file types:")


def test_chat_endpoint_with_mocked_ollama(monkeypatch) -> None:
    client = TestClient(app)

    class FakeSettings:
        llm_provider = "ollama"

    monkeypatch.setattr(
        "app.api.routes.chat.retrieve_context",
        lambda query: [
            {
                "source": "policy.txt",
                "chunk_id": "policy-chunk-0001",
                "text": "Manifest upload requires UTF-8 CSV and valid headers.",
            }
        ],
    )
    monkeypatch.setattr("app.generation.pipeline.get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        "app.generation.pipeline._call_ollama",
        lambda prompt: "Manifest upload requires UTF-8 CSV and valid headers.",
    )

    response = client.post(
        "/api/chat",
        json={"query": "What is required for manifest upload?"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Manifest upload requires UTF-8 CSV and valid headers."
    assert response.json()["citations"] == [
        {"source": "policy.txt", "chunk_id": "policy-chunk-0001"}
    ]
    assert response.json()["confidence"] == 0.75


def test_chat_endpoint_returns_ollama_fallback_on_error(monkeypatch) -> None:
    client = TestClient(app)

    class FakeSettings:
        llm_provider = "ollama"

    monkeypatch.setattr(
        "app.api.routes.chat.retrieve_context",
        lambda query: [
            {
                "source": "policy.txt",
                "chunk_id": "policy-chunk-0001",
                "text": "Manifest upload requires UTF-8 CSV and valid headers.",
            }
        ],
    )
    monkeypatch.setattr("app.generation.pipeline.get_settings", lambda: FakeSettings())

    request = httpx.Request("POST", "http://127.0.0.1:11434/api/generate")
    response = httpx.Response(503, request=request)

    def raise_http_error(prompt: str) -> str:
        raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    monkeypatch.setattr("app.generation.pipeline._call_ollama", raise_http_error)

    response = client.post(
        "/api/chat",
        json={"query": "What is required for manifest upload?"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == (
        "I could not reach the local Ollama model. "
        "Please check that Ollama is running and the configured model is pulled."
    )
    assert response.json()["citations"] == [
        {"source": "policy.txt", "chunk_id": "policy-chunk-0001"}
    ]
    assert response.json()["confidence"] == 0.2


def test_run_ingestion_blocks_pii_and_writes_report(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "Resources"
    source_dir.mkdir()
    (source_dir / "clean.txt").write_text("Manifest upload needs UTF-8 and valid headers.", encoding="utf-8")
    (source_dir / "pii.txt").write_text("The password for this account is temporary.", encoding="utf-8")

    index_path = tmp_path / "index.json"
    report_path = tmp_path / "report.json"

    class FakeSettings:
        ingestion_source_dir = str(tmp_path / "Resource")
        local_index_path = str(index_path)
        ingestion_report_path = str(report_path)
        chunk_size_chars = 1000
        chunk_overlap_chars = 150
        ollama_timeout_seconds = 1.0
        embedding_model = "nomic-embed-text"
        ollama_base_url = "http://127.0.0.1:11434"

    monkeypatch.setattr("app.ingestion.pipeline.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.report.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.pipeline._embed_text", lambda text: [0.1, 0.2])

    report = run_ingestion()

    assert report["processed_files"] == 2
    assert report["indexed_chunks"] == 1
    assert report["failed_files"] == 1
    assert report["password_detected_files"] == 1
    assert report["pending_review_files"] == 1
    assert any(item["status"] == "pending_pii_review" for item in report["files"])

    saved_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved_report["password_detected_files"] == 1
    saved_index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(saved_index["items"]) == 1


def test_run_ingestion_reads_pdf_files(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "Resource"
    source_dir.mkdir()
    pdf_path = source_dir / "guide.pdf"
    pdf_path.write_bytes(b"pdf-bytes")

    index_path = tmp_path / "index.json"
    report_path = tmp_path / "report.json"

    class FakeSettings:
        ingestion_source_dir = str(source_dir)
        local_index_path = str(index_path)
        ingestion_report_path = str(report_path)
        chunk_size_chars = 1000
        chunk_overlap_chars = 150
        ollama_timeout_seconds = 1.0
        embedding_model = "nomic-embed-text"
        ollama_base_url = "http://127.0.0.1:11434"

    monkeypatch.setattr("app.ingestion.pipeline.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.report.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.pii.approval.get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        "app.ingestion.pipeline.read_source_file",
        lambda path: ("PDF training content", {"ocr_used": False, "ocr_pages": 0}),
    )
    monkeypatch.setattr("app.ingestion.pipeline._embed_text", lambda text: [0.1, 0.2])

    report = run_ingestion()

    assert report["processed_files"] == 1
    assert report["indexed_chunks"] == 1
    assert report["files"][0]["file"] == "guide.pdf"
    saved_index = json.loads(index_path.read_text(encoding="utf-8"))
    assert saved_index["items"][0]["source"] == "guide.pdf"


def test_run_ingestion_syncs_qdrant_when_enabled(monkeypatch, tmp_path) -> None:
    source_dir = tmp_path / "Resource"
    source_dir.mkdir()
    (source_dir / "guide.txt").write_text("Training content", encoding="utf-8")

    index_path = tmp_path / "index.json"
    report_path = tmp_path / "report.json"

    class FakeSettings:
        ingestion_source_dir = str(source_dir)
        local_index_path = str(index_path)
        ingestion_report_path = str(report_path)
        chunk_size_chars = 1000
        chunk_overlap_chars = 150
        ollama_timeout_seconds = 1.0
        embedding_model = "nomic-embed-text"
        ollama_base_url = "http://127.0.0.1:11434"
        vector_backend = "qdrant"

    monkeypatch.setattr("app.ingestion.pipeline.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.report.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.pii.approval.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.ingestion.pipeline._embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(
        "app.ingestion.pipeline.sync_to_vector_backend",
        lambda items, backend: {"status": "synced", "points_upserted": len(items)},
    )

    report = run_ingestion()

    assert report["vector_backend"] == "qdrant"
    assert report["vector_backend_status"] == {"status": "synced", "points_upserted": 1}


def test_retrieve_context_prefers_qdrant(monkeypatch) -> None:
    class FakeSettings:
        retrieval_top_k = 3
        vector_backend = "qdrant"

    monkeypatch.setattr("app.retrieval.pipeline.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.retrieval.pipeline._load_local_index", lambda: [])
    monkeypatch.setattr("app.retrieval.pipeline._embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(
        "app.retrieval.pipeline.search_qdrant_items",
        lambda vector, top_k: [
            {
                "source": "guide.txt",
                "chunk_id": "guide-chunk-0001",
                "text": "Training content from Qdrant",
            }
        ],
    )

    contexts = retrieve_context("training")

    assert contexts == [
        {
            "source": "guide.txt",
            "chunk_id": "guide-chunk-0001",
            "text": "Training content from Qdrant",
        }
    ]


def test_hidden_dashboard_renders_report(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        "app.api.routes.admin.get_last_ingestion_report",
        lambda: {
            "status": "completed_with_warnings",
            "source_dir": "../Resources",
            "processed_files": 2,
            "indexed_chunks": 1,
            "failed_files": 1,
            "password_detected_files": 1,
            "pending_review_files": 1,
            "vector_backend": "qdrant",
            "vector_backend_status": {"status": "synced", "points_upserted": 1},
            "files": [
                {
                    "file": "clean.txt",
                    "status": "indexed",
                    "indexed_chunks": 1,
                    "pii_types": [],
                    "pii_findings": [],
                    "reason": "Indexed successfully",
                },
                {
                    "file": "pii.txt",
                    "status": "pending_pii_review",
                    "indexed_chunks": 0,
                    "pii_types": ["email"],
                    "pii_findings": [
                        {"type": "email", "severity": "medium", "sample": "us...om"}
                    ],
                    "reason": "Suspected PII detected before ingestion. Approval required to index.",
                },
            ],
        },
    )

    response = client.get("/api/admin/_dashboard")
    assert response.status_code == 200
    assert "Training Agent Hidden Dashboard" in response.text
    assert "pii.txt" in response.text
    assert "Approval required to index" in response.text


def test_ready_endpoint(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        "app.api.routes.health.get_system_health",
        lambda: {
            "status": "ready",
            "vector_backend": "qdrant",
            "source_dir": "../Resources",
            "components": {
                "api": {"status": "up"},
                "ollama": {"status": "up", "status_code": 200},
                "qdrant": {"status": "up", "status_code": 200},
            },
        },
    )

    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_approve_pii_endpoint(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        "app.api.routes.admin.approve_file_for_ingestion",
        lambda file_path, approved_by, reason: {
            "status": "approved",
            "file": file_path,
            "approved_by": approved_by,
        },
    )

    response = client.post(
        "/api/admin/approve-pii",
        json={
            "file": "pii.txt",
            "approved_by": "qa.user",
            "reason": "Approved for internal test indexing",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "approved",
        "file": "pii.txt",
        "approved_by": "qa.user",
    }


def test_material_insight_endpoint_forwards_use_cache(monkeypatch) -> None:
    client = TestClient(app)
    captured: dict[str, object] = {}

    def fake_get_material_insight(
        source: str,
        domain_context: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, object]:
        captured["source"] = source
        captured["domain_context"] = domain_context
        captured["use_cache"] = use_cache
        return {"source": source, "summary": "ok"}

    monkeypatch.setattr("app.api.routes.admin.get_material_insight", fake_get_material_insight)

    response = client.post(
        "/api/admin/material-insight",
        json={
            "source": "Levarti/TXT/Sorting & SortBy Result Sets.txt",
            "domain_context": "enterprise onboarding",
            "use_cache": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"source": "Levarti/TXT/Sorting & SortBy Result Sets.txt", "summary": "ok"}
    assert captured == {
        "source": "Levarti/TXT/Sorting & SortBy Result Sets.txt",
        "domain_context": "enterprise onboarding",
        "use_cache": False,
    }


def test_material_insight_stream_emits_progress_and_result(monkeypatch) -> None:
    client = TestClient(app)

    def fake_get_material_insight(
        source: str,
        domain_context: str | None = None,
        use_cache: bool = True,
        progress_callback=None,
    ) -> dict[str, object]:
        if progress_callback:
            progress_callback("progress", {"stage": "retrieval", "source": source})
        return {
            "source": source,
            "domain_context": domain_context,
            "use_cache": use_cache,
            "summary": "streamed",
        }

    monkeypatch.setattr("app.api.routes.admin.get_material_insight", fake_get_material_insight)

    response = client.post(
        "/api/admin/material-insight-stream",
        json={
            "source": "Levarti/Documents/User Guides/TA Manager_v1.9.pdf",
            "domain_context": "enterprise onboarding",
            "use_cache": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert "event: result" in response.text
    assert "event: end" in response.text
