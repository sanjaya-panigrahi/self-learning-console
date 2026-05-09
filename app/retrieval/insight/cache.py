"""Memory + disk cache for material insights with TTL support."""

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any

from app.core.config.settings import get_settings

_INSIGHT_CACHE_VERSION = "v8"
_INSIGHT_CACHE_LOCK = threading.Lock()
_INSIGHT_CACHE: dict[str, dict[str, Any]] = {}


def _cache_dir() -> Path:
    settings = get_settings()
    return Path(getattr(settings, "material_insight_cache_dir", "data/indexes/material_insight_cache"))


def _cache_file_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.json"


def _load_disk_entry(key: str) -> dict[str, Any] | None:
    path = _cache_file_path(key)
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _save_disk_entry(key: str, entry: dict[str, Any]) -> None:
    path = _cache_file_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, ensure_ascii=True), encoding="utf-8")
    except OSError:
        # Disk persistence is best-effort; in-memory cache remains authoritative for runtime.
        return


def _delete_disk_entry(key: str) -> None:
    path = _cache_file_path(key)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def cache_key(source: str, domain_context: str | None) -> str:
    """Build a versioned cache key for an insight result.

    Args:
        source: Material source path
        domain_context: Optional domain context string

    Returns:
        Cache key string including version prefix
    """
    return f"{_INSIGHT_CACHE_VERSION}||{source}||{(domain_context or '').strip().lower()}"


def clear_material_insight_cache() -> None:
    """Evict all entries from memory and disk insight cache."""
    with _INSIGHT_CACHE_LOCK:
        _INSIGHT_CACHE.clear()

    cache_dir = _cache_dir()
    if not cache_dir.exists() or not cache_dir.is_dir():
        return
    for path in cache_dir.glob("*.json"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def get_cached_material_insight(source: str, domain_context: str | None) -> dict[str, Any] | None:
    """Retrieve a cached insight result if it exists and has not expired.

    Args:
        source: Material source path
        domain_context: Optional domain context string

    Returns:
        Cached insight dict with `cached=True` metadata, or None if expired/missing
    """
    settings = get_settings()
    ttl = max(int(getattr(settings, "material_insight_cache_ttl_seconds", 3600)), 60)
    key = cache_key(source, domain_context)
    now = time.time()
    with _INSIGHT_CACHE_LOCK:
        cached = _INSIGHT_CACHE.get(key)
        if not cached:
            cached = _load_disk_entry(key)
            if cached is not None:
                _INSIGHT_CACHE[key] = cached
        if not cached:
            return None
        if now - float(cached.get("cached_at", now)) > ttl:
            _INSIGHT_CACHE.pop(key, None)
            _delete_disk_entry(key)
            return None
        payload = dict(cached.get("payload", {}))
    payload["cached"] = True
    payload["cache_age_seconds"] = int(now - float(cached.get("cached_at", now)))
    return payload


def set_cached_material_insight(source: str, domain_context: str | None, payload: dict[str, Any]) -> None:
    """Store an insight result in the cache.

    Args:
        source: Material source path
        domain_context: Optional domain context string
        payload: Insight result to cache
    """
    key = cache_key(source, domain_context)
    entry = {
        "cached_at": time.time(),
        "payload": dict(payload),
    }
    with _INSIGHT_CACHE_LOCK:
        _INSIGHT_CACHE[key] = entry
    _save_disk_entry(key, entry)
