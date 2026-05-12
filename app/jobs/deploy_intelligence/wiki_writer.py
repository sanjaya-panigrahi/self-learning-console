"""Wiki layer: writes interlinked markdown pages from deploy-intelligence knowledge cards.

Directory layout written under *wiki_dir* (default ``data/wiki/``):

    data/wiki/
        index.md            ← catalog of all source pages, entity pages, and concept pages
        log.md              ← append-only operation log
        .manifest.json      ← incremental-build hash manifest (mtime + hash per source)
        sources/            ← one page per ingested document
            <slug>.md
        entities/           ← one page per named entity appearing in ≥ min_docs documents
            <slug>.md
        concepts/           ← one page per thematic concept appearing in ≥ min_docs documents
            <slug>.md
        answers/            ← filed Q&A answers (from chat or admin endpoint)
            <slug>.md
"""
from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import tempfile

from app.core.config.settings import get_settings

_REVIEW_ALLOWED = {"draft", "reviewed", "approved"}


def _allowed_update_triggers() -> set[str]:
    settings = get_settings()
    raw = str(getattr(settings, "wiki_allowed_update_triggers", "") or "")
    tokens = {token.strip().lower() for token in raw.split(",") if token.strip()}
    return tokens or {"deploy-intelligence", "feedback-auto-helpful", "admin-api"}


def _enforce_wiki_update_trigger(trigger: str) -> str:
    settings = get_settings()
    cleaned = str(trigger or "").strip().lower()
    if bool(getattr(settings, "wiki_learning_requires_explicit_trigger", True)) and not cleaned:
        raise ValueError("Wiki update requires an explicit trigger")

    allowed = _allowed_update_triggers()
    if cleaned not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise PermissionError(f"Wiki update trigger '{cleaned or 'none'}' is not allowed; allowed: {allowed_text}")
    return cleaned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Return a safe filesystem slug from *name*."""
    name = re.sub(r"[^\w\s-]", "", name.lower())
    name = re.sub(r"[\s_-]+", "-", name).strip("-")
    return name or "unknown"


def _now_str() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, dir=path.parent, delete=False, suffix=".tmp") as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "_None_"
    return "\n".join(f"- {item}" for item in items)


def _source_page_slug(card: dict[str, Any]) -> str:
    """Return the canonical slug used for a source page from a knowledge card."""
    title = str(card.get("title") or Path(str(card.get("source", "unknown"))).stem)
    return _slug(title)


def _source_reference_slug(source_ref: str) -> str:
    """Return best-effort source slug from a source reference path/name."""
    return _slug(Path(str(source_ref)).stem)


_QUESTION_STOPWORDS = {
    "what",
    "which",
    "when",
    "where",
    "who",
    "why",
    "how",
    "is",
    "are",
    "was",
    "were",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "on",
    "and",
    "or",
    "please",
    "tell",
    "me",
    "about",
    "can",
    "you",
    "explain",
    "could",
    "would",
}

_QUESTION_EQUIVALENT_TERMS = {
    "irop": "irregular operations",
    "irops": "irregular operations",
    "irrops": "irregular operations",
}


def _normalize_question_text(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = re.sub(r"[?!.:,;()\[\]{}]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return ""

    parts: list[str] = []
    for token in normalized.split():
        expanded = _QUESTION_EQUIVALENT_TERMS.get(token, token)
        parts.extend(expanded.split())
    return " ".join(parts)


def _question_tokens(text: str) -> set[str]:
    normalized = _normalize_question_text(text)
    tokens = {tok for tok in normalized.split() if tok and tok not in _QUESTION_STOPWORDS}
    return tokens


def _question_similarity(a: str, b: str) -> float:
    a_norm = _normalize_question_text(a)
    b_norm = _normalize_question_text(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0

    a_tokens = _question_tokens(a_norm)
    b_tokens = _question_tokens(b_norm)
    jaccard = 0.0
    if a_tokens and b_tokens:
        intersection = len(a_tokens & b_tokens)
        union = len(a_tokens | b_tokens)
        jaccard = (intersection / union) if union else 0.0

    seq = SequenceMatcher(None, a_norm, b_norm).ratio()
    containment = 1.0 if (a_norm in b_norm or b_norm in a_norm) else 0.0
    return max(jaccard, seq, containment)


def _extract_markdown_question(path: Path) -> str:
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[:1]
    except OSError:
        return ""
    if not first_line:
        return ""
    line = first_line[0].strip()
    if line.lower().startswith("# q:"):
        return line[4:].strip()
    return ""


def _find_equivalent_answer_page(question: str, answers_dir: Path) -> Path | None:
    if not answers_dir.exists():
        return None

    best_path: Path | None = None
    best_score = 0.0
    for candidate in answers_dir.glob("*.md"):
        existing_question = _extract_markdown_question(candidate)
        if not existing_question:
            continue
        score = _question_similarity(question, existing_question)
        if score > best_score:
            best_score = score
            best_path = candidate

    return best_path if best_score >= 0.88 else None


def _extract_section(content: str, heading: str) -> str:
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(heading)}\n\n(.*?)(?=\n##\s+|\n---\n|\Z)")
    match = pattern.search(content)
    return match.group(1).strip() if match else ""


def _replace_or_insert_section(content: str, heading: str, body: str, *, before_delimiter: str = "\n---\n") -> str:
    section_block = f"## {heading}\n\n{body.strip()}\n\n"
    pattern = re.compile(rf"(?ms)^##\s+{re.escape(heading)}\n\n.*?(?=\n##\s+|\n---\n|\Z)")
    if pattern.search(content):
        return pattern.sub(section_block.rstrip("\n"), content, count=1)

    insert_at = content.find(before_delimiter)
    if insert_at == -1:
        if not content.endswith("\n"):
            content += "\n"
        return content + "\n" + section_block
    return content[:insert_at] + "\n" + section_block + content[insert_at:]


def _merge_answer_page(
    *,
    page_path: Path,
    incoming_question: str,
    incoming_answer: str,
    incoming_sources: list[str],
) -> None:
    content = page_path.read_text(encoding="utf-8")

    # Maintain a canonical list of alternate phrasings for the same concept.
    canonical_question = _extract_markdown_question(page_path)
    alt_questions_raw = _extract_section(content, "Alternate Questions")
    alt_questions = [line[2:].strip() for line in alt_questions_raw.splitlines() if line.strip().startswith("- ")]
    for q in [canonical_question, incoming_question]:
        cleaned = str(q or "").strip()
        if cleaned and all(_normalize_question_text(cleaned) != _normalize_question_text(existing) for existing in alt_questions):
            alt_questions.append(cleaned)
    if alt_questions:
        content = _replace_or_insert_section(content, "Alternate Questions", "\n".join(f"- {q}" for q in alt_questions))

    # Merge sources without duplication.
    existing_sources_raw = _extract_section(content, "Sources")
    existing_sources = [line.strip() for line in existing_sources_raw.splitlines() if line.strip().startswith("- ")]
    for source in incoming_sources:
        source_slug = _source_reference_slug(source)
        source_line = f"- [{source}](../sources/{source_slug}.md)"
        if source_line not in existing_sources:
            existing_sources.append(source_line)
    if existing_sources:
        content = _replace_or_insert_section(content, "Sources", "\n".join(existing_sources))

    # Consolidate and enrich answer content from equivalent questions.
    incoming_answer_clean = str(incoming_answer or "").strip()
    if incoming_answer_clean:
        answer_section = _extract_section(content, "Answer")
        answer_normalized = _normalize_question_text(answer_section)
        incoming_normalized = _normalize_question_text(incoming_answer_clean)
        
        # If incoming answer is substantially different and not already in the answer section
        if incoming_normalized and incoming_normalized not in answer_normalized:
            # If incoming answer is longer/more detailed, use it as main answer
            if len(incoming_answer_clean) > len(answer_section):
                content = _replace_or_insert_section(content, "Answer", incoming_answer_clean)
            else:
                # Otherwise append to answer section for multi-perspective clarity
                enriched_answer = answer_section.rstrip() + "\n\n" + incoming_answer_clean
                content = _replace_or_insert_section(content, "Answer", enriched_answer)

    page_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Source-document page
# ---------------------------------------------------------------------------

def write_source_page(card: dict[str, Any], sources_dir: Path) -> Path:
    """Write a markdown page for *card* under *sources_dir*. Returns the path."""
    title = str(card.get("title") or Path(str(card.get("source", "unknown"))).stem)
    slug = _source_page_slug(card)
    dest = sources_dir / f"{slug}.md"

    entities: list[str] = [str(e) for e in card.get("entities", []) if str(e).strip()]
    entity_links: list[str] = []
    for e in entities:
        e_slug = _slug(e)
        entity_links.append(f"[{e}](../entities/{e_slug}.md)")

    lines = [
        f"# {title}",
        "",
        f"> **Source file:** `{card.get('source', '')}`  ",
        f"> **Chunks indexed:** {card.get('chunk_count', '?')}  ",
        f"> **Generated:** {_now_str()}",
        "",
        "## Summary",
        "",
        str(card.get("summary") or "_No summary generated._"),
        "",
        "## Key Points",
        "",
        _bullet_list([str(p) for p in card.get("key_points", []) if str(p).strip()]),
        "",
    ]

    if entity_links:
        lines += [
            "## Entities",
            "",
            ", ".join(entity_links),
            "",
        ]

    policy_flags = [str(f) for f in card.get("policy_flags", []) if str(f).strip()]
    if policy_flags:
        lines += [
            "## Policy Flags",
            "",
            _bullet_list(policy_flags),
            "",
        ]

    expected_q = [str(q) for q in card.get("expected_questions", []) if str(q).strip()]
    if expected_q:
        lines += [
            "## Sample Questions",
            "",
            _bullet_list(expected_q[:10]),
            "",
        ]

    lines += [
        "---",
        "",
        "[← Back to Index](../index.md)",
    ]

    sources_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Entity pages
# ---------------------------------------------------------------------------

def _build_entity_map(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map each entity name → list of cards in which it appears.

    Variants of the same entity that differ only in case, hyphens, or underscores
    are merged under the most frequently occurring raw form (canonical name).
    """
    def _norm(name: str) -> str:
        return re.sub(r"[-_]", " ", name.lower()).strip()

    # norm_key → { "name_counts": {raw: count}, "cards": [card, ...] }
    grouped: dict[str, dict] = {}
    for card in cards:
        seen_norms: set[str] = set()
        for e in card.get("entities", []):
            name = str(e).strip()
            if not name:
                continue
            key = _norm(name)
            if key in seen_norms:
                continue  # avoid counting the same card twice for the same entity
            seen_norms.add(key)
            if key not in grouped:
                grouped[key] = {"name_counts": defaultdict(int), "cards": []}
            grouped[key]["name_counts"][name] += 1
            grouped[key]["cards"].append(card)

    entity_map: dict[str, list[dict[str, Any]]] = {}
    for key, data in grouped.items():
        canonical = max(data["name_counts"], key=lambda n: data["name_counts"][n])
        entity_map[canonical] = data["cards"]

    return entity_map


def write_entity_pages(
    cards: list[dict[str, Any]],
    entities_dir: Path,
    min_docs: int = 2,
) -> list[str]:
    """Write entity pages for entities appearing in ≥ *min_docs* documents.

    Returns the list of entity names that got pages.
    """
    entity_map = _build_entity_map(cards)
    written: list[str] = []

    entities_dir.mkdir(parents=True, exist_ok=True)
    for entity, entity_cards in sorted(entity_map.items()):
        if len(entity_cards) < min_docs:
            continue

        slug = _slug(entity)
        dest = entities_dir / f"{slug}.md"

        doc_links: list[str] = []
        for c in entity_cards:
            t = str(c.get("title") or Path(str(c.get("source", "unknown"))).stem)
            doc_links.append(f"[{t}](../sources/{_slug(t)}.md)")

        lines = [
            f"# {entity}",
            "",
            f"> Appears in **{len(entity_cards)}** document(s).  ",
            f"> Generated: {_now_str()}",
            "",
            "## Documents",
            "",
        ]
        for link in doc_links:
            lines.append(f"- {link}")

        # Collect all summaries mentioning this entity for context
        excerpts: list[str] = []
        entity_normalized = re.sub(r"[-_]", " ", entity.lower()).strip()
        for c in entity_cards:
            summary = str(c.get("summary", "")).strip()
            summary_lower = summary.lower()
            in_summary = entity_normalized in summary_lower
            if not in_summary:
                # also check individual key_points for a mention
                for kp in c.get("key_points", []):
                    if entity_normalized in str(kp).lower():
                        in_summary = True
                        break
            if in_summary and summary:
                excerpts.append(f"> *{str(c.get('title', 'Unknown'))}* — {summary[:300].strip()}…")

        if excerpts:
            lines += [
                "",
                "## Context",
                "",
            ]
            lines += excerpts

        lines += [
            "",
            "---",
            "",
            "[← Back to Index](../index.md)",
        ]

        dest.write_text("\n".join(lines), encoding="utf-8")
        written.append(entity)

    return written


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Concept pages
# ---------------------------------------------------------------------------

def _build_concept_map(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Map each concept name → list of cards in which it appears.

    Uses the ``concepts`` field if present; falls back to extracting multi-word
    phrases from ``key_points`` that are longer than one word.
    """
    concept_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        # Prefer explicit concept field from knowledge card
        concepts = [str(c).strip() for c in card.get("concepts", []) if str(c).strip()]
        if not concepts:
            # Fallback: use short key_point phrases as pseudo-concepts
            for kp in card.get("key_points", []):
                text = str(kp).strip()
                # Use leading noun-phrase-like segment (first 4 words, if multi-word)
                words = text.split()
                if len(words) >= 3:
                    phrase = " ".join(words[:4]).rstrip(".,;:")
                    if len(phrase) > 10:
                        concepts.append(phrase)
        seen_in_card: set[str] = set()
        for c in concepts:
            key = c.lower()
            if key not in seen_in_card:
                concept_map[c].append(card)
                seen_in_card.add(key)
    return dict(concept_map)


def write_concept_pages(
    cards: list[dict[str, Any]],
    concepts_dir: Path,
    min_docs: int = 2,
) -> list[str]:
    """Write concept pages for concepts appearing in ≥ *min_docs* documents.

    Concept pages are distinct from entity pages — they cover thematic topics
    (capabilities, workflows, processes) rather than named entities.

    Returns the list of concept names that got pages.
    """
    concept_map = _build_concept_map(cards)
    written: list[str] = []

    concepts_dir.mkdir(parents=True, exist_ok=True)
    for concept, concept_cards in sorted(concept_map.items()):
        if len(concept_cards) < min_docs:
            continue
        # Skip if this concept looks like it duplicates an entity (exact title match)
        # to avoid redundancy — entities are handled separately
        slug = _slug(concept)
        dest = concepts_dir / f"{slug}.md"

        doc_links: list[str] = []
        for c in concept_cards:
            t = str(c.get("title") or Path(str(c.get("source", "unknown"))).stem)
            doc_links.append(f"[{t}](../sources/{_slug(t)}.md)")

        # Collect relevant key_points from each mentioning card
        excerpts: list[str] = []
        for c in concept_cards:
            for kp in c.get("key_points", []):
                kp_text = str(kp).strip()
                if concept.lower() in kp_text.lower() and kp_text:
                    title = str(c.get("title", "Unknown"))
                    excerpts.append(f"> *{title}* — {kp_text}")
                    break  # one excerpt per document

        lines = [
            f"# Concept: {concept}",
            "",
            f"> Appears in **{len(concept_cards)}** document(s).  ",
            f"> Generated: {_now_str()}",
            "",
            "## Documents",
            "",
        ]
        for link in doc_links:
            lines.append(f"- {link}")

        if excerpts:
            lines += [
                "",
                "## Key Points Mentioning This Concept",
                "",
            ]
            lines += excerpts

        lines += [
            "",
            "---",
            "",
            "[← Back to Index](../index.md)",
        ]

        dest.write_text("\n".join(lines), encoding="utf-8")
        written.append(concept)

    return written


# ---------------------------------------------------------------------------
# Incremental manifest
# ---------------------------------------------------------------------------

def _source_hash(source_path: str) -> str:
    """Return a fingerprint for *source_path* based on mtime and size.

    If the file does not exist on disk (path stored in Qdrant but not local),
    returns the empty string so the source page is always regenerated.
    """
    try:
        stat = os.stat(source_path)
        raw = f"{stat.st_mtime_ns}-{stat.st_size}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]
    except OSError:
        return ""


def _manifest_path(wiki_dir: Path) -> Path:
    return wiki_dir / ".manifest.json"


def _load_manifest(wiki_dir: Path) -> dict[str, str]:
    mp = _manifest_path(wiki_dir)
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_manifest(wiki_dir: Path, manifest: dict[str, str]) -> None:
    wiki_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(_manifest_path(wiki_dir), json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Editorial review state
# ---------------------------------------------------------------------------

def _review_state_path(wiki_dir: Path) -> Path:
    return wiki_dir / "review_state.json"


def _load_review_state(wiki_dir: Path) -> dict[str, Any]:
    path = _review_state_path(wiki_dir)
    if not path.exists():
        return {"pages": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"pages": {}}
        pages = raw.get("pages", {})
        if not isinstance(pages, dict):
            pages = {}
        return {"pages": pages}
    except (json.JSONDecodeError, OSError):
        return {"pages": {}}


def _save_review_state(wiki_dir: Path, state: dict[str, Any]) -> None:
    wiki_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(_review_state_path(wiki_dir), json.dumps(state, indent=2))


def set_page_review_status(
    wiki_dir: Path,
    page_rel_path: str,
    status: str,
    *,
    reviewer: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Set review status for a wiki page and persist review_state.json."""
    status_clean = str(status).strip().lower()
    if status_clean not in _REVIEW_ALLOWED:
        raise ValueError(f"Invalid review status: {status_clean}")

    state = _load_review_state(wiki_dir)
    pages = state.setdefault("pages", {})
    existing = pages.get(page_rel_path, {}) if isinstance(pages.get(page_rel_path), dict) else {}

    entry = {
        "status": status_clean,
        "updated_at": _now_str(),
        "reviewer": reviewer or existing.get("reviewer"),
        "notes": notes if notes is not None else existing.get("notes", ""),
    }
    pages[page_rel_path] = entry
    _save_review_state(wiki_dir, state)
    return entry


def get_page_review_status(wiki_dir: Path, page_rel_path: str) -> dict[str, Any]:
    """Get review metadata for a wiki page, defaulting to draft if unknown."""
    state = _load_review_state(wiki_dir)
    pages = state.get("pages", {})
    if not isinstance(pages, dict):
        pages = {}
    entry = pages.get(page_rel_path)
    if isinstance(entry, dict):
        return {
            "status": str(entry.get("status", "draft")),
            "updated_at": str(entry.get("updated_at", "")),
            "reviewer": str(entry.get("reviewer", "") or ""),
            "notes": str(entry.get("notes", "") or ""),
        }
    return {"status": "draft", "updated_at": "", "reviewer": "", "notes": ""}


def get_review_summary(wiki_dir: Path) -> dict[str, int]:
    """Return aggregate counts by review status across all tracked pages."""
    state = _load_review_state(wiki_dir)
    pages = state.get("pages", {})
    draft = reviewed = approved = 0
    if isinstance(pages, dict):
        for entry in pages.values():
            if not isinstance(entry, dict):
                draft += 1
                continue
            status = str(entry.get("status", "draft")).lower()
            if status == "approved":
                approved += 1
            elif status == "reviewed":
                reviewed += 1
            else:
                draft += 1
    return {
        "total": draft + reviewed + approved,
        "draft": draft,
        "reviewed": reviewed,
        "approved": approved,
    }


# ---------------------------------------------------------------------------
# Source-change impact report
# ---------------------------------------------------------------------------

def write_impact_report(
    wiki_dir: Path,
    *,
    changed_sources: list[str],
    unchanged_sources: list[str],
    deleted_sources: list[str],
    affected_entities: list[str],
    affected_concepts: list[str],
) -> Path:
    """Write an impact report describing which wiki pages are affected by source changes."""
    impact_path = wiki_dir / "impact_report.json"
    source_pages = [f"sources/{_slug(Path(s).stem)}.md" for s in changed_sources]
    entity_pages = [f"entities/{_slug(e)}.md" for e in affected_entities]
    concept_pages = [f"concepts/{_slug(c)}.md" for c in affected_concepts]
    deleted_source_pages = [f"sources/{_slug(Path(s).stem)}.md" for s in deleted_sources]

    payload = {
        "generated_at": int(time.time()),
        "generated_at_readable": _now_str(),
        "changed_sources": sorted(changed_sources),
        "unchanged_sources": sorted(unchanged_sources),
        "deleted_sources": sorted(deleted_sources),
        "counts": {
            "changed_sources": len(changed_sources),
            "unchanged_sources": len(unchanged_sources),
            "deleted_sources": len(deleted_sources),
            "affected_entities": len(affected_entities),
            "affected_concepts": len(affected_concepts),
        },
        "affected": {
            "source_pages": sorted(source_pages),
            "deleted_source_pages": sorted(deleted_source_pages),
            "entity_pages": sorted(entity_pages),
            "concept_pages": sorted(concept_pages),
        },
    }

    wiki_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(impact_path, json.dumps(payload, indent=2))
    append_wiki_log(
        f"Impact report updated — {len(changed_sources)} changed, "
        f"{len(deleted_sources)} deleted, {len(affected_entities)} entity pages, "
        f"{len(affected_concepts)} concept pages affected",
        wiki_dir,
    )
    return impact_path


def write_wiki_index(
    cards: list[dict[str, Any]],
    entity_names: list[str],
    wiki_dir: Path,
) -> Path:
    """Regenerate ``wiki_dir/index.md`` with links to all source, entity, and concept pages."""
    dest = wiki_dir / "index.md"

    lines = [
        "# Knowledge Wiki — Index",
        "",
        f"_Last updated: {_now_str()}_  ",
        f"_{len(cards)} source document(s) · {len(entity_names)} entity/concept page(s)_",
        "",
        "---",
        "",
        f"## Documents ({len(cards)})",
        "",
        "| Document | Entities | Key Points |",
        "| --- | --- | --- |",
    ]

    for card in sorted(cards, key=lambda c: str(c.get("title", "")).lower()):
        title = str(card.get("title") or Path(str(card.get("source", "unknown"))).stem)
        slug = _slug(title)
        entities = [str(e).strip() for e in card.get("entities", []) if str(e).strip()]
        entity_badges = " · ".join(entities[:5])
        kp_count = len(card.get("key_points", []))
        lines.append(f"| [{title}](sources/{slug}.md) | {entity_badges or '—'} | {kp_count} |")

    if entity_names:
        lines += [
            "",
            f"## Entities ({len(entity_names)})",
            "",
        ]
        for e in sorted(entity_names):
            lines.append(f"- [{e}](entities/{_slug(e)}.md)")

    # Concept pages
    concepts_dir = wiki_dir / "concepts"
    if concepts_dir.exists():
        concept_slugs = sorted(p.stem for p in concepts_dir.glob("*.md"))
        if concept_slugs:
            lines += [
                "",
                f"## Concepts ({len(concept_slugs)})",
                "",
            ]
            for slug in concept_slugs:
                display = slug.replace("-", " ").title()
                lines.append(f"- [{display}](concepts/{slug}.md)")

    # Answer pages
    answers_dir = wiki_dir / "answers"
    if answers_dir.exists():
        answer_slugs = sorted((p.stem for p in answers_dir.glob("*.md")), reverse=True)
        if answer_slugs:
            lines += [
                "",
                f"## Filed Answers ({len(answer_slugs)})",
                "",
            ]
            for slug in answer_slugs[:20]:
                display = slug.replace("-", " ")
                lines.append(f"- [{display}](answers/{slug}.md)")

    lines += ["", "---", "", "_Auto-generated by deploy-intelligence pipeline._"]

    wiki_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Answer filing
# ---------------------------------------------------------------------------

def write_answer_page(
    question: str,
    answer: str,
    wiki_dir: Path,
    *,
    confidence: float = 0.0,
    sources: list[str] | None = None,
    session_id: str | None = None,
    filed_by: str = "admin",
    trigger: str = "admin-api",
) -> Path:
    """Persist a Q&A pair as a markdown page under ``wiki_dir/answers/``.

    Returns the path of the written file.
    """
    trigger_name = _enforce_wiki_update_trigger(trigger)
    settings = get_settings()

    normalized_sources = [str(item).strip() for item in (sources or []) if str(item).strip()]
    if bool(getattr(settings, "wiki_require_sources_for_answer_pages", True)) and not normalized_sources:
        raise ValueError("Answer pages require at least one source reference")

    if filed_by == "auto-helpful" and bool(getattr(settings, "wiki_enforce_feedback_confidence", True)):
        min_confidence = float(getattr(settings, "wiki_auto_file_min_confidence", 0.8) or 0.8)
        if float(confidence or 0.0) < min_confidence:
            raise ValueError(
                f"Auto-helpful filing requires confidence >= {min_confidence:.2f}"
            )

    answers_dir = wiki_dir / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)

    equivalent_page = _find_equivalent_answer_page(question, answers_dir)
    if equivalent_page is not None:
        _merge_answer_page(
            page_path=equivalent_page,
            incoming_question=question,
            incoming_answer=answer,
            incoming_sources=normalized_sources,
        )
        append_wiki_log(
            f"Answer merged into `{equivalent_page.name}` (question matched semantically, by {filed_by}, trigger {trigger_name})",
            wiki_dir,
        )
        return equivalent_page

    slug = _slug(question[:80])
    # Avoid overwriting if a page with same slug already exists — append timestamp
    dest = answers_dir / f"{slug}.md"
    if dest.exists():
        ts_suffix = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        dest = answers_dir / f"{slug}-{ts_suffix}.md"

    source_links: list[str] = []
    for s in normalized_sources:
        s = str(s).strip()
        if s:
            source_slug = _source_reference_slug(s)
            source_links.append(f"[{s}](../sources/{source_slug}.md)")

    truth_basis = "approved_feedback" if filed_by == "auto-helpful" else "source_cited_entry"

    lines = [
        f"# Q: {question.strip()}",
        "",
        f"> **Filed:** {_now_str()}  ",
        f"> **Confidence:** {round(confidence * 100)}%  ",
        f"> **Filed by:** {filed_by}  ",
        f"> **Trigger:** {trigger_name}  ",
        f"> **Truth basis:** {truth_basis}",
    ]

    if session_id:
        lines.append(f"> **Session:** `{session_id}`")

    lines += [
        "",
        "## Answer",
        "",
        answer.strip(),
        "",
    ]

    if source_links:
        lines += [
            "## Sources",
            "",
            "\n".join(f"- {link}" for link in source_links),
            "",
        ]

    lines += [
        "---",
        "",
        "[← Back to Index](../index.md)",
    ]

    dest.write_text("\n".join(lines), encoding="utf-8")
    append_wiki_log(
        f"Answer filed: `{dest.name}` (confidence {round(confidence * 100)}%, by {filed_by}, trigger {trigger_name})",
        wiki_dir,
    )
    return dest


# ---------------------------------------------------------------------------
# Operation log
# ---------------------------------------------------------------------------

def append_wiki_log(event: str, wiki_dir: Path) -> None:
    """Append one line to the append-only ``wiki_dir/log.md``."""
    log_path = wiki_dir / "log.md"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    if not log_path.exists():
        log_path.write_text("# Wiki Operation Log\n\n", encoding="utf-8")

    ts = _now_str()
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"- `{ts}` — {event}\n")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_wiki_generation(
    knowledge_cards: list[dict[str, Any]],
    wiki_dir: Path,
    min_entity_docs: int = 2,
    *,
    trigger: str = "deploy-intelligence",
) -> dict[str, Any]:
    """Generate all wiki pages from *knowledge_cards* using the incremental manifest.

    Only regenerates source pages for documents whose content has changed since the
    last run (based on mtime + content hash). Returns a summary dict with counts.
    """
    trigger_name = _enforce_wiki_update_trigger(trigger)
    started = time.time()
    sources_dir = wiki_dir / "sources"
    entities_dir = wiki_dir / "entities"
    concepts_dir = wiki_dir / "concepts"

    append_wiki_log(
        f"Wiki generation started — {len(knowledge_cards)} knowledge card(s), trigger {trigger_name}",
        wiki_dir,
    )

    # 0. Load manifest for incremental builds
    manifest = _load_manifest(wiki_dir)
    new_manifest: dict[str, str] = {}

    # 1. Source pages (skip unchanged documents)
    source_pages: list[str] = []
    changed_source_paths: list[str] = []
    changed_cards: list[dict[str, Any]] = []
    unchanged_source_paths: list[str] = []
    skipped_unchanged = 0
    for card in knowledge_cards:
        try:
            source_path = str(card.get("source", ""))
            current_hash = _source_hash(source_path)
            new_manifest[source_path] = current_hash
            if manifest.get(source_path) == current_hash and (sources_dir / f"{_source_page_slug(card)}.md").exists():
                # Unchanged — skip regeneration
                title = str(card.get("title") or Path(source_path).stem)
                source_pages.append(f"{_slug(title)}.md")
                unchanged_source_paths.append(source_path)
                skipped_unchanged += 1
                continue
            p = write_source_page(card, sources_dir)
            source_pages.append(p.name)
            changed_source_paths.append(source_path)
            changed_cards.append(card)
            set_page_review_status(
                wiki_dir,
                f"sources/{p.name}",
                "draft",
                reviewer="system",
                notes="Auto-updated by deploy-intelligence due to source change.",
            )
        except Exception as exc:  # pragma: no cover
            append_wiki_log(
                f"ERROR writing source page for `{card.get('source', '?')}`: {exc}",
                wiki_dir,
            )

    # 2. Entity pages
    entity_names: list[str] = []
    try:
        entity_names = write_entity_pages(knowledge_cards, entities_dir, min_docs=min_entity_docs)
        if changed_cards:
            affected_entities = {
                str(e).strip()
                for c in changed_cards
                for e in c.get("entities", [])
                if str(e).strip()
            }
            for entity in sorted(affected_entities):
                entity_page = f"entities/{_slug(entity)}.md"
                if (wiki_dir / entity_page).exists():
                    set_page_review_status(
                        wiki_dir,
                        entity_page,
                        "draft",
                        reviewer="system",
                        notes="Affected by source update; review synthesized cross-document context.",
                    )
    except Exception as exc:  # pragma: no cover
        append_wiki_log(f"ERROR writing entity pages: {exc}", wiki_dir)

    # 3. Concept pages
    concept_names: list[str] = []
    try:
        concept_names = write_concept_pages(knowledge_cards, concepts_dir, min_docs=min_entity_docs)
        if changed_cards:
            affected_concepts = {
                str(c).strip()
                for card in changed_cards
                for c in card.get("concepts", [])
                if str(c).strip()
            }
            for concept in sorted(affected_concepts):
                concept_page = f"concepts/{_slug(concept)}.md"
                if (wiki_dir / concept_page).exists():
                    set_page_review_status(
                        wiki_dir,
                        concept_page,
                        "draft",
                        reviewer="system",
                        notes="Affected by source update; verify thematic synthesis remains correct.",
                    )
    except Exception as exc:  # pragma: no cover
        append_wiki_log(f"ERROR writing concept pages: {exc}", wiki_dir)

    # 3.5 Impact propagation report
    deleted_sources = sorted(set(manifest.keys()) - set(new_manifest.keys()))
    affected_entities = sorted(
        {
            str(e).strip()
            for c in changed_cards
            for e in c.get("entities", [])
            if str(e).strip()
        }
    )
    affected_concepts = sorted(
        {
            str(c).strip()
            for card in changed_cards
            for c in card.get("concepts", [])
            if str(c).strip()
        }
    )
    try:
        write_impact_report(
            wiki_dir,
            changed_sources=changed_source_paths,
            unchanged_sources=unchanged_source_paths,
            deleted_sources=deleted_sources,
            affected_entities=affected_entities,
            affected_concepts=affected_concepts,
        )
    except Exception as exc:  # pragma: no cover
        append_wiki_log(f"ERROR writing impact report: {exc}", wiki_dir)

    # 4. Index
    try:
        write_wiki_index(knowledge_cards, entity_names, wiki_dir)
    except Exception as exc:  # pragma: no cover
        append_wiki_log(f"ERROR writing index: {exc}", wiki_dir)

    # 5. Persist updated manifest
    try:
        _save_manifest(wiki_dir, new_manifest)
    except Exception as exc:  # pragma: no cover
        append_wiki_log(f"ERROR saving manifest: {exc}", wiki_dir)

    elapsed = round(time.time() - started, 2)
    append_wiki_log(
        f"Wiki generation complete — {len(source_pages)} source pages, "
        f"{len(entity_names)} entity pages, {len(concept_names)} concept pages, "
        f"{skipped_unchanged} unchanged skipped, elapsed {elapsed}s",
        wiki_dir,
    )

    return {
        "source_pages": len(source_pages),
        "entity_pages": len(entity_names),
        "concept_pages": len(concept_names),
        "skipped_unchanged": skipped_unchanged,
        "changed_sources": len(changed_source_paths),
        "unchanged_sources": len(unchanged_source_paths),
        "deleted_sources": len(deleted_sources),
        "entity_names": entity_names,
        "wiki_dir": str(wiki_dir),
        "elapsed_seconds": elapsed,
    }
