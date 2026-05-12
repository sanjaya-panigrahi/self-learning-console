"""In-memory cache for retrieval search responses with TTL support."""

from collections import OrderedDict
import threading
import time
import json
from typing import Any

from app.core.config.settings import get_settings

try:
    import redis
except Exception:  # pragma: no cover - optional dependency
    redis = None

_RETRIEVAL_SEARCH_CACHE_VERSION = "v1"
_RETRIEVAL_SEARCH_CACHE_LOCK = threading.Lock()
_RETRIEVAL_SEARCH_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_REDIS_CLIENT: Any = None


def cache_key(query: str, domain_context: str | None, top_k: int, orchestrator: str) -> str:
    """Build a versioned cache key for retrieval search responses."""
    clean_query = " ".join((query or "").split()).strip().lower()
    clean_domain_context = " ".join((domain_context or "").split()).strip().lower()
    clean_orchestrator = " ".join((orchestrator or "").split()).strip().lower()
    return f"{_RETRIEVAL_SEARCH_CACHE_VERSION}||{clean_query}||{clean_domain_context}||{int(top_k)}||{clean_orchestrator}"


def _get_redis_client() -> Any:
    global _REDIS_CLIENT
    settings = get_settings()
    if str(getattr(settings, "exact_cache_backend", "memory")).strip().lower() != "redis":
        return None
    if redis is None:
        return None

    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    try:
        _REDIS_CLIENT = redis.Redis.from_url(str(settings.redis_url), decode_responses=True)
        _REDIS_CLIENT.ping()
    except Exception:
        _REDIS_CLIENT = None
    return _REDIS_CLIENT


def _redis_cache_key(key: str) -> str:
    settings = get_settings()
    prefix = str(getattr(settings, "redis_exact_cache_prefix", "retrieval:exact")).strip() or "retrieval:exact"
    return f"{prefix}:{key}"


def clear_retrieval_search_cache() -> None:
    """Evict all entries from the retrieval search cache."""
    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        _RETRIEVAL_SEARCH_CACHE.clear()

    client = _get_redis_client()
    if client is None:
        return

    try:
        pattern = _redis_cache_key("*")
        keys = client.keys(pattern)
        if keys:
            client.delete(*keys)
    except Exception:
        return


def get_cached_retrieval_search(
    query: str,
    domain_context: str | None,
    top_k: int,
    orchestrator: str,
) -> dict[str, Any] | None:
    """Return a cached retrieval response when available and not expired."""
    settings = get_settings()
    if not bool(getattr(settings, "retrieval_search_cache_enabled", True)):
        return None

    multilevel_enabled = bool(getattr(settings, "cache_multilevel_enabled", True))
    ttl = max(
        int(
            getattr(settings, "cache_l1_ttl_seconds", 300)
            if multilevel_enabled
            else getattr(settings, "retrieval_search_cache_ttl_seconds", 300)
        ),
        15,
    )
    key = cache_key(query, domain_context, top_k, orchestrator)
    now = time.time()

    client = _get_redis_client()
    if client is not None:
        try:
            payload_raw = client.get(_redis_cache_key(key))
            if payload_raw:
                payload = json.loads(payload_raw)
                payload["cached"] = True
                payload["cache_age_seconds"] = 0
                return payload
        except Exception:
            pass

    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        cached = _RETRIEVAL_SEARCH_CACHE.get(key)
        if not cached:
            return None

        cached_at = float(cached.get("cached_at", now))
        if now - cached_at > ttl:
            _RETRIEVAL_SEARCH_CACHE.pop(key, None)
            return None

        payload = dict(cached.get("payload", {}))
        _RETRIEVAL_SEARCH_CACHE.move_to_end(key)

    payload["cached"] = True
    payload["cache_age_seconds"] = int(now - cached_at)
    return payload


def set_cached_retrieval_search(
    query: str,
    domain_context: str | None,
    top_k: int,
    orchestrator: str,
    payload: dict[str, Any],
) -> None:
    """Store retrieval response in cache and evict oldest entries when needed."""
    settings = get_settings()
    if not bool(getattr(settings, "retrieval_search_cache_enabled", True)):
        return

    multilevel_enabled = bool(getattr(settings, "cache_multilevel_enabled", True))
    max_entries = max(
        int(
            getattr(settings, "cache_l1_max_size", 500)
            if multilevel_enabled
            else getattr(settings, "retrieval_search_cache_max_entries", 200)
        ),
        20,
    )
    key = cache_key(query, domain_context, top_k, orchestrator)

    client = _get_redis_client()
    if client is not None:
        ttl = max(
            int(
                getattr(settings, "cache_l2_ttl_seconds", 3600)
                if multilevel_enabled
                else getattr(settings, "redis_exact_cache_ttl_seconds", 300)
            ),
            15,
        )
        try:
            client.setex(_redis_cache_key(key), ttl, json.dumps(dict(payload)))
        except Exception:
            pass

    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        _RETRIEVAL_SEARCH_CACHE.pop(key, None)
        _RETRIEVAL_SEARCH_CACHE[key] = {
            "cached_at": time.time(),
            "payload": dict(payload),
        }

        overflow = len(_RETRIEVAL_SEARCH_CACHE) - max_entries
        if overflow <= 0:
            return

        for _ in range(overflow):
            _RETRIEVAL_SEARCH_CACHE.popitem(last=False)


def get_retrieval_cache_stats() -> dict[str, Any]:
    """Return lightweight cache stats for observability endpoints."""
    settings = get_settings()
    with _RETRIEVAL_SEARCH_CACHE_LOCK:
        in_memory_entries = len(_RETRIEVAL_SEARCH_CACHE)

    multilevel_enabled = bool(getattr(settings, "cache_multilevel_enabled", True))
    return {
        "cache_enabled": bool(getattr(settings, "retrieval_search_cache_enabled", True)),
        "cache_backend": str(getattr(settings, "exact_cache_backend", "memory")),
        "multilevel_enabled": multilevel_enabled,
        "l1_ttl_seconds": int(getattr(settings, "cache_l1_ttl_seconds", 300)),
        "l2_ttl_seconds": int(getattr(settings, "cache_l2_ttl_seconds", 3600)),
        "max_entries": int(
            getattr(settings, "cache_l1_max_size", 500)
            if multilevel_enabled
            else getattr(settings, "retrieval_search_cache_max_entries", 200)
        ),
        "in_memory_entries": in_memory_entries,
    }
