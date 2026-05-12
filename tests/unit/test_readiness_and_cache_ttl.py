from fastapi.testclient import TestClient

from app.main import app
from app.retrieval.service.cache import (
    clear_retrieval_search_cache,
    get_cached_retrieval_search,
    set_cached_retrieval_search,
)


def test_ready_returns_503_when_degraded(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        "app.api.routes.health.get_system_health",
        lambda: {
            "status": "degraded",
            "vector_backend": "qdrant",
            "components": {
                "api": {"status": "up"},
                "ollama": {"status": "down"},
                "qdrant": {"status": "up"},
            },
        },
    )

    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_ready_returns_200_when_ready(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        "app.api.routes.health.get_system_health",
        lambda: {
            "status": "ready",
            "vector_backend": "qdrant",
            "components": {
                "api": {"status": "up"},
                "ollama": {"status": "up"},
                "qdrant": {"status": "up"},
            },
        },
    )

    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_retrieval_cache_ttl_expiry(monkeypatch) -> None:
    class FakeSettings:
        retrieval_search_cache_enabled = True
        cache_multilevel_enabled = False
        retrieval_search_cache_ttl_seconds = 1
        retrieval_search_cache_max_entries = 200
        exact_cache_backend = "memory"

    monkeypatch.setattr("app.retrieval.service.cache.get_settings", lambda: FakeSettings())
    now = {"value": 1_000.0}
    monkeypatch.setattr("app.retrieval.service.cache.time.time", lambda: now["value"])

    clear_retrieval_search_cache()
    payload = {"orchestrator": "custom", "answer": "ok"}
    set_cached_retrieval_search("q", None, 3, "custom", payload)

    cached = get_cached_retrieval_search("q", None, 3, "custom")
    assert cached is not None
    assert cached["cached"] is True

    now["value"] += 20

    expired = get_cached_retrieval_search("q", None, 3, "custom")
    assert expired is None
