"""Lexical (keyword-based) search for retrieval pipeline."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config.settings import get_settings

if TYPE_CHECKING:
    pass


_LEXICAL_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "for",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "who",
}


def sanitize_source_label(source: str) -> str:
    """Trim source to just the filename component.

    Args:
        source: Full or relative path to source file

    Returns:
        Just the filename part
    """
    source_path = Path(source)
    if len(source_path.parts) > 1:
        return source_path.name
    return source


def tokenize(text: str) -> set[str]:
    """Tokenize text to lowercase alphanumeric tokens.

    Args:
        text: Text to tokenize

    Returns:
        Set of lowercase tokens
    """
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return {token for token in cleaned.split() if token}


def is_lexical_first_query(query: str) -> bool:
    """Determine if a query should use lexical (keyword-based) search first.

    Lexical search is better for:
    - Product/version-specific queries (TA Manager v1.9)
    - Named configuration modules (Countries, Port Area Codes, Policy)
    - Acronym-heavy technical queries
    - Queries requiring exact term matching over semantic similarity

    Args:
        query: User query string

    Returns:
        True if lexical search should be tried first
    """
    terms = [term for term in query.split() if term.strip()]
    if not terms:
        return False
    settings = get_settings()
    acronym_min_len = int(getattr(settings, "retrieval_lexical_acronym_min_len", 2))
    acronym_max_len = int(getattr(settings, "retrieval_lexical_acronym_max_len", 6))
    short_query_max_terms = int(getattr(settings, "retrieval_lexical_short_query_max_terms", 4))
    short_phrase_max_terms = int(getattr(settings, "retrieval_lexical_short_phrase_max_terms", 3))

    # Single acronym query
    if len(terms) == 1 and terms[0].isupper() and acronym_min_len <= len(terms[0]) <= acronym_max_len:
        return True

    # Multiple acronyms or acronym in short query
    if len(terms) <= short_query_max_terms and any(term.isupper() and acronym_min_len <= len(term) <= acronym_max_len for term in terms):
        return True

    query_lower = query.lower()
    has_version_marker = bool(re.search(r"\bv\d+(?:\.\d+)?\b", query_lower))
    has_definition_intent = query_lower.startswith(("what is ", "what are ", "who is ", "define ", "explain "))

    # Version-specific lookup questions are usually best served by exact lexical matches.
    if has_version_marker and has_definition_intent:
        return True

    # Short noun phrases (e.g., "Countries", "Payment Rules") are often entity/module lookups.
    if len(terms) <= short_phrase_max_terms and all(any(ch.isalpha() for ch in term) for term in terms):
        return True

    # Definitional queries referencing a system context ("X in Y") should prefer lexical first.
    if has_definition_intent and " in " in query_lower:
        return True

    return False


def lexical_context_search(
    query: str,
    items: list[dict[str, str | list[float]]],
    k: int,
) -> list[dict[str, str]]:
    """Score and rank items against a query using term-overlap lexical scoring.

    Combines phrase hits, exact token hits, source token hits, and overlap
    to produce a ranked list of top-k matching chunks.

    Args:
        query: User query string
        items: Index items with source, chunk_id, text, embedding fields
        k: Maximum number of results to return

    Returns:
        Top-k retrieved contexts (source, chunk_id, text)
    """
    query_terms = {token for token in tokenize(query) if token not in _LEXICAL_STOPWORDS and len(token) >= 3}
    if not query_terms:
        query_terms = {token for token in tokenize(query) if len(token) >= 2}

    ordered_terms = [token for token in tokenize(query) if token not in _LEXICAL_STOPWORDS and len(token) >= 3]
    query_phrases: list[str] = []
    for size in (2, 3):
        if len(ordered_terms) < size:
            continue
        for i in range(len(ordered_terms) - size + 1):
            phrase = " ".join(ordered_terms[i : i + size])
            if phrase not in query_phrases:
                query_phrases.append(phrase)

    scored_lexical: list[tuple[float, dict[str, str | list[float]]]] = []
    for item in items:
        source = str(item.get("source", ""))
        item_text = str(item.get("text", ""))
        item_terms = tokenize(item_text)
        if not item_terms:
            continue
        overlap_terms = query_terms.intersection(item_terms)
        exact_token_hits = sum(item_text.lower().count(term) for term in query_terms)
        source_token_hits = sum(source.lower().count(term) for term in query_terms)
        phrase_hits = sum(item_text.lower().count(phrase) for phrase in query_phrases)
        source_phrase_hits = sum(source.lower().count(phrase) for phrase in query_phrases)
        overlap = len(overlap_terms)
        if overlap <= 0 and exact_token_hits <= 0 and source_token_hits <= 0 and phrase_hits <= 0 and source_phrase_hits <= 0:
            continue
        score = (
            (phrase_hits * 4.0)
            + (source_phrase_hits * 2.5)
            + (exact_token_hits * 2.5)
            + (source_token_hits * 1.5)
            + (overlap / max(len(item_terms), 1))
        )
        scored_lexical.append((score, item))

    if not scored_lexical:
        return []

    scored_lexical.sort(key=lambda row: row[0], reverse=True)
    top_items = scored_lexical[:k]
    return [
        {
            "source": sanitize_source_label(str(item.get("source", "unknown"))),
            "chunk_id": str(item.get("chunk_id", "chunk-unknown")),
            "text": str(item.get("text", "")),
        }
        for _, item in top_items
        if str(item.get("text", ""))
    ]
