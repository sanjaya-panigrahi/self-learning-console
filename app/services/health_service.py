from typing import Any

import httpx

from app.core.config.settings import get_settings
from app.ingestion.pipeline import resolve_ingestion_source_dir


def _probe_http(url: str, timeout: float) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
        return {
            "status": "up" if response.is_success else "down",
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"status": "down", "reason": str(exc)}


def get_system_health() -> dict[str, Any]:
    settings = get_settings()
    source_dir = str(resolve_ingestion_source_dir())
    components = {
        "api": {"status": "up"},
        "ollama": _probe_http(f"{settings.ollama_base_url}/api/tags", settings.ollama_timeout_seconds),
    }
    if settings.vector_backend.lower() == "qdrant":
        components["qdrant"] = _probe_http(f"{settings.qdrant_url}/collections", settings.ollama_timeout_seconds)
    else:
        components["qdrant"] = {"status": "skipped", "reason": "Vector backend is not qdrant"}

    if str(getattr(settings, "exact_cache_backend", "memory")).strip().lower() == "redis":
        redis_health_url = str(getattr(settings, "redis_url", "")).strip()
        if redis_health_url.startswith("redis://"):
            components["redis"] = {"status": "configured", "url": redis_health_url}
        else:
            components["redis"] = {"status": "down", "reason": "Invalid redis_url"}

    overall = "ready"
    for name, component in components.items():
        if name == "api":
            continue
        if component.get("status") not in {"up", "skipped"}:
            overall = "degraded"
            break

    return {
        "status": overall,
        "vector_backend": settings.vector_backend,
        "source_dir": source_dir,
        "components": components,
    }


def get_liveness() -> dict[str, str]:
    return {"status": "ok"}
