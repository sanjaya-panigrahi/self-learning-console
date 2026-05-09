"""Text chunking and splitting logic."""


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
