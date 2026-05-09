"""Insight subpackage - material analysis and insight generation."""

from app.retrieval.insight.cache import clear_material_insight_cache
from app.retrieval.insight.questions import InsightProgressCallback


def get_material_insight(*args: object, **kwargs: object) -> dict[str, object]:
    from app.retrieval.insights import get_material_insight as get_material_insight_impl

    return get_material_insight_impl(*args, **kwargs)

__all__ = [
    "get_material_insight",
    "clear_material_insight_cache",
    "InsightProgressCallback",
]
