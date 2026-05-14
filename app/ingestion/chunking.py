"""Text chunking and splitting logic."""

from typing import Any


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks of specified size.

    Args:
        text: Source text to chunk
        size: Target chunk size in characters
        overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if size <= 0:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max(size - overlap, 1)
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def chunk_text_with_metadata(
    text: str, 
    size: int, 
    overlap: int,
    pages_with_text: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Split text into overlapping chunks while preserving page information.

    Args:
        text: Source text to chunk
        size: Target chunk size in characters
        overlap: Number of characters to overlap between chunks
        pages_with_text: List of dicts with 'page' and 'text' keys mapping pages to their text

    Returns:
        List of chunk dicts with 'text', 'page', and 'char_position' fields
    """
    if size <= 0:
        # If pages_with_text is provided, extract page from first entry
        page_num = None
        if pages_with_text and len(pages_with_text) > 0:
            page_num = pages_with_text[0].get("page")
        return [{
            "text": text,
            "page": page_num,
            "char_position": 0
        }]

    # Build a mapping of character position to page number
    char_to_page: dict[int, int] = {}
    current_pos = 0
    if pages_with_text:
        for page_info in pages_with_text:
            page_num = page_info.get("page")
            page_text = page_info.get("text", "")
            # Account for newline separator added between pages
            for i in range(len(page_text)):
                char_to_page[current_pos + i] = page_num
            current_pos += len(page_text) + 1  # +1 for newline separator

    chunks: list[dict[str, Any]] = []
    start = 0
    step = max(size - overlap, 1)
    while start < len(text):
        end = min(start + size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            # Determine which page this chunk belongs to
            # Use the page of the first character in the chunk
            page_num = char_to_page.get(start)
            if page_num is None and pages_with_text and len(pages_with_text) > 0:
                page_num = pages_with_text[0].get("page")
            
            chunks.append({
                "text": chunk_text,
                "page": page_num,
                "char_position": start
            })
        start += step
    return chunks
