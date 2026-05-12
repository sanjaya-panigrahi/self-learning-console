"""Local index loading utilities."""

import json
import logging
from pathlib import Path

from app.core.config.settings import get_settings


logger = logging.getLogger(__name__)


def load_local_index() -> list[dict[str, str | list[float]]]:
    """Load the local JSON index from disk.

    Returns:
        List of index items with source, chunk_id, text, embedding fields.
        Returns empty list if the index doesn't exist yet.
    """
    settings = get_settings()
    index_path = Path(settings.local_index_path)
    if not index_path.exists():
        return []

    try:
        with index_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("Failed to read local index '%s': %s", index_path, exc)
        return []

    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    return items
