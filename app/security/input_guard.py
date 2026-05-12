"""Input guard checks for incoming API payloads."""

from typing import Any


def guard_chat_request(query: str) -> dict[str, Any]:
    """Validate and sanitize chat input query.

    Returns:
        Dict with keys:
          - ok: bool
          - reason: str
          - query: str (sanitized)
    """
    cleaned = " ".join((query or "").split()).strip()
    if not cleaned:
        return {"ok": False, "reason": "empty_query", "query": ""}
    if len(cleaned) > 4000:
        return {"ok": False, "reason": "query_too_long", "query": cleaned[:4000]}

    blocked_patterns = ("ignore previous instructions", "reveal system prompt")
    lowered = cleaned.lower()
    if any(pat in lowered for pat in blocked_patterns):
        return {"ok": False, "reason": "prompt_injection_pattern", "query": cleaned}

    return {"ok": True, "reason": "ok", "query": cleaned}
