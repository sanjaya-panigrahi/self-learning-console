"""Index loading and chunk preparation for material insights."""

import json
import re
from pathlib import Path
from typing import Any

from app.core.config.settings import get_settings


def load_local_index_items() -> list[dict[str, Any]]:
    """Load items from the local ingestion index.

    Returns:
        List of index items with source, text, embedding fields
    """
    settings = get_settings()
    index_path = Path(settings.local_index_path)
    if not index_path.exists():
        return []

    with index_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return payload.get("items", [])


def trim_excerpt(text: str, limit: int = 260) -> str:
    """Trim text to a clean excerpt within the character limit.

    Args:
        text: Text to trim
        limit: Maximum character limit

    Returns:
        Trimmed text with ellipsis if truncated
    """
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def is_boilerplate_text(text: str) -> bool:
    """Detect boilerplate/front-matter content not useful for insights.

    Identifies:
    - Legal disclaimers and copyright notices
    - Table of contents sections
    - Version history headers
    - Numbered heading lists (TOC-like)

    Args:
        text: Text to inspect

    Returns:
        True if the text looks like boilerplate
    """
    cleaned = " ".join(text.split()).lower()
    if not cleaned:
        return True

    boilerplate_markers = (
        "confidential and proprietary information",
        "all rights reserved",
        "table of contents",
        "document review",
        "accessibility compliance updates",
        "wcag 2.2 compliance updates",
        "initial draft version",
        "date version comments user",
        "this documentation is the confidential",
    )
    if any(marker in cleaned for marker in boilerplate_markers):
        return True

    if len(re.findall(r"\.{8,}", cleaned)) >= 2:
        return True

    sentences = [segment.strip() for segment in re.split(r"[.;]", cleaned) if segment.strip()]
    numbered_headings = sum(
        1
        for sentence in sentences
        if re.match(r"^\d{1,2}\s+\S+", sentence) and len(sentence.split()) <= 6
    )
    if len(sentences) >= 4 and numbered_headings >= 3:
        return True

    return False


def prepare_chunks_for_insight(chunks: list[str]) -> list[str]:
    """Clean and filter chunks for use in insight generation.

    Normalizes whitespace and removes boilerplate. Falls back to
    basic normalization if all chunks are boilerplate.

    Args:
        chunks: Raw text chunks from the index

    Returns:
        Filtered and normalized chunks
    """
    cleaned_chunks: list[str] = []
    for chunk in chunks:
        normalized = " ".join(str(chunk).split())
        if not normalized:
            continue
        if is_boilerplate_text(normalized):
            continue
        cleaned_chunks.append(normalized)

    return cleaned_chunks or [" ".join(str(chunk).split()) for chunk in chunks if str(chunk).strip()]


def get_material_chunks(source: str, limit: int = 10) -> list[str]:
    """Fetch and prepare chunks for a specific source from the local index.

    Args:
        source: Source file path to filter by
        limit: Maximum number of chunks to return

    Returns:
        Prepared chunks for the specified source
    """
    items = load_local_index_items()
    chunks = [str(item.get("text", "")) for item in items if str(item.get("source", "")) == source]
    prepared_chunks = prepare_chunks_for_insight(chunks)
    return [chunk for chunk in prepared_chunks[:limit] if chunk.strip()]
