"""
Query latency metrics collection and reporting.
Tracks timing for each stage: retrieve, generate, rank, etc.
"""
import time
import logging
import uuid
from typing import Callable, TypeVar, Any
from functools import wraps
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class QueryMetrics:
    """Metrics for a single query execution."""
    query_id: str
    query_text: str
    retrieve_ms: float = 0.0
    generate_ms: float = 0.0
    rank_ms: float = 0.0
    cache_hit: bool = False
    cache_tier: str | None = None  # "L1", "L2", "L3", None
    total_ms: float = 0.0
    timestamp: str = ""
    
    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def log(self) -> None:
        """Log metrics as structured JSON."""
        logger.info(
            f"Query metrics: {self.query_id}",
            extra={
                "query_id": self.query_id,
                "duration_ms": int(self.total_ms),
                "cache_hit": self.cache_hit,
                "cache_tier": self.cache_tier,
                "service": "retrieval",
            }
        )


class MetricsCollector:
    """Thread-local metrics collector for query tracking."""

    _instance_data: dict[str, QueryMetrics] = {}
    _history: list[QueryMetrics] = []
    _history_max: int = 300

    @classmethod
    def create_query(cls, query_text: str) -> str:
        """Create a new query and return its ID."""
        query_id = str(uuid.uuid4())[:8]
        cls._instance_data[query_id] = QueryMetrics(
            query_id=query_id,
            query_text=query_text,
        )
        return query_id

    @classmethod
    def get(cls, query_id: str) -> QueryMetrics | None:
        """Get metrics for a query."""
        return cls._instance_data.get(query_id)

    @classmethod
    def record_retrieve(cls, query_id: str, duration_ms: float) -> None:
        """Record retrieval phase duration."""
        if query_id in cls._instance_data:
            cls._instance_data[query_id].retrieve_ms = duration_ms

    @classmethod
    def record_generate(cls, query_id: str, duration_ms: float) -> None:
        """Record generation phase duration."""
        if query_id in cls._instance_data:
            cls._instance_data[query_id].generate_ms = duration_ms

    @classmethod
    def record_rank(cls, query_id: str, duration_ms: float) -> None:
        """Record ranking phase duration."""
        if query_id in cls._instance_data:
            cls._instance_data[query_id].rank_ms = duration_ms

    @classmethod
    def record_cache_hit(
        cls,
        query_id: str,
        cache_hit: bool,
        cache_tier: str | None = None,
    ) -> None:
        """Record cache hit/miss."""
        if query_id in cls._instance_data:
            cls._instance_data[query_id].cache_hit = cache_hit
            cls._instance_data[query_id].cache_tier = cache_tier

    @classmethod
    def finalize(cls, query_id: str) -> QueryMetrics | None:
        """Finalize metrics and log them."""
        metrics = cls._instance_data.pop(query_id, None)
        if metrics:
            metrics.total_ms = (
                metrics.retrieve_ms + metrics.generate_ms + metrics.rank_ms
            )
            metrics.log()
            cls._history.append(metrics)
            if len(cls._history) > cls._history_max:
                cls._history = cls._history[-cls._history_max :]
        return metrics

    @classmethod
    def snapshot(cls, limit: int = 50) -> dict[str, Any]:
        """Return recent query metrics summary for observability APIs."""
        safe_limit = max(1, min(int(limit), cls._history_max))
        recent = cls._history[-safe_limit:]
        if not recent:
            return {
                "sample_size": 0,
                "avg_total_ms": 0.0,
                "avg_retrieve_ms": 0.0,
                "avg_generate_ms": 0.0,
                "avg_rank_ms": 0.0,
                "cache_hit_rate": 0.0,
                "recent_queries": [],
            }

        sample_size = len(recent)
        avg_total = sum(m.total_ms for m in recent) / sample_size
        avg_retrieve = sum(m.retrieve_ms for m in recent) / sample_size
        avg_generate = sum(m.generate_ms for m in recent) / sample_size
        avg_rank = sum(m.rank_ms for m in recent) / sample_size
        hit_rate = sum(1 for m in recent if m.cache_hit) / sample_size

        return {
            "sample_size": sample_size,
            "avg_total_ms": round(avg_total, 2),
            "avg_retrieve_ms": round(avg_retrieve, 2),
            "avg_generate_ms": round(avg_generate, 2),
            "avg_rank_ms": round(avg_rank, 2),
            "cache_hit_rate": round(hit_rate, 4),
            "recent_queries": [
                {
                    "query_id": m.query_id,
                    "timestamp": m.timestamp,
                    "total_ms": round(m.total_ms, 2),
                    "cache_hit": m.cache_hit,
                    "cache_tier": m.cache_tier,
                }
                for m in recent[-20:]
            ],
        }


def timeit_stage(stage_name: str) -> Callable:
    """
    Decorator to time a function and record it in metrics.
    
    Usage:
        @timeit_stage("retrieve")
        def retrieve_context(query_id, query):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.time() - start) * 1000.0

                # Try to find query_id in args/kwargs
                query_id = kwargs.get("query_id")
                if not query_id:
                    for arg in args:
                        if isinstance(arg, str) and len(arg) == 8:
                            query_id = arg
                            break

                if query_id:
                    if stage_name == "retrieve":
                        MetricsCollector.record_retrieve(query_id, duration_ms)
                    elif stage_name == "generate":
                        MetricsCollector.record_generate(query_id, duration_ms)
                    elif stage_name == "rank":
                        MetricsCollector.record_rank(query_id, duration_ms)

        return wrapper

    return decorator
