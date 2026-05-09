import re
from typing import Any

from app.feedback.collector.service import get_source_feedback_penalties


def _is_low_signal_query(query: str) -> bool:
    terms = [term for term in search_tokens(query) if term]
    unique_terms = list(dict.fromkeys(terms))
    if not unique_terms:
        return True
    if len(unique_terms) == 1 and len(unique_terms[0]) <= 5:
        return True
    if len(unique_terms) <= 2 and all(len(term) <= 4 for term in unique_terms):
        return True
    return False


def trim_excerpt(text: str, limit: int = 260) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def search_tokens(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return [token for token in cleaned.split() if token]


def keyword_relevance_score(query: str, source: str, text: str) -> float:
    query_clean = " ".join(query.split()).strip()
    if not query_clean:
        return 0.0

    query_lower = query_clean.lower()
    combined = f"{source} {text}".lower()
    score = 0.0
    low_signal_query = _is_low_signal_query(query_clean)

    normalized_query = query_lower
    for prefix in ("what is ", "what are ", "who is ", "define ", "explain "):
        if normalized_query.startswith(prefix):
            normalized_query = normalized_query[len(prefix) :].strip()
            break

    if not low_signal_query and query_lower in combined:
        score += 2.0
    if not low_signal_query and normalized_query and normalized_query != query_lower and normalized_query in combined:
        score += 1.6
    if not low_signal_query and query_lower in source.lower():
        score += 1.0
    if not low_signal_query and normalized_query and normalized_query in source.lower():
        score += 1.4

    has_doc_source_hint = any(keyword in query_lower for keyword in ("guide", "manual", "playbook", "runbook", "handbook"))
    source_hint_stopwords = {
        "what",
        "which",
        "when",
        "where",
        "who",
        "why",
        "how",
        "does",
        "support",
        "need",
        "business",
        "start",
        "end",
        "time",
        "multiple",
        "window",
        "user",
        "guide",
        "manual",
        "the",
        "and",
        "for",
        "with",
        "in",
    }
    source_hint_terms = [
        token
        for token in search_tokens(query_clean)
        if len(token) >= 3 and token not in source_hint_stopwords
    ]
    focus_term_stopwords = source_hint_stopwords | {
        "filter",
        "sort",
        "data",
        "screen",
        "page",
        "view",
        "interface",
        "within",
        "using",
        "content",
        "list",
        "results",
    }
    focus_terms = [
        token
        for token in search_tokens(query_clean)
        if len(token) >= 3 and token not in focus_term_stopwords
    ]
    source_lower = source.lower()
    source_hint_matches = sum(
        1 for token in dict.fromkeys(source_hint_terms) if re.search(rf"\b{re.escape(token)}\b", source_lower)
    )
    if has_doc_source_hint and source_hint_matches > 0:
        score += 0.9 * source_hint_matches

    unique_focus_terms = list(dict.fromkeys(focus_terms))
    focus_matches = sum(1 for token in unique_focus_terms if re.search(rf"\b{re.escape(token)}\b", combined))
    if unique_focus_terms:
        score += min(focus_matches, 3) * 0.45
        if len(unique_focus_terms) >= 2 and focus_matches == 0:
            score -= 0.9

    version_match = re.search(r"v\d+\.\d+", query_lower)
    if version_match:
        version = version_match.group()
        if version in source.lower():
            score += 1.8

    terms = [term for term in search_tokens(query_clean) if len(term) >= 3]
    unique_terms = list(dict.fromkeys(terms))
    matched_terms = 0
    for term in unique_terms:
        if re.search(rf"\b{re.escape(term)}\b", combined):
            matched_terms += 1
    if unique_terms:
        base_term_score = (matched_terms / len(unique_terms)) * 1.2
        if has_doc_source_hint:
            base_term_score *= 1.15
        if low_signal_query:
            base_term_score *= 0.45
        score += base_term_score

    acronym_terms = [term for term in query_clean.split() if term.isupper() and 2 <= len(term) <= 4]
    for acronym in acronym_terms:
        if re.search(rf"\b{re.escape(acronym.lower())}\b", combined):
            score += 0.6

    return score


def content_quality_score(text: str) -> float:
    cleaned = " ".join(text.split())
    if not cleaned:
        return -1.0

    total_chars = len(cleaned)
    alpha_chars = sum(1 for char in cleaned if char.isalpha())
    digit_chars = sum(1 for char in cleaned if char.isdigit())
    alpha_ratio = alpha_chars / total_chars
    digit_ratio = digit_chars / total_chars
    dot_run_count = cleaned.count("....")
    punctuation_chars = sum(1 for char in cleaned if char in ".,:;|/-")
    punctuation_ratio = punctuation_chars / total_chars
    uppercase_token_count = sum(1 for token in cleaned.split() if len(token) >= 4 and token.isupper())

    score = 0.0
    score += alpha_ratio * 1.2
    score -= digit_ratio * 0.6
    score -= min(dot_run_count, 12) * 0.08
    score -= min(uppercase_token_count, 20) * 0.01
    score -= punctuation_ratio * 0.35
    return score


def merge_and_rank_contexts(
    query: str,
    original_contexts: list[dict[str, str]],
    rewritten_contexts: list[dict[str, str]],
    top_k: int,
) -> list[dict[str, str]]:
    low_signal_query = _is_low_signal_query(query)
    scored: dict[tuple[str, str], dict[str, Any]] = {}
    source_penalties = get_source_feedback_penalties()

    for index, context in enumerate(original_contexts):
        key = (str(context.get("source", "")), str(context.get("chunk_id", "")))
        if key not in scored:
            scored[key] = {"context": context, "score": 0.0}
        scored[key]["score"] += 1.0 / (index + 1)

    for index, context in enumerate(rewritten_contexts):
        key = (str(context.get("source", "")), str(context.get("chunk_id", "")))
        if key not in scored:
            scored[key] = {"context": context, "score": 0.0}
        scored[key]["score"] += 0.7 / (index + 1)

    for entry in scored.values():
        context = entry["context"]
        source = str(context.get("source", "")).strip().lower()
        keyword_score = keyword_relevance_score(
            query=query,
            source=str(context.get("source", "")),
            text=str(context.get("text", "")),
        )
        quality_score = content_quality_score(str(context.get("text", "")))
        feedback_penalty = float(source_penalties.get(source, 0.0) or 0.0)
        entry["keyword_score"] = keyword_score
        entry["quality_score"] = quality_score
        entry["feedback_penalty"] = feedback_penalty
        entry["score"] += keyword_score
        entry["score"] += quality_score
        entry["score"] -= feedback_penalty

    ranked = sorted(scored.values(), key=lambda row: float(row["score"]), reverse=True)
    preferred = [
        entry
        for entry in ranked
        if float(entry.get("keyword_score", 0.0)) >= 0.35
        or (
            float(entry.get("quality_score", 0.0)) >= 0.22
            and float(entry.get("keyword_score", 0.0)) >= 0.18
        )
    ]

    if low_signal_query:
        preferred = [
            entry
            for entry in preferred
            if float(entry.get("keyword_score", 0.0)) >= 0.9 and float(entry.get("quality_score", 0.0)) >= 0.2
        ]

    selected = preferred[:top_k]
    if len(selected) < top_k and not low_signal_query:
        selected_keys = {
            (
                str(item["context"].get("source", "")),
                str(item["context"].get("chunk_id", "")),
            )
            for item in selected
        }
        for candidate in ranked:
            key = (
                str(candidate["context"].get("source", "")),
                str(candidate["context"].get("chunk_id", "")),
            )
            if key in selected_keys:
                continue
            if float(candidate.get("keyword_score", 0.0)) < 0.18:
                continue
            selected.append(candidate)
            selected_keys.add(key)
            if len(selected) >= top_k:
                break

    return [entry["context"] for entry in selected[:top_k]]


__all__ = [
    "content_quality_score",
    "keyword_relevance_score",
    "merge_and_rank_contexts",
    "search_tokens",
    "trim_excerpt",
]
