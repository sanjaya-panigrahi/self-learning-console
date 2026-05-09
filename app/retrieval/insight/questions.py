"""Question filtering, relevance checking, and progressive question building for material insights."""

import re
from collections.abc import Callable
from typing import Any

InsightProgressCallback = Callable[[str, dict[str, Any] | None], None]


def emit_progress(callback: InsightProgressCallback | None, event: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a progress event to the callback if one is registered.

    Args:
        callback: Optional progress callback
        event: Event name string
        payload: Optional event payload dict
    """
    if callback is None:
        return
    callback(event, payload or {})


def clean_question_list(raw_questions: list[Any], limit: int = 12) -> list[str]:
    """Normalize, deduplicate, and truncate a list of questions.

    Args:
        raw_questions: Raw question strings or objects
        limit: Maximum number of questions to return

    Returns:
        Deduplicated, normalized list of questions
    """
    deduped_questions: list[str] = []
    seen_questions: set[str] = set()
    for item in raw_questions:
        normalized = re.sub(r"\s+", " ", str(item)).strip()
        key = normalized.lower()
        if len(normalized) < 12 or key in seen_questions:
            continue
        seen_questions.add(key)
        deduped_questions.append(normalized)
        if len(deduped_questions) >= limit:
            break
    return deduped_questions


def extract_source_tokens(source: str) -> set[str]:
    """Extract meaningful tokens from a source file path.

    Args:
        source: Source file path

    Returns:
        Set of lowercase tokens (length >= 4) from filename
    """
    source_name = source.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ").replace("-", " ").lower()
    return {token for token in re.findall(r"[a-z0-9]+", source_name) if len(token) >= 4}


def build_question_anchors(
    material_label: str,
    module_names: list[str],
    key_topics: list[str],
    data_fields: list[str],
) -> list[str]:
    """Build a deduplicated list of anchor terms for relevance checking.

    Args:
        material_label: Material label
        module_names: Module names list
        key_topics: Key topic strings
        data_fields: Data field names

    Returns:
        Unique list of anchor terms (length >= 3)
    """
    anchors: list[str] = []
    seen: set[str] = set()
    for raw in [material_label] + module_names + key_topics + data_fields:
        normalized = re.sub(r"\s+", " ", str(raw)).strip()
        lowered = normalized.lower()
        if len(normalized) < 3 or lowered in seen:
            continue
        seen.add(lowered)
        anchors.append(normalized)
    return anchors


def is_question_relevant(
    question: str,
    source: str,
    material_label: str,
    anchors: list[str],
) -> bool:
    """Check if a question is relevant to this specific material.

    Args:
        question: Question text
        source: Source file path
        material_label: Material label
        anchors: List of anchor terms from the material

    Returns:
        True if the question references material-specific content
    """
    lowered_question = question.lower()
    if material_label and material_label.lower() in lowered_question:
        return True

    for anchor in anchors:
        anchor_lower = anchor.lower()
        if len(anchor_lower) >= 4 and anchor_lower in lowered_question:
            return True

    source_tokens = extract_source_tokens(source)
    if source_tokens and any(token in lowered_question for token in source_tokens):
        return True

    operational_keywords = {
        "workflow", "audit", "approval", "permission", "validation",
        "exception", "rollback", "troubleshoot", "diagnose",
    }
    if any(keyword in lowered_question for keyword in operational_keywords):
        return True
    return False


def build_progressive_question_candidates(
    material_label: str,
    focus_items: list[str],
) -> list[str]:
    """Generate progressive (Basic → Intermediate → Advanced) question candidates.

    Args:
        material_label: Material label used in question templates
        focus_items: Module/topic names to use as anchors

    Returns:
        List of question candidates at multiple difficulty levels
    """
    candidates: list[str] = []
    scoped_items = [item for item in focus_items[:4] if str(item).strip()]
    if not scoped_items:
        return [
            f"Basic: What is the purpose of {material_label} in day-to-day operations?",
            f"Intermediate: Which validation steps should users follow before saving a routine update in {material_label}?",
            f"Advanced: Which failure paths and rollback checks are critical in {material_label} before production use?",
        ]

    basic_templates = [
        "Basic: What is {item} in {label}, and when should users update it?",
        "Basic: Which business need does {item} support in {label}?",
        "Basic: Where in {label} do users access {item}, and what is its primary outcome?",
        "Basic: What is the difference between maintaining {item} versus leaving defaults in {label}?",
    ]
    intermediate_templates = [
        "Intermediate: How should teams validate changes in {item} before saving in {label}?",
        "Intermediate: What pre-checks and post-save checks are required when updating {item} in {label}?",
        "Intermediate: Which approval or handoff steps apply when {item} is modified in {label}?",
        "Intermediate: How would you troubleshoot an unexpected result immediately after changing {item} in {label}?",
    ]
    advanced_templates = [
        "Advanced: Which failure patterns are most likely in {item}, and how should they be diagnosed in {label}?",
        "Advanced: If {item} causes inconsistent behavior across environments, what root-cause path should be followed in {label}?",
        "Advanced: What regression tests should be prioritized after high-risk updates to {item} in {label}?",
    ]

    for index, item in enumerate(scoped_items):
        template = basic_templates[index % len(basic_templates)]
        candidates.append(template.format(item=item, label=material_label))

    for index, item in enumerate(scoped_items):
        template = intermediate_templates[index % len(intermediate_templates)]
        candidates.append(template.format(item=item, label=material_label))

    for index, item in enumerate(scoped_items[:3]):
        template = advanced_templates[index % len(advanced_templates)]
        candidates.append(template.format(item=item, label=material_label))

    if len(scoped_items) >= 2:
        left = scoped_items[0]
        right = scoped_items[1]
        candidates.append(
            f"Advanced: How can misconfiguration across {left} and {right} create downstream production issues in {material_label}, and what should be checked first?"
        )
    else:
        candidates.append(
            f"Advanced: Which edge cases should be tested first to prevent production issues in {material_label}?"
        )

    candidates.append(
        f"Intermediate: Which role-based permissions or approvals are required before publishing changes in {material_label}?"
    )
    return candidates


def filter_relevant_questions(
    questions: list[str],
    source: str,
    material_label: str,
    anchors: list[str],
    limit: int,
) -> list[str]:
    """Filter questions to those most relevant to the material.

    Falls back to all questions if there are too few relevant ones.

    Args:
        questions: Candidate question strings
        source: Source file path
        material_label: Material label
        anchors: Anchor terms for relevance checking
        limit: Maximum questions to return

    Returns:
        Filtered, deduplicated question list
    """
    relevant = [question for question in questions if is_question_relevant(question, source, material_label, anchors)]
    if len(relevant) >= min(8, limit):
        return clean_question_list(relevant, limit=limit)
    return clean_question_list(questions, limit=limit)


def normalize_insight_result(source: str, parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Normalize an LLM-parsed insight result to the expected schema.

    Args:
        source: Material source path
        parsed: Raw parsed LLM output
        fallback: Fallback insight for missing fields

    Returns:
        Normalized insight dict
    """
    deduped_questions = clean_question_list(parsed.get("suggested_questions", []), limit=12)
    return {
        "source": source,
        "summary": str(parsed.get("summary", "")).strip() or fallback["summary"],
        "key_topics": [str(item).strip() for item in parsed.get("key_topics", []) if str(item).strip()][:8],
        "critical_points": [str(item).strip() for item in parsed.get("critical_points", []) if str(item).strip()][:8],
        "suggested_questions": deduped_questions[:12],
    }


def suggested_questions_need_fallback(
    source: str,
    suggested_questions: list[str],
    fallback_questions: list[str],
) -> bool:
    """Check if suggested questions are too generic and need fallback replacement.

    Args:
        source: Material source path
        suggested_questions: LLM-generated questions
        fallback_questions: Heuristic fallback questions

    Returns:
        True if fallback questions should be used instead
    """
    if len(suggested_questions) < 4:
        return True

    lowered = [question.lower() for question in suggested_questions]
    generic_markers = ("this material", "each module", "these examples", "the application")
    marker_hits = sum(1 for question in lowered if any(marker in question for marker in generic_markers))
    if marker_hits >= 3:
        return True

    source_name = source.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ").replace("-", " ").lower()
    source_tokens = {token for token in re.findall(r"[a-z0-9]+", source_name) if len(token) >= 4}
    if source_tokens:
        if not any(any(token in question for token in source_tokens) for question in lowered):
            fallback_lowered = [question.lower() for question in fallback_questions]
            if any(any(token in question for token in source_tokens) for question in fallback_lowered):
                return True

    normalized = [re.sub(r"\s+", " ", question).strip().lower() for question in suggested_questions]
    if len(set(normalized)) <= max(2, len(normalized) // 2):
        return True

    return False
