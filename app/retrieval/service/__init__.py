from pathlib import Path
import time
import logging
import re
from typing import Any
from urllib.parse import quote

from app.core.config.settings import get_settings
from app.core.observability.metrics import MetricsCollector
from app.core.observability.langsmith import traceable
from app.ingestion.pipeline import get_last_ingestion_report, resolve_ingestion_source_dir
from app.retrieval.index import load_local_index
from app.retrieval.pipeline import retrieve_context, rewrite_query_for_retrieval
from app.retrieval.pipeline.orchestrators.llamaindex_orchestrator import (
    retrieve_context_with_llamaindex,
)
from app.retrieval.service.acronym import (
    domain_seed_expansion as get_seed_acronym_expansion,
)
from app.retrieval.service.cache import (
    get_cached_retrieval_search,
    set_cached_retrieval_search,
)
from app.retrieval.service.semantic_cache import (
    find_semantic_cache_hit,
    upsert_semantic_cache_entry,
)
from app.retrieval.service.similarity_tracker import (
    find_similar_query,
    record_query_signature,
)
from app.retrieval.service.acronym import (
    extract_acronym_expansion as extract_acronym_expansion_text,
)
from app.retrieval.service.acronym import (
    find_acronym_expansion_in_index as find_indexed_acronym_expansion,
)
from app.retrieval.service.acronym import (
    infer_acronym_expansion_from_texts as infer_acronym_expansion,
)
from app.retrieval.service.acronym import (
    looks_like_acronym_expansion as is_acronym_expansion_phrase,
)
from app.retrieval.service.acronym import (
    pick_preferred_entity_sentence as select_preferred_entity_sentence,
)
from app.retrieval.service.overview import get_retrieval_overview as build_retrieval_overview
from app.retrieval.service.query_intent import (
    extract_acronym_candidates,
    is_entity_style_query,
    normalize_training_question_query,
    query_variants,
)
from app.retrieval.service.schemas import (
    RetrievalCitation,
    RetrievalResultItem,
    RetrievalSearchResponse,
    RetrievalVisualReference,
)
from app.retrieval.service.scoring import (
    merge_and_rank_contexts as rank_contexts,
)
from app.retrieval.service.scoring import (
    search_tokens as tokenize_search_text,
)
from app.retrieval.service.scoring import (
    trim_excerpt as summarize_excerpt,
)
from app.retrieval.service.synthesis import (
    build_retrieval_answer_prompt as compose_retrieval_answer_prompt,
)
from app.retrieval.service.synthesis import (
    detect_image_references as collect_image_references,
)
from app.retrieval.service.synthesis import (
    extract_definition_content as extract_definition_text,
)
from app.retrieval.service.synthesis import (
    fallback_retrieval_answer as compose_fallback_retrieval_answer,
)
from app.retrieval.service.synthesis import (
    group_sentences_by_topic as classify_sentences_by_topic,
)
from app.retrieval.service.synthesis import (
    is_llm_answer_insufficient as llm_answer_is_insufficient,
)
from app.retrieval.service.synthesis import (
    parse_synthesis_json as parse_retrieval_synthesis_json,
)
from app.retrieval.service.synthesis import (
    synthesize_retrieval_answer as compose_synthesized_retrieval_answer,
)
from app.retrieval.service.visuals import (
    build_visual_references,
    render_pdf_preview,
    visual_preview_dir,
)
from app.retrieval.service.visuals import (
    render_chunk_page_image as render_visual_chunk_page_image,
)
from app.retrieval.service.visuals import (
    resolve_visual_reference_source as resolve_visual_source,
)
from app.agents import build_retrieval_plan, choose_orchestrator, select_final_answer_payload

logger = logging.getLogger(__name__)


def _extract_answer_page_question(text: str) -> str:
    match = re.search(r"^\s*#\s*Q:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    return " ".join(match.group(1).split()).strip()


def _extract_answer_page_confidence(text: str) -> float:
    match = re.search(r"\*\*Confidence:\*\*\s*([0-9]+(?:\.[0-9]+)?)\s*%", text, flags=re.IGNORECASE)
    if not match:
        return 0.0
    try:
        return float(match.group(1)) / 100.0
    except ValueError:
        return 0.0


def _question_overlap_score(query: str, candidate: str) -> float:
    query_tokens = {token for token in tokenize_search_text(query) if len(token) >= 4}
    candidate_tokens = {token for token in tokenize_search_text(candidate) if len(token) >= 4}
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = len(query_tokens.intersection(candidate_tokens))
    return overlap / max(len(query_tokens), 1)


def _cached_wiki_answer_is_valid(query: str, payload: dict[str, Any]) -> bool:
    answer_model = str(payload.get("answer_model", "")).strip().lower()
    answer_path = str(payload.get("answer_path", "")).strip().lower()
    if answer_model != "wiki-based" and answer_path != "wiki-rule-based":
        return True

    answer_text = str(payload.get("answer", "")).strip()
    if not answer_text:
        return False

    settings = get_settings()
    min_answer_confidence = float(getattr(settings, "wiki_auto_file_min_confidence", 0.8) or 0.8)
    min_answer_question_overlap = 0.35

    answer_confidence = _extract_answer_page_confidence(answer_text)
    if answer_confidence < min_answer_confidence:
        return False

    answer_question = _extract_answer_page_question(answer_text)
    overlap = _question_overlap_score(query, answer_question)
    return overlap >= min_answer_question_overlap


def _is_wiki_answer_context(context: dict[str, str]) -> bool:
    return str(context.get("source", "")).startswith("wiki/answers/")


def _wiki_page_candidates(wiki_dir: Path) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    for kind in ("answers", "sources", "entities", "concepts"):
        base = wiki_dir / kind
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md")):
            candidates.append((kind, path))
    return candidates


def _load_wiki_contexts(query: str, wiki_dir: Path, top_k: int) -> list[dict[str, str]]:
    if top_k <= 0 or not wiki_dir.exists():
        return []

    settings = get_settings()
    min_answer_confidence = float(getattr(settings, "wiki_auto_file_min_confidence", 0.8) or 0.8)
    min_answer_question_overlap = 0.35

    ranked: list[tuple[float, dict[str, str]]] = []
    for kind, path in _wiki_page_candidates(wiki_dir):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue

        if kind == "answers":
            answer_confidence = _extract_answer_page_confidence(text)
            if answer_confidence < min_answer_confidence:
                continue

            answer_question = _extract_answer_page_question(text)
            overlap = _question_overlap_score(query, answer_question)
            if overlap < min_answer_question_overlap:
                continue

        score = _keyword_relevance_score(query=query, source=str(path), text=text)
        score += _content_quality_score(text)
        if kind == "answers":
            score += 0.35
        elif kind in {"entities", "concepts"}:
            score += 0.15

        ranked.append(
            (
                score,
                {
                    "source": f"wiki/{kind}/{path.name}",
                    "chunk_id": f"wiki-{kind}-{path.stem}",
                    "text": text,
                },
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [context for _, context in ranked[:top_k]]


def _wiki_response(
    *,
    query: str,
    retrieval_query: str,
    orchestrator_name: str,
    contexts: list[dict[str, str]],
    domain_context: str | None,
) -> RetrievalSearchResponse:
    wiki_llm_payload = _synthesize_retrieval_answer(
        query=query,
        contexts=contexts,
        domain_context=domain_context,
    )
    wiki_rule_answer, wiki_rule_confidence = _fallback_retrieval_answer(query=query, contexts=contexts)
    wiki_rule_payload = {
        "answer": wiki_rule_answer,
        "answer_confidence": wiki_rule_confidence,
        "answer_confidence_source": "wiki-rule-based",
        "answer_model": "wiki-based",
        "answer_path": "wiki-rule-based",
    }

    llm_available = wiki_llm_payload.get("answer_path") == "llm"
    llm_answer = str(wiki_llm_payload.get("answer", "")).strip() if llm_available else ""

    fallback_reason = ""
    if not llm_available:
        fallback_reason = "wiki_llm_unavailable"
    elif _is_llm_answer_insufficient(llm_answer, query):
        fallback_reason = "wiki_llm_low_detail"

    final_answer_payload = wiki_rule_payload if fallback_reason else wiki_llm_payload

    citations: list[RetrievalCitation] = [
        {
            "source": context["source"],
            "chunk_id": context["chunk_id"],
        }
        for context in contexts[:4]
    ]
    results: list[RetrievalResultItem] = [
        {
            "source": context["source"],
            "chunk_id": context["chunk_id"],
            "excerpt": _trim_excerpt(context["text"], limit=320),
            "page_image_url": "",
        }
        for context in contexts
    ]

    return {
        "query": query,
        "retrieval_query": retrieval_query,
        "orchestrator": orchestrator_name,
        "answer": final_answer_payload["answer"],
        "answer_confidence": final_answer_payload["answer_confidence"],
        "answer_confidence_source": final_answer_payload.get("answer_confidence_source", "wiki"),
        "answer_model": final_answer_payload["answer_model"],
        "answer_path": final_answer_payload.get("answer_path", "wiki"),
        "llm_answer": llm_answer,
        "llm_answer_confidence": wiki_llm_payload.get("answer_confidence", 0.0) if llm_available else 0.0,
        "llm_answer_confidence_source": wiki_llm_payload.get("answer_confidence_source", "none") if llm_available else "none",
        "llm_answer_model": wiki_llm_payload.get("answer_model", "") if llm_available else "",
        "retrieval_answer": wiki_rule_payload["answer"],
        "retrieval_answer_confidence": wiki_rule_payload["answer_confidence"],
        "retrieval_answer_confidence_source": wiki_rule_payload["answer_confidence_source"],
        "retrieval_answer_model": wiki_rule_payload["answer_model"],
        "fallback_used": bool(fallback_reason),
        "fallback_reason": fallback_reason,
        "citations": citations,
        "visual_references": [],
        "result_count": len(contexts),
        "results": results,
        "cached": False,
        "cache_age_seconds": 0,
        "semantic_cache_hit": False,
        "semantic_cache_score": 0.0,
        "semantic_cache_kind": "none",
        "semantic_cache_source": "none",
    }


def _trim_excerpt(text: str, limit: int = 260) -> str:
    return summarize_excerpt(text, limit=limit)


def _load_local_index_items() -> list[dict[str, Any]]:
    return load_local_index()


def _search_tokens(text: str) -> list[str]:
    return tokenize_search_text(text)


def _extract_acronym_candidates(query: str) -> list[str]:
    return extract_acronym_candidates(query)


def _is_entity_style_query(query: str) -> bool:
    return is_entity_style_query(query)




def _keyword_relevance_score(query: str, source: str, text: str) -> float:
    from app.retrieval.service.scoring import keyword_relevance_score

    return keyword_relevance_score(query=query, source=source, text=text)


def _content_quality_score(text: str) -> float:
    from app.retrieval.service.scoring import content_quality_score

    return content_quality_score(text)


def _merge_and_rank_contexts(
    query: str,
    original_contexts: list[dict[str, str]],
    rewritten_contexts: list[dict[str, str]],
    top_k: int,
) -> list[dict[str, str]]:
    return rank_contexts(
        query=query,
        original_contexts=original_contexts,
        rewritten_contexts=rewritten_contexts,
        top_k=top_k,
    )


def _build_retrieval_answer_prompt(
    query: str,
    contexts: list[dict[str, str]],
    domain_context: str | None = None,
    max_contexts: int = 4,
    excerpt_limit: int = 240,
) -> str:
    return compose_retrieval_answer_prompt(
        query=query,
        contexts=contexts,
        domain_context=domain_context,
        max_contexts=max_contexts,
        excerpt_limit=excerpt_limit,
    )


def _parse_synthesis_json(raw_response: str) -> tuple[str, float | None]:
    return parse_retrieval_synthesis_json(raw_response)


def _extract_definition_content(text: str, query_keywords: list[str]) -> str | None:
    return extract_definition_text(text, query_keywords)


def _group_sentences_by_topic(texts: list[str]) -> dict[str, list[str]]:
    return classify_sentences_by_topic(texts)


def _detect_image_references(sources: list[str]) -> list[str]:
    return collect_image_references(sources)


def resolve_visual_reference_source(source_name: str) -> Path | None:
    return resolve_visual_source(source_name)


def _visual_preview_dir() -> Path:
    return visual_preview_dir()


def _render_pdf_preview(source_path: Path) -> Path | None:
    return render_pdf_preview(source_path)


def render_chunk_page_image(source: str, chunk_text: str) -> Path | None:
    return render_visual_chunk_page_image(source, chunk_text)


def _build_visual_references(sources: list[str]) -> list[RetrievalVisualReference]:
    return build_visual_references(sources)


def _pick_preferred_entity_sentence(query: str, sentences: list[str]) -> str | None:
    return select_preferred_entity_sentence(query=query, sentences=sentences)


def _looks_like_acronym_expansion(acronym: str, phrase: str) -> bool:
    return is_acronym_expansion_phrase(acronym, phrase)


def _extract_acronym_expansion(acronym: str, texts: list[str]) -> str | None:
    return extract_acronym_expansion_text(acronym, texts)


def _is_subsequence(needle: str, haystack: str) -> bool:
    from app.retrieval.service.acronym import is_subsequence

    return is_subsequence(needle, haystack)


def _infer_acronym_expansion_from_texts(acronym: str, texts: list[str]) -> str | None:
    return infer_acronym_expansion(acronym, texts)


def _find_acronym_expansion_in_index(acronym: str, max_items: int = 220) -> tuple[str | None, list[str]]:
    return find_indexed_acronym_expansion(acronym, max_items=max_items)


def _preferred_source_contexts(query: str, sources: list[str], limit: int) -> list[dict[str, str]]:
    if not sources or limit <= 0:
        return []

    source_set = {source.strip() for source in sources if source.strip()}
    if not source_set:
        return []

    candidates: list[tuple[float, dict[str, str]]] = []
    for item in _load_local_index_items():
        source = str(item.get("source", "")).strip()
        text = str(item.get("text", "")).strip()
        if source not in source_set or not text:
            continue

        score = _keyword_relevance_score(query=query, source=source, text=text)
        score += _content_quality_score(text)
        candidates.append(
            (
                score,
                {
                    "source": Path(source).name or source,
                    "chunk_id": str(item.get("chunk_id", "")) or f"{Path(source).stem}-preferred",
                    "text": text,
                },
            )
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    used_sources_pref: set[str] = set()
    for _, context in candidates:
        key = (context["source"], context["chunk_id"])
        if key in seen or context["source"] in used_sources_pref:
            continue
        selected.append(context)
        seen.add(key)
        used_sources_pref.add(context["source"])
        if len(selected) >= limit:
            break
    return selected


def _promote_preferred_sources(
    contexts: list[dict[str, str]],
    preferred_sources: list[str],
    top_k: int,
) -> list[dict[str, str]]:
    if not contexts:
        return []

    preferred_set = {source.strip() for source in preferred_sources if source.strip()}
    unique_contexts: list[dict[str, str]] = []
    seen_chunks: set[tuple[str, str]] = set()
    for context in contexts:
        source = str(context.get("source", ""))
        chunk_id = str(context.get("chunk_id", ""))
        key = (source, chunk_id)
        if key in seen_chunks:
            continue
        seen_chunks.add(key)
        unique_contexts.append(context)

    if not preferred_set:
        return unique_contexts[:top_k]

    preferred: list[dict[str, str]] = []
    others: list[dict[str, str]] = []
    for context in unique_contexts:
        if str(context.get("source", "")) in preferred_set:
            preferred.append(context)
        else:
            others.append(context)

    selected: list[dict[str, str]] = []
    selected_keys: set[tuple[str, str]] = set()
    used_sources: set[str] = set()

    # First pass: maximize source diversity while preferring acronym-definition sources.
    for bucket in (preferred, others):
        for context in bucket:
            source = str(context.get("source", ""))
            key = (source, str(context.get("chunk_id", "")))
            if source in used_sources or key in selected_keys:
                continue
            selected.append(context)
            selected_keys.add(key)
            used_sources.add(source)
            if len(selected) >= top_k:
                return selected

    # Second pass: fill remaining slots by rank order.
    for context in preferred + others:
        source = str(context.get("source", ""))
        key = (source, str(context.get("chunk_id", "")))
        if key in selected_keys:
            continue
        selected.append(context)
        selected_keys.add(key)
        if len(selected) >= top_k:
            break

    return selected


# Domain seed dictionary: known acronyms in the aviation / travel-tech space that may not be
# spelled out explicitly in indexed material.  Keys are uppercase acronym strings.
def _domain_seed_expansion(acronym: str) -> str | None:
    return get_seed_acronym_expansion(acronym)


def _fallback_retrieval_answer(query: str, contexts: list[dict[str, str]]) -> tuple[str, float]:
    return compose_fallback_retrieval_answer(query=query, contexts=contexts)


def _synthesize_retrieval_answer(
    query: str,
    contexts: list[dict[str, str]],
    domain_context: str | None = None,
) -> dict[str, Any]:
    return compose_synthesized_retrieval_answer(
        query=query,
        contexts=contexts,
        domain_context=domain_context,
        settings_getter=get_settings,
    )


def _is_llm_answer_insufficient(answer: str, query: str) -> bool:
    return llm_answer_is_insufficient(answer=answer, query=query, settings_getter=get_settings)


@traceable(
    name="retrieval.search_material",
    run_type="chain",
    tags=["retrieval", "search", "orchestration"],
    metadata={"component": "retrieval", "stage": "search"},
)
def search_retrieval_material(
    query: str,
    domain_context: str | None = None,
    top_k: int = 6,
    orchestrator: str | None = None,
) -> RetrievalSearchResponse:
    settings = get_settings()
    orchestrator_name = choose_orchestrator(
        default_orchestrator=str(getattr(settings, "retrieval_orchestrator", "custom")).strip().lower(),
        requested_orchestrator=orchestrator,
    )
    query_clean = " ".join(query.split()).strip()
    query_id = MetricsCollector.create_query(query_clean)

    try:
        try:
            record_query_signature(query=query_clean, domain_context=domain_context)
        except Exception as exc:
            logger.debug("record_query_signature failed (non-critical): %s", exc)

        cached_response = get_cached_retrieval_search(
            query=query_clean,
            domain_context=domain_context,
            top_k=top_k,
            orchestrator=orchestrator_name,
        )
        if cached_response is not None and _cached_wiki_answer_is_valid(query_clean, cached_response):
            MetricsCollector.record_cache_hit(query_id, True, "L1/L2")
            cached_response["semantic_cache_hit"] = False
            cached_response["semantic_cache_score"] = 1.0
            cached_response["semantic_cache_kind"] = "exact"
            cached_response["semantic_cache_source"] = "retrieval-search-cache"
            if bool(getattr(settings, "semantic_cache_enabled", True)) and bool(
                getattr(settings, "semantic_cache_learn_from_runtime", True)
            ):
                try:
                    upsert_semantic_cache_entry(
                        query=query_clean,
                        domain_context=domain_context,
                        response_payload=cached_response,
                        source="runtime-search-exact-cache",
                        generated_by_model=str(cached_response.get("answer_model", "")),
                        kind="runtime",
                        score=float(cached_response.get("answer_confidence", 0.0) or 0.0),
                    )
                except Exception as exc:
                    logger.debug("semantic cache upsert (exact-cache path) failed (non-critical): %s", exc)
            return cached_response

        MetricsCollector.record_cache_hit(query_id, False)

        semantic_hit = None
        if bool(getattr(settings, "semantic_cache_enabled", True)):
            try:
                semantic_hit = find_semantic_cache_hit(query=query_clean, domain_context=domain_context)
            except Exception as e:
                logger.debug(f"Semantic cache lookup error (continuing): {e}")
                semantic_hit = None

            if semantic_hit is None:
                try:
                    similar_query_match = find_similar_query(query=query_clean, domain_context=domain_context)
                except Exception as exc:
                    logger.debug("similar query lookup failed (non-critical): %s", exc)
                    similar_query_match = None
                if similar_query_match is not None:
                    candidate_query = str(similar_query_match.get("query_norm") or "").strip()
                    if candidate_query:
                        try:
                            semantic_hit = find_semantic_cache_hit(query=candidate_query, domain_context=domain_context)
                        except Exception as exc:
                            logger.debug("semantic cache lookup (similar-query path) failed (non-critical): %s", exc)
                            semantic_hit = None
                        if semantic_hit is not None:
                            semantic_hit = dict(semantic_hit)
                            semantic_hit["source"] = f"{semantic_hit.get('source', 'semantic-cache')}|similar-query"
                            semantic_hit["similar_query"] = {
                                "query": str(similar_query_match.get("query", "")),
                                "query_norm": candidate_query,
                                "score": float(similar_query_match.get("score", 0.0) or 0.0),
                            }
    
        if semantic_hit is not None:
            semantic_payload = dict(semantic_hit.get("response", {}))
            if not _cached_wiki_answer_is_valid(query_clean, semantic_payload):
                semantic_hit = None

        if semantic_hit is not None:
            MetricsCollector.record_cache_hit(query_id, True, "L3")
            semantic_payload = dict(semantic_hit.get("response", {}))
            semantic_payload["query"] = query
            semantic_payload["retrieval_query"] = semantic_payload.get("retrieval_query") or query_clean
            semantic_payload["orchestrator"] = orchestrator_name
            semantic_payload["cached"] = True
            semantic_payload["cache_age_seconds"] = max(int(time.time()) - int(semantic_hit.get("created_at") or time.time()), 0)
            semantic_payload["semantic_cache_hit"] = True
            semantic_payload["semantic_cache_score"] = float(semantic_hit.get("score", 0.0) or 0.0)
            semantic_payload["semantic_cache_kind"] = str(semantic_hit.get("kind", "runtime"))
            semantic_payload["semantic_cache_source"] = str(semantic_hit.get("source", "semantic-cache"))
            similar_query_info = semantic_hit.get("similar_query")
            if isinstance(similar_query_info, dict):
                semantic_payload["similar_query"] = dict(similar_query_info)
            return semantic_payload

        normalized_query = normalize_training_question_query(query_clean)
        local_normalized = normalized_query.strip().lower() != query_clean.strip().lower()

        entity_style_query = is_entity_style_query(query_clean)
        rewrite_enabled = bool(getattr(settings, "enable_query_rewrite", True))

        plan = build_retrieval_plan(
            query_clean=query_clean,
            normalized_query=normalized_query,
            rewrite_enabled=rewrite_enabled,
            rewrite_func=rewrite_query_for_retrieval,
            domain_context=domain_context,
        )
        retrieval_query = plan["retrieval_query"]

        wiki_contexts: list[dict[str, str]] = []
        if bool(getattr(settings, "retrieval_wiki_first_enabled", True)):
            wiki_dir = Path(getattr(settings, "deploy_intel_wiki_dir", "") or "data/wiki")
            wiki_top_k = int(getattr(settings, "retrieval_wiki_top_k", max(top_k, 4)) or max(top_k, 4))
            wiki_contexts = _load_wiki_contexts(query=query_clean, wiki_dir=wiki_dir, top_k=wiki_top_k)
            min_wiki_score = float(getattr(settings, "retrieval_wiki_min_score", 1.4) or 1.4)
            wiki_answer_contexts = [context for context in wiki_contexts if _is_wiki_answer_context(context)]
            if wiki_answer_contexts:
                best_wiki_score = _keyword_relevance_score(
                    query=query_clean,
                    source=wiki_answer_contexts[0]["source"],
                    text=wiki_answer_contexts[0]["text"],
                ) + _content_quality_score(wiki_answer_contexts[0]["text"])
                if best_wiki_score >= min_wiki_score:
                    wiki_response = _wiki_response(
                        query=query,
                        retrieval_query=retrieval_query,
                        orchestrator_name=orchestrator_name,
                        contexts=wiki_answer_contexts[:top_k],
                        domain_context=domain_context,
                    )
                    set_cached_retrieval_search(
                        query=query_clean,
                        domain_context=domain_context,
                        top_k=top_k,
                        orchestrator=orchestrator_name,
                        payload=wiki_response,
                    )
                    if bool(getattr(settings, "semantic_cache_learn_from_runtime", True)):
                        try:
                            upsert_semantic_cache_entry(
                                query=query_clean,
                                domain_context=domain_context,
                                response_payload=wiki_response,
                                source="runtime-search-wiki",
                                generated_by_model=str(wiki_response.get("answer_model", "")),
                                kind="runtime",
                                score=float(wiki_response.get("answer_confidence", 0.0) or 0.0),
                            )
                        except Exception as exc:
                            logger.debug("semantic cache upsert (wiki path) failed (non-critical): %s", exc)
                    return wiki_response

        expanded_top_k = max(top_k * 8, 40)
        base_query = normalized_query if local_normalized else query_clean
        variants = query_variants(base_query, retrieval_query)

        original_contexts: list[dict[str, str]] = []
        rewritten_contexts: list[dict[str, str]] = []
        preferred_sources: list[str] = []
        for index, variant in enumerate(variants):
            if orchestrator_name == "llamaindex":
                contexts = retrieve_context_with_llamaindex(variant, top_k=expanded_top_k)
                if not contexts:
                    contexts = retrieve_context(variant, top_k=expanded_top_k)
            else:
                contexts = retrieve_context(variant, top_k=expanded_top_k)
            if index == 0:
                original_contexts = contexts
            else:
                rewritten_contexts.extend(contexts)

        acronym_candidates = _extract_acronym_candidates(query_clean)
        if entity_style_query and acronym_candidates:
            for acronym in acronym_candidates[:2]:
                _, sources = _find_acronym_expansion_in_index(acronym)
                for source in sources:
                    if source not in preferred_sources:
                        preferred_sources.append(source)
            if preferred_sources:
                boosted_contexts = _preferred_source_contexts(query=query_clean, sources=preferred_sources, limit=max(top_k, 2))
                if boosted_contexts:
                    original_contexts = boosted_contexts + original_contexts

        contexts = _merge_and_rank_contexts(
            query=query,
            original_contexts=original_contexts,
            rewritten_contexts=rewritten_contexts,
            top_k=top_k,
        )
        if entity_style_query and preferred_sources:
            contexts = _promote_preferred_sources(contexts=contexts, preferred_sources=preferred_sources, top_k=top_k)

        llm_payload = _synthesize_retrieval_answer(
            query=query_clean,
            contexts=contexts,
            domain_context=domain_context,
        )

        retrieval_answer, retrieval_confidence = _fallback_retrieval_answer(query=query_clean, contexts=contexts)
        retrieval_payload = {
            "answer": retrieval_answer,
            "answer_confidence": retrieval_confidence,
            "answer_confidence_source": "retrieval-rule-based",
            "answer_model": "retrieval-based",
            "answer_path": "retrieval-rule-based",
        }

        llm_available = llm_payload.get("answer_path") == "llm"
        llm_answer = str(llm_payload.get("answer", "")).strip() if llm_available else ""

        llm_answer_insufficient_flag = (
            not llm_available or _is_llm_answer_insufficient(llm_answer, query_clean)
        )
        final_answer_payload, fallback_reason = select_final_answer_payload(
            llm_payload=llm_payload,
            retrieval_payload=retrieval_payload,
            llm_answer_insufficient=llm_answer_insufficient_flag,
        )

        citations: list[RetrievalCitation] = [
            {
                "source": context["source"],
                "chunk_id": context["chunk_id"],
            }
            for context in contexts[:4]
        ]
        visual_references = _build_visual_references([context["source"] for context in contexts])
        results: list[RetrievalResultItem] = []
        for context in contexts:
            page_image: str = ""
            if context.get("source", "").endswith(".pdf"):
                img_path = render_chunk_page_image(
                    source=str(context["source"]),
                    chunk_text=str(context.get("text", "")),
                )
                if img_path:
                    page_image = f"/visual-previews/{quote(img_path.name)}"
            results.append(
                {
                    "source": context["source"],
                    "chunk_id": context["chunk_id"],
                    "excerpt": _trim_excerpt(context["text"], limit=320),
                    "page_image_url": page_image,
                }
            )

        response: RetrievalSearchResponse = {
            "query": query,
            "retrieval_query": retrieval_query,
            "orchestrator": orchestrator_name,
            "answer": final_answer_payload["answer"],
            "answer_confidence": final_answer_payload["answer_confidence"],
            "answer_confidence_source": final_answer_payload.get("answer_confidence_source", "unknown"),
            "answer_model": final_answer_payload["answer_model"],
            "answer_path": final_answer_payload.get("answer_path", "unknown"),
            "llm_answer": llm_answer,
            "llm_answer_confidence": llm_payload.get("answer_confidence", 0.0) if llm_available else 0.0,
            "llm_answer_confidence_source": llm_payload.get("answer_confidence_source", "none") if llm_available else "none",
            "llm_answer_model": llm_payload.get("answer_model", "") if llm_available else "",
            "retrieval_answer": retrieval_payload["answer"],
            "retrieval_answer_confidence": retrieval_payload["answer_confidence"],
            "retrieval_answer_confidence_source": retrieval_payload.get("answer_confidence_source", "retrieval-rule-based"),
            "retrieval_answer_model": retrieval_payload["answer_model"],
            "fallback_used": bool(fallback_reason),
            "fallback_reason": fallback_reason,
            "citations": citations,
            "visual_references": visual_references,
            "result_count": len(contexts),
            "results": results,
            "cached": False,
            "cache_age_seconds": 0,
            "semantic_cache_hit": False,
            "semantic_cache_score": 0.0,
            "semantic_cache_kind": "none",
            "semantic_cache_source": "none",
        }

        set_cached_retrieval_search(
            query=query_clean,
            domain_context=domain_context,
            top_k=top_k,
            orchestrator=orchestrator_name,
            payload=response,
        )

        if bool(getattr(settings, "semantic_cache_learn_from_runtime", True)):
            try:
                upsert_semantic_cache_entry(
                    query=query_clean,
                    domain_context=domain_context,
                    response_payload=response,
                    source="runtime-search",
                    generated_by_model=str(final_answer_payload.get("answer_model", "")),
                    kind="runtime",
                    score=float(final_answer_payload.get("answer_confidence", 0.0) or 0.0),
                )
            except Exception as exc:
                logger.debug("semantic cache upsert (final response) failed (non-critical): %s", exc)

        return response
    finally:
        MetricsCollector.finalize(query_id)


def get_retrieval_overview() -> dict[str, Any]:
    return build_retrieval_overview(
        ingestion_report_getter=get_last_ingestion_report,
        index_loader=_load_local_index_items,
    )
