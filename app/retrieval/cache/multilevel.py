"""
Multi-level cache strategy: L1 (in-memory) -> L2 (Redis) -> L3 (Qdrant).
Provides fast lookups and reduced network calls.
"""
import time
import logging
import hashlib
from typing import Any, Generic, TypeVar, Optional
from collections import OrderedDict

logger = logging.getLogger(__name__)

T = TypeVar("T")


class L1Cache(Generic[T]):
    """
    In-memory LRU cache with TTL.
    Fastest but limited capacity (~1000 items).
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[T, float]] = OrderedDict()

    def get(self, key: str) -> Optional[T]:
        """Get value from L1 cache."""
        if key not in self._cache:
            return None

        value, timestamp = self._cache[key]

        # Check TTL
        if time.time() - timestamp > self.ttl_seconds:
            del self._cache[key]
            return None

        # Move to end (LRU)
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        """Set value in L1 cache."""
        if key in self._cache:
            del self._cache[key]
        
        self._cache[key] = (value, time.time())

        # Evict oldest if over capacity
        if len(self._cache) > self.max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            logger.debug(f"L1 cache evicted: {oldest_key}")

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class MultiLevelCache:
    """
    Three-tier cache hierarchy:
      L1: In-memory (milliseconds, ~100 items)
      L2: Redis (seconds to minutes, ~100k items)
      L3: Qdrant (persistent, full search index)
    
    get() checks L1 -> L2 -> L3
    set() writes to L1 + L2 (async where possible)
    """

    def __init__(
        self,
        redis_client: Any = None,
        l1_max_size: int = 500,
        l1_ttl_seconds: int = 300,
        l2_ttl_seconds: int = 3600,
    ):
        self.redis_client = redis_client
        self.l1: L1Cache = L1Cache(max_size=l1_max_size, ttl_seconds=l1_ttl_seconds)
        self.l2_ttl_seconds = l2_ttl_seconds

    @staticmethod
    def _make_key(prefix: str, query: str) -> str:
        """Create cache key from prefix + query hash."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        return f"{prefix}:{query_hash}"

    def get(self, prefix: str, query: str) -> Optional[dict[str, Any]]:
        """
        Attempt to get value from cache hierarchy.
        Returns: (value, tier) or (None, None)
        """
        key = self._make_key(prefix, query)

        # L1: In-memory
        l1_value = self.l1.get(key)
        if l1_value is not None:
            logger.debug(f"Cache L1 hit: {key}")
            return ("L1", l1_value)

        # L2: Redis
        if self.redis_client:
            try:
                l2_value = self.redis_client.get(key)
                if l2_value is not None:
                    logger.debug(f"Cache L2 hit: {key}")
                    # Populate L1 from L2 hit
                    self.l1.set(key, l2_value)
                    return ("L2", l2_value)
            except Exception as exc:
                logger.debug(f"L2 cache read failed: {exc}")

        # L3: Qdrant (delegated to caller)
        logger.debug(f"Cache miss: {key}")
        return None

    def set(self, prefix: str, query: str, value: dict[str, Any]) -> None:
        """Set value in L1 + L2 caches."""
        key = self._make_key(prefix, query)

        # Always L1
        self.l1.set(key, value)

        # L2: Redis (if available)
        if self.redis_client:
            try:
                self.redis_client.setex(
                    key,
                    self.l2_ttl_seconds,
                    value,
                )
                logger.debug(f"Cache L2 set: {key}")
            except Exception as exc:
                logger.debug(f"L2 cache write failed: {exc}")

    def invalidate(self, prefix: str, query: str) -> None:
        """Invalidate entry across all tiers."""
        key = self._make_key(prefix, query)

        # L1
        if key in self.l1._cache:
            del self.l1._cache[key]

        # L2: Redis
        if self.redis_client:
            try:
                self.redis_client.delete(key)
            except Exception as exc:
                logger.debug(f"L2 cache invalidate failed: {exc}")

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "l1_size": self.l1.size(),
            "l1_max_size": self.l1.max_size,
            "l1_ttl_seconds": self.l1.ttl_seconds,
            "l2_ttl_seconds": self.l2_ttl_seconds,
            "l2_available": self.redis_client is not None,
        }
