"""LLM-based insight and question generation via Ollama."""

import json
import re
import time
from typing import Any

import httpx

from app.core.config.settings import get_settings
from app.core.observability.langsmith import traceable
from app.core.prompts.toon import render_prompt
from app.retrieval.insight.content import (
    extract_data_fields,
    extract_module_entries,
    infer_material_label,
)
from app.retrieval.insight.fallback import build_structured_fallback_details, summary_needs_fallback
from app.retrieval.insight.index import trim_excerpt
from app.retrieval.insight.questions import (
    InsightProgressCallback,
    build_question_anchors,
    clean_question_list,
    emit_progress,
    filter_relevant_questions,
    normalize_insight_result,
    suggested_questions_need_fallback,
)


def parse_insight_json(raw: str) -> dict[str, Any] | None:
    """Try to parse a JSON object from LLM output.

    Handles both clean JSON and JSON embedded within surrounding text.

    Args:
        raw: Raw LLM response string

    Returns:
        Parsed dict or None if parsing fails
    """
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return None


def _extract_questions_from_text(raw: str, limit: int = 12) -> list[str]:
    """Extract question-like lines from plain text model output."""
    questions: list[str] = []
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    for line in lines:
        if not line:
            continue
        # Remove bullets/numbering prefixes like "1.", "-", "*", ")".
        cleaned = re.sub(r"^(?:[-*\u2022]|\d+[\.)]|[a-zA-Z][\.)])\s+", "", line).strip()
        if not cleaned:
            continue
        if not cleaned.endswith("?"):
            continue
        questions.append(cleaned)
    return clean_question_list(questions, limit=limit)


def select_insight_model(settings: Any) -> str:
    """Select the model to use for insight generation.

    Prefers `ollama_fast_model` if configured, falls back to `ollama_model`.
    """
    fast_model = str(getattr(settings, "ollama_fast_model", "")).strip()
    if fast_model:
        return fast_model
    return str(settings.ollama_model)


def select_question_model(settings: Any) -> str:
    """Select the model for question generation, or 'disabled' if not configured."""
    question_model = str(getattr(settings, "ollama_question_model", "")).strip()
    return question_model or "disabled"


@traceable(
    name="retrieval.material_insight_ollama",
    run_type="llm",
    tags=["retrieval", "insight", "ollama"],
    metadata={"component": "retrieval", "stage": "insight-llm"},
)
def generate_insight_with_ollama(
    source: str,
    prompt: str | list[str],
    fallback: dict[str, Any],
    callback: InsightProgressCallback | None = None,
) -> dict[str, Any]:
    """Generate material insight using Ollama streaming LLM.

    Tries primary model then falls back to standard model. Validates
    output quality and substitutes fallback sections if needed.

    Args:
        source: Material source path
        prompt: Insight generation prompt
        fallback: Fallback insight dict for poor-quality LLM output
        callback: Optional progress callback

    Returns:
        Insight result dict with model and generation metadata
    """
    settings = get_settings()
    primary_model = select_insight_model(settings)
    model_candidates = [primary_model]
    standard_model = str(settings.ollama_model).strip()
    if standard_model and standard_model not in model_candidates:
        model_candidates.append(standard_model)
    timeout_seconds = max(15.0, min(float(getattr(settings, "ollama_insight_timeout_seconds", 35.0)), 90.0))
    prompt_candidates = prompt if isinstance(prompt, list) else [prompt]
    primary_model = model_candidates[0] if model_candidates else ""

    for model in model_candidates:
        timed_out_attempts = 0
        for prompt_index, prompt_text in enumerate(prompt_candidates, start=1):
            payload = {
                "model": model,
                "prompt": prompt_text,
                "stream": True,
                "format": "json",
                "options": {"temperature": 0.1},
            }
            emit_progress(
                callback,
                "generating",
                {"model": model, "timeout_seconds": timeout_seconds, "prompt_attempt": prompt_index, "prompt_count": len(prompt_candidates)},
            )
            start_time = time.time()
            chunks: list[str] = []
            timed_out = False
            request_timeout = httpx.Timeout(
                timeout_seconds,
                connect=min(5.0, timeout_seconds),
                read=timeout_seconds,
                write=timeout_seconds,
                pool=timeout_seconds,
            )
            try:
                with httpx.Client(timeout=request_timeout) as client:
                    with client.stream("POST", f"{settings.ollama_base_url}/api/generate", json=payload) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if not line:
                                continue
                            try:
                                row = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            token = str(row.get("response", ""))
                            if token:
                                chunks.append(token)
                            if time.time() - start_time >= timeout_seconds:
                                timed_out = True
                                emit_progress(
                                    callback,
                                    "timeout_partial",
                                    {"model": model, "elapsed_ms": int((time.time() - start_time) * 1000), "prompt_attempt": prompt_index},
                                )
                                break
            except httpx.TimeoutException:
                timed_out = True
                emit_progress(
                    callback,
                    "timeout_partial",
                    {"model": model, "elapsed_ms": int((time.time() - start_time) * 1000), "prompt_attempt": prompt_index},
                )
            except httpx.HTTPError:
                emit_progress(callback, "model_error", {"model": model, "prompt_attempt": prompt_index})
                continue

            raw = "".join(chunks).strip()
            if timed_out:
                timed_out_attempts += 1
                continue

            parsed = parse_insight_json(raw)
            if parsed is None:
                emit_progress(callback, "fallback", {"reason": "json_parse_failed", "model": model, "prompt_attempt": prompt_index})
                continue

            result = normalize_insight_result(source, parsed, fallback)
            if summary_needs_fallback(result["summary"]):
                result["summary"] = fallback["summary"]
                result["key_topics"] = fallback["key_topics"]
                result["critical_points"] = fallback["critical_points"]
                result["suggested_questions"] = fallback["suggested_questions"]
            elif suggested_questions_need_fallback(source, result["suggested_questions"], fallback["suggested_questions"]):
                result["suggested_questions"] = fallback["suggested_questions"]
            result["cached"] = False
            result["partial"] = False
            result["model"] = model
            result["generation_ms"] = int((time.time() - start_time) * 1000)
            result["prompt_attempt"] = prompt_index
            return result

        if timed_out_attempts >= len(prompt_candidates) and model == primary_model:
            emit_progress(
                callback,
                "fallback",
                {"reason": "ollama_timeout", "model": model, "exhausted_prompt_budgets": True},
            )
            return {
                **fallback,
                "cached": False,
                "partial": False,
                "model": model,
                "generation_ms": int(timeout_seconds * 1000),
                "insight_timeout_exhausted": True,
            }

    emit_progress(callback, "fallback", {"reason": "ollama_http_error"})
    return {
        **fallback,
        "cached": False,
        "partial": False,
        "model": "fallback",
        "generation_ms": 0,
        "insight_timeout_exhausted": False,
    }


@traceable(
    name="retrieval.suggested_questions_qwen",
    run_type="llm",
    tags=["retrieval", "insight", "questions", "ollama"],
    metadata={"component": "retrieval", "stage": "question-llm"},
)
def generate_questions_with_ollama(
    source: str,
    chunks: list[str],
    existing_questions: list[str],
    question_model: str | None = None,
    callback: InsightProgressCallback | None = None,
) -> list[str]:
    """Generate additional suggested questions using Ollama.

    Args:
        source: Material source path
        chunks: Prepared text chunks
        existing_questions: Already-generated questions to avoid duplicating
        question_model: Optional explicit model override for question generation
        callback: Optional progress callback

    Returns:
        Additional question strings from the LLM
    """
    settings = get_settings()
    resolved_model = (question_model or getattr(settings, "ollama_question_model", None) or "").strip()
    if not resolved_model:
        return []

    timeout_seconds = max(10.0, min(float(getattr(settings, "ollama_question_timeout_seconds", 120.0)), 180.0))
    emit_progress(callback, "generating_questions", {"model": resolved_model, "timeout_seconds": timeout_seconds})
    request_timeout = httpx.Timeout(
        timeout_seconds,
        connect=min(5.0, timeout_seconds),
        read=timeout_seconds,
        write=timeout_seconds,
        pool=timeout_seconds,
    )
    module_entries = extract_module_entries(chunks)
    material_label = infer_material_label(source, module_entries, " ".join(chunks))
    existing_block = "\n".join(f"- {q}" for q in existing_questions[:6])

    # Retry with smaller excerpt budgets when large prompts time out on 14B models.
    excerpt_budgets: list[tuple[int, int]] = [(3, 400), (2, 300), (2, 200)]
    with httpx.Client(timeout=request_timeout) as client:
        for chunk_limit, char_limit in excerpt_budgets:
            excerpts = "\n\n".join(trim_excerpt(chunk, limit=char_limit) for chunk in chunks[:chunk_limit])
            prompt = render_prompt(
                "retrieval.material_questions.v1",
                values={
                    "material_label": material_label,
                    "existing_block": existing_block,
                    "excerpts": excerpts,
                },
            )
            payload = {
                "model": resolved_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
            }

            body: dict[str, Any] | None = None
            raw = ""
            try:
                for attempt in range(2):
                    response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
                    response.raise_for_status()
                    parsed_body = response.json()
                    if isinstance(parsed_body, dict):
                        body = parsed_body
                    else:
                        body = {}
                    raw = str(body.get("response", "")).strip()
                    # Ollama can return an initial empty response with done_reason=load
                    # while loading a large model. Retry once to get the actual output.
                    if raw:
                        break
                    if attempt == 0 and str(body.get("done_reason", "")).strip().lower() == "load":
                        emit_progress(callback, "generating_questions", {"model": resolved_model, "retry_after_load": True})
                        continue
                    break
            except (httpx.TimeoutException, httpx.HTTPError, ValueError):
                emit_progress(
                    callback,
                    "generating_questions",
                    {
                        "model": resolved_model,
                        "retry_budget": {"chunks": chunk_limit, "chars": char_limit},
                    },
                )
                continue

            if not raw:
                continue

            parsed: dict[str, Any] | None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = parse_insight_json(raw)

            if isinstance(parsed, dict):
                candidates = parsed.get("suggested_questions")
                if not isinstance(candidates, list):
                    candidates = parsed.get("questions")
                if not isinstance(candidates, list):
                    items = parsed.get("items")
                    if isinstance(items, list):
                        candidates = [item.get("question") for item in items if isinstance(item, dict)]
                if isinstance(candidates, list):
                    normalized = clean_question_list([str(item) for item in candidates if str(item).strip()], limit=12)
                    if normalized:
                        return normalized

            # Fallback: qwen may return a plain numbered/bulleted list despite JSON instruction.
            extracted = _extract_questions_from_text(raw, limit=12)
            if extracted:
                return extracted

    emit_progress(callback, "questions_fallback", {"reason": "ollama_question_error", "model": resolved_model})
    return []


def ensure_question_target(
    source: str,
    chunks: list[str],
    base_questions: list[str],
    min_questions: int = 8,
    max_questions: int = 12,
) -> list[str]:
    """Ensure the question list meets the minimum count target.

    Supplements with heuristic progressive questions if needed.

    Args:
        source: Material source path
        chunks: Text chunks
        base_questions: Initial question list
        min_questions: Minimum desired question count
        max_questions: Maximum question count

    Returns:
        Question list meeting the min/max bounds
    """
    questions = clean_question_list(base_questions, limit=max_questions)
    if len(questions) >= min_questions:
        return questions[:max_questions]

    from app.retrieval.insight.questions import (
        build_progressive_question_candidates,
    )

    combined = " ".join(chunks)
    module_entries = extract_module_entries(chunks)
    module_names = [name for name, _ in module_entries]
    data_fields = extract_data_fields(combined)
    material_label = infer_material_label(source, module_entries, combined)

    _, key_topics, critical_points, fallback_questions = build_structured_fallback_details(source, chunks)
    anchors = build_question_anchors(material_label, module_names, key_topics, data_fields)
    questions = filter_relevant_questions(
        clean_question_list(questions + fallback_questions, limit=max_questions),
        source,
        material_label,
        anchors,
        limit=max_questions,
    )
    if len(questions) >= min_questions:
        return questions[:max_questions]

    focus_items = [item for item in (module_names + key_topics + data_fields) if str(item).strip()]
    dedup_focus: list[str] = []
    seen_focus: set[str] = set()
    for item in focus_items:
        normalized = re.sub(r"\s+", " ", str(item)).strip()
        normalized = re.split(r"\s+Note:\s|\s+\(|:\s+[A-Z]", normalized, maxsplit=1)[0].strip()
        normalized = normalized[:60].strip()
        key = normalized.lower()
        if not normalized or key in seen_focus:
            continue
        seen_focus.add(key)
        dedup_focus.append(normalized)

    candidates = build_progressive_question_candidates(material_label, dedup_focus)

    for point in critical_points[:4]:
        normalized_point = re.sub(r"\s+", " ", point).strip().rstrip(".")
        if normalized_point:
            candidates.append(
                f"Intermediate: What verification steps confirm that '{normalized_point}' is correctly implemented in {material_label}?"
            )

    prioritized_questions = clean_question_list(candidates + questions, limit=max_questions)
    questions = filter_relevant_questions(
        prioritized_questions,
        source,
        material_label,
        anchors,
        limit=max_questions,
    )
    return questions[:max_questions]


def generate_question_bank_with_ollama(
    source: str,
    chunks: list[str],
    existing_questions: list[str],
    question_model: str | None = None,
    strict_model_only: bool = False,
    callback: InsightProgressCallback | None = None,
) -> list[str]:
    """Build a complete question bank using LLM plus heuristic fallback.

    Args:
        source: Material source path
        chunks: Prepared text chunks
        existing_questions: Starting question set
        question_model: Optional explicit model override for question generation
        callback: Optional progress callback

    Returns:
        Complete question list. In strict mode, returns only model-generated
        questions with no heuristic supplementation.
    """
    min_questions = 8
    max_questions = 12
    questions = clean_question_list(existing_questions, limit=max_questions)
    llm_questions = generate_questions_with_ollama(
        source,
        chunks,
        questions,
        question_model=question_model,
        callback=callback,
    )
    if strict_model_only:
        return clean_question_list(llm_questions, limit=max_questions)
    if llm_questions:
        questions = clean_question_list(questions + llm_questions, limit=max_questions)
    return ensure_question_target(source, chunks, questions, min_questions=min_questions, max_questions=max_questions)
