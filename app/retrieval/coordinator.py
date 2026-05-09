import threading

from app.core.config.settings import get_settings
from app.retrieval.insights import get_material_insight
from app.retrieval.service import get_retrieval_overview


def prewarm_material_insights() -> None:
    settings = get_settings()
    top_n = max(int(getattr(settings, "material_insight_background_top_n", 3)), 0)
    if top_n <= 0:
        return

    def _worker() -> None:
        overview = get_retrieval_overview()
        materials = [item for item in overview.get("materials", []) if str(item.get("status")) == "indexed"]
        for item in materials[:top_n]:
            source = str(item.get("source", "")).strip()
            if not source:
                continue
            get_material_insight(source=source, domain_context=None, use_cache=True)

    threading.Thread(target=_worker, name="insight-prewarm", daemon=True).start()
