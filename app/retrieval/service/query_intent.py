import re

from app.core.config.settings import get_settings


def is_acronym_expansion_intent(query: str) -> bool:
    query_lower = query.lower()
    return any(
        phrase in query_lower
        for phrase in (" mean", " means", "full form", "stands for", "expand ", "expansion")
    )


def extract_acronym_candidates(query: str) -> list[str]:
    stopwords = {
        "what",
        "which",
        "when",
        "where",
        "who",
        "why",
        "how",
        "does",
        "do",
        "is",
        "are",
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "mean",
        "means",
        "full",
        "form",
        "stands",
        "expand",
        "expansion",
        "of",
    }

    raw_terms = re.findall(r"\b([A-Za-z]{2,8})\b", query)
    candidates: list[str] = []
    for term in raw_terms:
        lowered = term.lower()
        if lowered in stopwords:
            continue
        if 2 <= len(term) <= 6:
            candidate = term.upper()
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def is_entity_style_query(query: str) -> bool:
    terms = query.split()
    if not terms:
        return False
    settings = get_settings()
    entity_max_terms = int(getattr(settings, "retrieval_entity_max_terms", 5))
    entity_definition_max_terms = int(getattr(settings, "retrieval_entity_definition_max_terms", 10))
    acronym_min_len = int(getattr(settings, "retrieval_lexical_acronym_min_len", 2))
    acronym_max_len = int(getattr(settings, "retrieval_lexical_acronym_max_len", 6))
    query_lower = query.lower()

    if is_acronym_expansion_intent(query_lower) and extract_acronym_candidates(query):
        return True

    if query_lower.startswith(("what is ", "what are ", "who is ", "define ", "explain ")):
        has_version_marker = bool(re.search(r"\bv\d+(?:\.\d+)?\b", query_lower))
        has_context_phrase = " in " in query_lower
        if has_version_marker or has_context_phrase or len(terms) <= entity_definition_max_terms:
            return True

    if len(terms) > entity_max_terms:
        return False
    has_acronym = any(term.isupper() and acronym_min_len <= len(term) <= acronym_max_len for term in terms)
    return has_acronym


def normalize_training_question_query(query: str) -> str:
    cleaned = " ".join(query.split()).strip().rstrip("?")
    if not cleaned:
        return query

    patterns: list[tuple[str, str]] = [
        (
            r"^which business need does (?P<topic>.+?) support in (?P<context>.+)$",
            "{topic} {context} purpose",
        ),
        (
            r"^what pre-checks and post-save checks are required when updating (?P<topic>.+?) in (?P<context>.+)$",
            "{topic} {context} pre-checks post-save checks",
        ),
        (
            r"^how should teams validate changes in (?P<topic>.+?) before saving in (?P<context>.+)$",
            "{topic} {context} validation before saving",
        ),
    ]

    normalized = cleaned.lower()
    for pattern, template in patterns:
        match = re.match(pattern, normalized)
        if not match:
            continue
        topic = match.group("topic").strip()
        context = match.group("context").strip()
        rewritten = template.format(topic=topic, context=context)
        return " ".join(rewritten.split())

    return query


def query_variants(base_query: str, retrieval_query: str) -> list[str]:
    variants: list[str] = [base_query]
    if retrieval_query.strip() and retrieval_query.strip().lower() != base_query.strip().lower():
        variants.append(retrieval_query)

    if is_entity_style_query(base_query):
        normalized_base_query = " ".join(base_query.lower().split())
        if not normalized_base_query.startswith(("what is ", "what are ", "who is ", "define ", "explain ")):
            variants.append(f"what is {base_query}")

    acronym_candidates = extract_acronym_candidates(base_query)
    for acronym in acronym_candidates[:2]:
        variants.append(acronym)
        variants.append(f"{acronym} full form")
        variants.append(f"{acronym} stands for")

    unique: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        cleaned = " ".join(variant.split()).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


__all__ = [
    "extract_acronym_candidates",
    "is_acronym_expansion_intent",
    "is_entity_style_query",
    "normalize_training_question_query",
    "query_variants",
]
