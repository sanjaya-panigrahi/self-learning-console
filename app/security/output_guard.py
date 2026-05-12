"""Output guard checks for generated responses."""

from typing import Any


def guard_chat_response(answer: str) -> dict[str, Any]:
    """Guard outgoing answer text against sensitive leakage patterns."""
    text = (answer or "").strip()
    if not text:
        return {"ok": True, "reason": "empty", "answer": ""}

    sensitive_markers = ("sk-", "lsv2_", "BEGIN PRIVATE KEY")
    if any(marker in text for marker in sensitive_markers):
        return {
            "ok": False,
            "reason": "sensitive_output_detected",
            "answer": "Response blocked by output guard due to sensitive content policy.",
        }

    if len(text) > 12000:
        text = text[:12000]
    return {"ok": True, "reason": "ok", "answer": text}
