import re

from app.retrieval.index import load_local_index
from app.retrieval.service.scoring import search_tokens


def pick_preferred_entity_sentence(query: str, sentences: list[str]) -> str | None:
    query_lower = query.lower()
    query_terms = [
        token
        for token in search_tokens(query)
        if len(token) >= 3 and token not in {"what", "which", "when", "where", "who", "why", "how", "does", "the", "and", "for", "with", "from", "this", "that"}
    ]
    query_phrases: list[str] = []
    for size in (2, 3):
        if len(query_terms) < size:
            continue
        for idx in range(len(query_terms) - size + 1):
            phrase = " ".join(query_terms[idx : idx + size])
            if phrase not in query_phrases:
                query_phrases.append(phrase)

    preferred: list[tuple[int, str]] = []
    for sentence in sentences:
        lower = sentence.lower()
        score = 0
        if query_lower in lower:
            score += 6

        token_matches = sum(1 for token in query_terms if re.search(rf"\b{re.escape(token)}\b", lower))
        phrase_matches = sum(1 for phrase in query_phrases if phrase in lower)
        score += token_matches * 2
        score += phrase_matches * 3

        if "includes the" in lower or "refers to" in lower or "used to" in lower:
            score += 1
        if lower.startswith(("figure ", "table ")):
            score -= 3
        preferred.append((score, sentence))

    if not preferred:
        return None

    preferred.sort(key=lambda item: item[0], reverse=True)
    best_score, best_sentence = preferred[0]
    if best_score <= 0:
        return None
    return best_sentence


def looks_like_acronym_expansion(acronym: str, phrase: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z]+", phrase) if w]
    if len(words) < 2 or len(words) > 8:
        return False
    initials = "".join(word[0].lower() for word in words)
    ac = acronym.lower()
    return initials == ac or initials.startswith(ac)


def extract_acronym_expansion(acronym: str, texts: list[str]) -> str | None:
    ac = re.escape(acronym)
    patterns = [
        rf"\b{ac}\b\s*\(([^)]+)\)",
        rf"\b{ac}\b\s*(?:-|:|=|means|refers to|stands for|is)\s*([A-Za-z][A-Za-z\s\-/&]+)",
        rf"([A-Za-z][A-Za-z\s\-/&]+)\s*\(\s*\b{ac}\b\s*\)",
    ]

    for raw in texts:
        cleaned_text = " ".join(raw.split())
        for pattern in patterns:
            for match in re.finditer(pattern, cleaned_text, flags=re.IGNORECASE):
                candidate = " ".join((match.group(1) or "").split()).strip(" -:;,.")
                if len(candidate) < 6:
                    continue
                candidate = candidate[:90].strip(" -:;,.")
                if looks_like_acronym_expansion(acronym, candidate):
                    return f"{acronym.upper()} means {candidate}."
    return None


def is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(char in it for char in needle)


def infer_acronym_expansion_from_texts(acronym: str, texts: list[str]) -> str | None:
    ac = acronym.lower()
    if len(ac) < 2:
        return None

    best_phrase: str | None = None
    best_score = 0
    best_frequency = 0
    weak_terms = {
        "id",
        "ids",
        "code",
        "status",
        "reason",
        "options",
        "option",
        "event",
        "events",
        "service",
        "services",
        "type",
        "types",
    }
    phrase_hits: dict[str, int] = {}

    for raw in texts:
        cleaned = " ".join(raw.split())
        if not cleaned:
            continue

        tokens = [token.lower() for token in re.findall(r"[A-Za-z]+", cleaned)]
        if len(tokens) < 2:
            continue

        for size in (2, 3, 4):
            if len(tokens) < size:
                continue
            for idx in range(len(tokens) - size + 1):
                words = tokens[idx : idx + size]
                if any(len(word) < 3 for word in words):
                    continue
                if any(ac in word for word in words):
                    continue
                if any(word in weak_terms for word in words):
                    continue

                initials = "".join(word[0] for word in words)
                two_by_two = "".join(word[:2] for word in words[:2]) if len(words) >= 2 else ""

                score = 0
                if initials == ac:
                    score = 5
                elif len(ac) == 4 and len(words) == 2 and two_by_two == ac and all(len(word) >= 4 for word in words):
                    score = 4
                elif initials.startswith(ac):
                    score = 3

                phrase = " ".join(word.capitalize() for word in words)
                if len(phrase) < 6 or len(phrase) > 60:
                    continue

                phrase_hits[phrase] = phrase_hits.get(phrase, 0) + 1
                frequency = phrase_hits[phrase]

                if score > best_score or (score == best_score and frequency > best_frequency):
                    best_score = score
                    best_phrase = phrase
                    best_frequency = frequency

    if best_phrase and best_score >= 3:
        if best_score == 3 and best_frequency < 2:
            return None
        return f"{acronym.upper()} means {best_phrase}."

    return None


def find_acronym_expansion_in_index(acronym: str, max_items: int = 220) -> tuple[str | None, list[str]]:
    items = load_local_index()
    if not items:
        return None, []

    acronym_pattern = re.compile(rf"\b{re.escape(acronym)}\b", flags=re.IGNORECASE)
    texts: list[str] = []
    sources: list[str] = []
    source_set: set[str] = set()
    for item in items:
        text = str(item.get("text", ""))
        if not text or not acronym_pattern.search(text):
            continue
        texts.append(text)
        source = str(item.get("source", "")).strip()
        if source and source not in sources:
            sources.append(source)
            source_set.add(source)
        if len(texts) >= max_items:
            break

    if not texts and not sources:
        return None, []

    source_context_texts: list[str] = []
    if source_set:
        for item in items:
            source = str(item.get("source", "")).strip()
            if source not in source_set:
                continue
            text = str(item.get("text", ""))
            if text:
                source_context_texts.append(text)
            if len(source_context_texts) >= max_items:
                break

    candidate_texts = texts + source_context_texts
    if not candidate_texts:
        return None, []

    expansion = extract_acronym_expansion(acronym, candidate_texts)
    if not expansion:
        expansion = infer_acronym_expansion_from_texts(acronym, source_context_texts)
    return expansion, sources[:3]


DOMAIN_ACRONYM_SEEDS: dict[str, str] = {
    "ETA": "Estimated Time of Arrival",
    "ETD": "Estimated Time of Departure",
    "SLA": "Service Level Agreement",
    "API": "Application Programming Interface",
    "UI": "User Interface",
    "UX": "User Experience",
    "SSO": "Single Sign-On",
    "MFA": "Multi-Factor Authentication",
    "OTP": "One-Time Password",
    "JWT": "JSON Web Token",
    "REST": "Representational State Transfer",
    "SPA": "Single Page Application",
    "CSV": "Comma-Separated Values",
    "PDF": "Portable Document Format",
}


def domain_seed_expansion(acronym: str) -> str | None:
    return DOMAIN_ACRONYM_SEEDS.get(acronym.upper())


__all__ = [
    "domain_seed_expansion",
    "extract_acronym_expansion",
    "find_acronym_expansion_in_index",
    "infer_acronym_expansion_from_texts",
    "is_subsequence",
    "looks_like_acronym_expansion",
    "pick_preferred_entity_sentence",
]
