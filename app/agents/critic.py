"""Critic agent for selecting final retrieval answer payload."""

from typing import Any


def select_final_answer_payload(
    llm_payload: dict[str, Any],
    retrieval_payload: dict[str, Any],
    llm_answer_insufficient: bool,
) -> tuple[dict[str, Any], str]:
    """Select payload and fallback reason while keeping current retrieval semantics."""
    llm_available = llm_payload.get("answer_path") == "llm"
    if not llm_available:
        return retrieval_payload, "llm_unavailable"
    if llm_answer_insufficient:
        return retrieval_payload, "llm_low_detail"
    return llm_payload, ""
