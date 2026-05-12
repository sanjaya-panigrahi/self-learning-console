"""Content guard checks for optional domain context and intermediate text."""

from typing import Any


def guard_domain_context(domain_context: str | None) -> dict[str, Any]:
    """Validate and sanitize optional domain context."""
    cleaned = " ".join((domain_context or "").split()).strip()
    if not cleaned:
        return {"ok": True, "reason": "none", "domain_context": None}
    if len(cleaned) > 3000:
        cleaned = cleaned[:3000]

    blocked_terms = ("api key", "secret token", "private key")
    lowered = cleaned.lower()
    if any(term in lowered for term in blocked_terms):
        return {"ok": False, "reason": "sensitive_context", "domain_context": None}

    return {"ok": True, "reason": "ok", "domain_context": cleaned}
