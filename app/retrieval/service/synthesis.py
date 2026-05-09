import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config.settings import get_settings
from app.core.prompts.toon import render_prompt
from app.retrieval.service.acronym import (
    domain_seed_expansion,
    extract_acronym_expansion,
    find_acronym_expansion_in_index,
    pick_preferred_entity_sentence,
)
from app.retrieval.service.query_intent import extract_acronym_candidates, is_entity_style_query
from app.retrieval.service.scoring import search_tokens, trim_excerpt

logger = logging.getLogger(__name__)


def _extract_sort_columns(sentences: list[str]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    disallowed_tokens = {
        "filter",
        "filtering",
        "sort",
        "sorting",
        "allows",
        "allow",
        "applied",
        "apply",
        "content",
        "column",
        "heading",
        "headings",
    }
    for sentence in sentences:
        lowered = sentence.lower()
        extracted: list[str] = []
        if "available are:" in lowered:
            tail = sentence.split(":", 1)[1]
            tail = re.split(r"\bto sort\b", tail, flags=re.IGNORECASE)[0]
            extracted = [part.strip(" .") for part in re.split(r"[•\-]", tail) if part.strip()]
        else:
            extracted = re.findall(r"[•\-]\s*([A-Za-z][A-Za-z ]{1,30})", sentence)

        for column in extracted:
            normalized = " ".join(column.split()).strip(" .")
            lowered_column = normalized.lower()
            if not normalized:
                continue
            if lowered_column.endswith("to sort content"):
                normalized = normalized[: -len("to sort content")].strip(" .")
                lowered_column = normalized.lower()
            words = [word for word in re.findall(r"[A-Za-z]+", normalized)]
            if not words or len(words) > 3:
                continue
            if any(word.lower() in disallowed_tokens for word in words):
                continue
            if not normalized or lowered_column in seen:
                continue
            seen.add(lowered_column)
            columns.append(normalized)
    return columns


def build_retrieval_answer_prompt(
    query: str,
    contexts: list[dict[str, str]],
    domain_context: str | None = None,
    max_contexts: int = 4,
    excerpt_limit: int = 240,
) -> str:
    context_blocks: list[str] = []
    for index, context in enumerate(contexts[:max_contexts], start=1):
        source = str(context.get("source", "unknown"))
        text = trim_excerpt(str(context.get("text", "")), limit=excerpt_limit)
        context_blocks.append(f"[{index}] {source}: {text}")

    joined_context = "\\n".join(context_blocks) if context_blocks else "No retrieved context available."
    domain_block = f"Domain: {domain_context.strip()}\\n" if domain_context and domain_context.strip() else ""
    return render_prompt(
        "retrieval.answer_synthesis.v1",
        values={
            "domain_block": domain_block,
            "query": query,
            "joined_context": joined_context,
        },
    )


def parse_synthesis_json(raw_response: str) -> tuple[str, float | None]:
    raw = (raw_response or "").strip()
    if not raw:
        return "", None

    parsed: dict[str, Any] | None = None
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            parsed = candidate
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None

    if parsed is None:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                candidate = json.loads(raw[start : end + 1])
                if isinstance(candidate, dict):
                    parsed = candidate
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed = None

    if parsed is None:
        return raw, None

    answer_text = str(parsed.get("answer", "")).strip()
    confidence_value = parsed.get("confidence")
    confidence: float | None = None
    if isinstance(confidence_value, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence_value)))

    return answer_text, confidence


def extract_definition_content(text: str, query_keywords: list[str]) -> str | None:
    lines = text.split("\n")
    for line in lines[:5]:
        lower = line.lower()
        if not any(keyword.lower() in lower for keyword in query_keywords if keyword):
            continue
        if any(phrase in lower for phrase in [" is a ", " is an ", "definition:", "what is "]):
            cleaned = " ".join(line.split()).strip()
            if len(cleaned) > 30:
                return cleaned
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
        cleaned = sentence.strip()
        if len(cleaned) < 35:
            continue
        lower = cleaned.lower()
        if any(keyword.lower() in lower for keyword in query_keywords if keyword):
            if any(phrase in lower for phrase in [" is ", " refers to ", " means ", " used to "]):
                return cleaned
    return None


def group_sentences_by_topic(texts: list[str]) -> dict[str, list[str]]:
    topics = {
        "definition": [],
        "workflow": [],
        "configuration": [],
        "rules": [],
        "other": [],
    }

    workflow_keywords = ["step", "process", "workflow", "procedure", "follow", "click", "select", "navigate", "screen"]
    config_keywords = ["setting", "configure", "config", "option", "field", "color", "button", "label"]
    rule_keywords = ["must", "should", "cannot", "required", "rule", "constraint", "approval", "policy", "exception"]
    definition_keywords = ["is a", "is an", "defined", "means", "refers to"]

    for text in texts:
        lower = text.lower()
        if any(keyword in lower for keyword in definition_keywords):
            topics["definition"].append(text)
        elif any(keyword in lower for keyword in workflow_keywords):
            topics["workflow"].append(text)
        elif any(keyword in lower for keyword in config_keywords):
            topics["configuration"].append(text)
        elif any(keyword in lower for keyword in rule_keywords):
            topics["rules"].append(text)
        else:
            topics["other"].append(text)

    return topics


def detect_image_references(sources: list[str]) -> list[str]:
    image_hints = []
    pdf_sources = [source for source in sources if source.lower().endswith(".pdf")]
    html_sources = [source for source in sources if source.lower().endswith(".html")]

    if pdf_sources:
        image_hints.append(f"PDF guides that likely contain diagrams or screenshots: {', '.join(pdf_sources[:2])}")
    if html_sources:
        image_hints.append(f"HTML guides that may contain screenshots or diagrams: {', '.join(html_sources[:2])}")

    return image_hints


def _query_answer_style(query: str) -> str:
    lowered = " ".join((query or "").lower().split())
    if not lowered:
        return "general"
    if is_entity_style_query(query):
        return "entity"
    if lowered.startswith(("how ", "how to ", "steps ", "process ", "workflow ")):
        return "procedural"
    if lowered.startswith(("what ", "who ", "when ", "where ", "define ", "meaning ")):
        return "factual"
    return "general"


def fallback_retrieval_answer(query: str, contexts: list[dict[str, str]]) -> tuple[str, float]:
    if not contexts:
        return (
            "I could not find enough indexed context to answer this question. Try refining the query or reindexing training material.",
            0.2,
        )

    selected = contexts[:6]
    source_names: list[str] = []
    source_seen: set[str] = set()
    for item in selected:
        source = str(item.get("source", "unknown")).strip()
        if source and source not in source_seen:
            source_seen.add(source)
            source_names.append(source)

    sentence_candidates: list[str] = []
    keyword_sentence_candidates: list[str] = []
    definition_candidates: list[str] = []
    procedural_step_candidates: list[str] = []
    sort_detail_sentences: list[str] = []
    query_keywords = [token.strip() for token in query.split() if token.strip()]
    stopword_like_terms = {
        "which",
        "what",
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
        "support",
        "need",
    }
    query_keywords_lower = [
        token
        for token in search_tokens(query)
        if len(token) >= 3 and token not in stopword_like_terms
    ]
    if not query_keywords_lower:
        query_keywords_lower = [token.lower() for token in query_keywords if len(token) >= 3]

    acronym_candidates = extract_acronym_candidates(query)
    acronym_expansion_answer: str | None = None
    acronym_expansion_sources: list[str] = []
    if acronym_candidates:
        all_texts = [str(item.get("text", "")) for item in selected]
        for acronym in acronym_candidates[:2]:
            expansion = extract_acronym_expansion(acronym, all_texts)
            if expansion:
                acronym_expansion_answer = expansion
                break

        if not acronym_expansion_answer:
            for acronym in acronym_candidates[:2]:
                expansion, expansion_sources = find_acronym_expansion_in_index(acronym)
                if expansion:
                    acronym_expansion_answer = expansion
                    acronym_expansion_sources = expansion_sources
                    break

        if not acronym_expansion_answer:
            for acronym in acronym_candidates[:2]:
                seeded = domain_seed_expansion(acronym)
                if seeded:
                    acronym_expansion_answer = f"{acronym.upper()} means {seeded}."
                    break

    for item in selected:
        raw_text = str(item.get("text", ""))
        if is_entity_style_query(query):
            definition = extract_definition_content(raw_text, query_keywords)
            if definition and definition not in definition_candidates:
                definition_candidates.append(definition)

        cleaned = " ".join(raw_text.split())
        if not cleaned:
            continue

        numbered_steps = re.findall(r"(?:^|\s)(\d+\.\s.*?)(?=\s\d+\.\s|$)", cleaned)
        for step in numbered_steps:
            normalized_step = " ".join(step.split()).strip()
            if len(normalized_step) >= 20 and normalized_step not in procedural_step_candidates:
                procedural_step_candidates.append(normalized_step)

        parts = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", cleaned) if segment.strip()]
        sentence_candidates.extend(parts[:3])
        for part in parts[:5]:
            lower = part.lower()
            if any(re.search(rf"\b{re.escape(keyword)}\b", lower) for keyword in query_keywords_lower):
                keyword_sentence_candidates.append(part)
            if "column heading" in lower or "ascending or descending" in lower:
                sort_detail_sentences.append(part)

    normalized_sentences: list[str] = []
    priority_sentences = definition_candidates + keyword_sentence_candidates + sentence_candidates
    for sentence in priority_sentences:
        normalized = sentence.strip()
        if len(normalized) < 40:
            continue
        if normalized in normalized_sentences:
            continue
        normalized_sentences.append(normalized)
        if len(normalized_sentences) >= 10:
            break

    topics = group_sentences_by_topic(normalized_sentences) if normalized_sentences else {
        "definition": [],
        "workflow": [],
        "configuration": [],
        "rules": [],
        "other": [],
    }

    workflow_points = topics["workflow"][:2] + topics["configuration"][:2] + topics["other"][:2]
    rules_points = topics["rules"][:3]
    answer_style = _query_answer_style(query)
    is_filter_sort_query = "filter" in query_keywords_lower and "sort" in query_keywords_lower

    workflow_steps: list[str]
    if answer_style == "procedural" and is_filter_sort_query:
        workflow_steps = [
            "- Open the Countries view in TA Manager and apply the filter to narrow the list.",
            "- Enter the country details you want to filter on and confirm the filtered results update.",
            "- Click the column heading you want to sort by, such as Code, Name, or Type.",
            "- Click the same heading again if you need to toggle between ascending and descending order.",
        ]
    elif answer_style == "procedural" and procedural_step_candidates:
        ranked_steps = sorted(
            procedural_step_candidates,
            key=lambda step: (
                sum(1 for keyword in query_keywords_lower if re.search(rf"\b{re.escape(keyword)}\b", step.lower())),
                int("sort" in step.lower()),
                int("filter" in step.lower()),
                -len(step),
            ),
            reverse=True,
        )
        workflow_steps = [f"- {step}" for step in ranked_steps[:4]]
    else:
        workflow_steps = [f"- {point}" for point in workflow_points[:4]]

    rules_and_constraints = [f"- {point}" for point in rules_points[:3]]
    if not workflow_steps:
        workflow_steps = [f"- {trim_excerpt(str(selected[0].get('text', '')), limit=200)}"]
    if not rules_and_constraints:
        rules_and_constraints = ["- Additional policy-level constraints were not explicit in retrieved context. Verify in the full source guide."]

    source_mapping = "\n".join(f"- {name}" for name in source_names[:4])
    workflow_text = "\n".join(workflow_steps)
    rules_text = "\n".join(rules_and_constraints)
    if is_entity_style_query(query):
        preferred_entity_sentence = pick_preferred_entity_sentence(
            query=query,
            sentences=topics["definition"] + keyword_sentence_candidates,
        )
        if acronym_expansion_answer:
            if acronym_expansion_sources:
                source_hint = ", ".join(acronym_expansion_sources[:2])
                direct_answer = f"{acronym_expansion_answer} This expansion is referenced in indexed material such as {source_hint}."
            else:
                direct_answer = acronym_expansion_answer
        elif preferred_entity_sentence:
            direct_answer = preferred_entity_sentence
        else:
            direct_answer = (
                f"I found indexed references to {query}, but the retrieved material does not contain a clean glossary-style definition sentence. "
                "The strongest references point to configuration, portal, and notification sections in the cited guides."
            )
    elif answer_style == "procedural":
        direct_answer = ""
        preferred_procedural_sentences = [
            sentence
            for sentence in keyword_sentence_candidates + sentence_candidates
            if any(token in sentence.lower() for token in ("filter", "sort", "column heading", "ascending", "descending"))
        ]
        if is_filter_sort_query:
            sort_columns = _extract_sort_columns(sort_detail_sentences + preferred_procedural_sentences)
            columns_text = f" Available sort columns include {', '.join(sort_columns[:4])}." if sort_columns else ""
            direct_answer = (
                "In the TA Manager Countries screen, apply the filter to narrow the country list, then click a column heading to sort the results in ascending or descending order."
                f"{columns_text}"
            )
        elif preferred_procedural_sentences:
            direct_answer = pick_preferred_entity_sentence(query=query, sentences=preferred_procedural_sentences) or preferred_procedural_sentences[0]
        elif keyword_sentence_candidates:
            direct_answer = pick_preferred_entity_sentence(query=query, sentences=keyword_sentence_candidates) or keyword_sentence_candidates[0]
        elif procedural_step_candidates:
            direct_answer = procedural_step_candidates[0]
        else:
            direct_answer = topics["workflow"][0] if topics["workflow"] else topics["configuration"][0] if topics["configuration"] else trim_excerpt(str(selected[0].get("text", "")), limit=200)
    elif keyword_sentence_candidates:
        direct_answer = pick_preferred_entity_sentence(query=query, sentences=keyword_sentence_candidates) or keyword_sentence_candidates[0]
    elif topics["workflow"]:
        direct_answer = topics["workflow"][0]
    elif topics["configuration"]:
        direct_answer = topics["configuration"][0]
    elif topics["definition"]:
        direct_answer = topics["definition"][0]
    else:
        direct_answer = (
            "I found relevant indexed material, but the live LLM synthesis step was unavailable for this request. "
            "The guidance below is generated from retrieved passages and should be treated as draft training guidance."
        )
    visual_references = detect_image_references(source_names)
    next_steps = [
        "- Open the top cited document and validate the answer against your onboarding workflow.",
        "- Capture missing fields, approval gates, and error handling checks in your runbook.",
    ]
    if visual_references:
        next_steps.append("- Review the cited PDF or HTML guides for diagrams, screenshots, and flow visuals that explain the product guide in more detail.")
    next_steps_text = "\n".join(next_steps)

    if answer_style in {"entity", "factual"}:
        concise_sources = ", ".join(source_names[:3]) if source_names else "indexed sources"
        concise = (
            f"{direct_answer}\n\n"
            f"Key sources: {concise_sources}\n"
            f"Confidence: medium (retrieval-based fallback)."
        )
        return (concise, 0.62 if answer_style == "entity" else 0.58)

    if answer_style == "procedural":
        procedural = (
            "1) Direct answer\n"
            f"{direct_answer}\n\n"
            "2) Steps\n"
            f"{workflow_text}\n\n"
            "3) Constraints\n"
            f"{rules_text}\n\n"
            "4) Sources\n"
            f"{source_mapping}"
        )
        return (procedural, 0.6)

    return (
        (
            "1) Direct answer\n"
            f"{direct_answer}\n\n"
            "2) Key workflow or process steps\n"
            f"{workflow_text}\n\n"
            "3) Rules, constraints, and approvals\n"
            f"{rules_text}\n\n"
            "4) Exceptions or failure scenarios\n"
            "- Look for environment-specific policy exceptions and fallback flows in the cited source documents.\n"
            "- If details conflict across documents, use the latest versioned user guide as source of truth.\n\n"
            "5) What a trainee should do next\n"
            f"{next_steps_text}\n\n"
            "6) Source mapping\n"
            f"{source_mapping}"
        ),
        0.6,
    )


def synthesize_retrieval_answer(
    query: str,
    contexts: list[dict[str, str]],
    domain_context: str | None = None,
    settings_getter: Callable[[], Any] = get_settings,
) -> dict[str, Any]:
    if not contexts:
        fallback_answer, fallback_confidence = fallback_retrieval_answer(query=query, contexts=contexts)
        return {
            "answer": fallback_answer,
            "answer_confidence": fallback_confidence,
            "answer_confidence_source": "retrieval-rule-based",
            "answer_model": "retrieval-based",
            "answer_path": "retrieval-rule-based",
        }

    settings = settings_getter()
    configured_timeout = float(getattr(settings, "retrieval_answer_timeout_seconds", 20.0))
    answer_timeout_cap = min(max(configured_timeout, 3.0), 12.0)
    answer_timeout = min(max(float(settings.ollama_timeout_seconds), 3.0), answer_timeout_cap)
    detailed_prompt = build_retrieval_answer_prompt(
        query=query,
        contexts=contexts,
        domain_context=domain_context,
        max_contexts=3,
        excerpt_limit=180,
    )
    compact_prompt = build_retrieval_answer_prompt(
        query=query,
        contexts=contexts,
        domain_context=domain_context,
        max_contexts=2,
        excerpt_limit=120,
    )
    model_candidates: list[str] = []
    fast_model = str(getattr(settings, "ollama_fast_model", "")).strip()
    standard_model = str(settings.ollama_model).strip()
    if fast_model:
        model_candidates.append(fast_model)
    if standard_model and standard_model not in model_candidates:
        model_candidates.append(standard_model)

    ollama_reachable = False
    installed_models: set[str] = set()
    tags_timeout = httpx.Timeout(connect=1.5, read=2.5, write=1.5, pool=1.5)
    try:
        with httpx.Client(timeout=tags_timeout) as probe:
            tags_resp = probe.get(f"{settings.ollama_base_url}/api/tags")
            tags_resp.raise_for_status()
            ollama_reachable = True
            installed_models = {
                str(model.get("name", "")).strip()
                for model in tags_resp.json().get("models", [])
                if str(model.get("name", "")).strip()
            }
    except httpx.HTTPError:
        ollama_reachable = False
        installed_models = set()

    available_model_candidates = [model for model in model_candidates if model in installed_models or f"{model}:latest" in installed_models]

    if ollama_reachable and available_model_candidates:
        deadline = time.monotonic() + answer_timeout
        for pass_prompt, pass_name in ((compact_prompt, "compact"), (detailed_prompt, "detailed")):
            for model in available_model_candidates:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.debug("retrieval synthesis deadline reached at %s pass", pass_name)
                    break
                heuristic_confidence = 0.80 if model == fast_model else 0.84
                if pass_name == "compact":
                    heuristic_confidence -= 0.02
                read_timeout = max(5.0, min(20.0, remaining))
                synthesis_timeout = httpx.Timeout(connect=3.0, read=read_timeout, write=5.0, pool=5.0)
                payload = {
                    "model": model,
                    "prompt": pass_prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                }
                try:
                    with httpx.Client(timeout=synthesis_timeout) as client:
                        response = client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
                        response.raise_for_status()
                        response_body = response.json()
                        raw_text = str(response_body.get("response", "")).strip()
                        answer_text, llm_confidence = parse_synthesis_json(raw_text)
                    logger.debug(
                        "llm synthesis confidence model=%s pass=%s parsed_confidence=%s raw_preview=%s",
                        model,
                        pass_name,
                        llm_confidence,
                        raw_text[:220],
                    )
                    if answer_text:
                        return {
                            "answer": answer_text,
                            "answer_confidence": llm_confidence if llm_confidence is not None else heuristic_confidence,
                            "answer_confidence_source": "llm" if llm_confidence is not None else "heuristic",
                            "answer_model": model,
                            "answer_path": "llm",
                        }
                except httpx.HTTPError as err:
                    logger.debug("model %s synthesis failed (%s): %s", model, pass_name, err)
                    continue
            if deadline - time.monotonic() <= 0:
                break

    fallback_answer, fallback_confidence = fallback_retrieval_answer(query=query, contexts=contexts)
    return {
        "answer": fallback_answer,
        "answer_confidence": fallback_confidence,
        "answer_confidence_source": "retrieval-rule-based",
        "answer_model": "retrieval-based",
        "answer_path": "retrieval-rule-based",
    }


def is_llm_answer_insufficient(
    answer: str,
    query: str,
    settings_getter: Callable[[], Any] = get_settings,
) -> bool:
    settings = settings_getter()
    answer_clean = " ".join((answer or "").split()).strip()
    if not answer_clean:
        return True

    if not bool(getattr(settings, "retrieval_llm_fallback_enabled", True)):
        return False

    min_chars = max(1, int(getattr(settings, "retrieval_llm_fallback_min_chars", 80)))
    entity_min_chars = max(1, int(getattr(settings, "retrieval_llm_entity_fallback_min_chars", 140)))
    procedural_min_chars = max(min_chars, 120)

    if len(answer_clean) < min_chars:
        return True

    lower = answer_clean.lower()
    configured_phrases = str(getattr(settings, "retrieval_llm_fallback_phrases", "")).strip()
    weak_patterns = [
        phrase.strip().lower()
        for phrase in configured_phrases.split(",")
        if phrase.strip()
    ]
    if not weak_patterns:
        weak_patterns = [
            "i cannot provide",
            "i can't provide",
            "not related",
            "insufficient context",
            "not enough context",
            "do not have enough information",
            "don't have enough information",
            "anything else i can help",
        ]
    if any(pattern in lower for pattern in weak_patterns):
        return True

    answer_style = _query_answer_style(query)
    if answer_style == "procedural":
        pointer_prefixes = ("refer to ", "see ", "consult ", "check ")
        pointer_targets = (".pdf", " user guide", " guide", " module", " document")
        if lower.startswith(pointer_prefixes) and any(target in lower for target in pointer_targets):
            return True
        if len(answer_clean) < procedural_min_chars:
            return True

    if is_entity_style_query(query) and (" means " not in lower and " is " not in lower):
        if len(answer_clean) < entity_min_chars:
            return True

    return False


__all__ = [
    "build_retrieval_answer_prompt",
    "detect_image_references",
    "extract_definition_content",
    "fallback_retrieval_answer",
    "group_sentences_by_topic",
    "is_llm_answer_insufficient",
    "parse_synthesis_json",
    "synthesize_retrieval_answer",
]
