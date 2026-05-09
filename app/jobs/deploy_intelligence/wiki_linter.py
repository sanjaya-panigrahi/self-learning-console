"""Wiki linter: LLM-driven quality check for the project knowledge wiki.

Sends a compact digest of knowledge cards to the LLM and requests
a structured wiki-quality review identifying:

- Orphan topics (mentioned across many cards but lacking a dedicated page)
- Coverage gaps (important topics underrepresented in the corpus)
- Potential contradictions (summary-level, not deep claim-level)
- Stale claims (areas where newer docs may supersede older assertions)
- Suggested new sources (topics worth investigating)

Writes the lint report to ``wiki_dir/lint_report.md``.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.core.prompts.toon import render_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_generate(
    model: str,
    prompt: str,
    ollama_base_url: str,
    timeout_seconds: float = 90.0,
) -> str:
    """Return raw LLM text response (not JSON)."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    timeout = httpx.Timeout(connect=5.0, read=max(float(timeout_seconds), 60.0), write=10.0, pool=5.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{ollama_base_url}/api/generate", json=payload)
            response.raise_for_status()
            return str(response.json().get("response", "")).strip()
    except httpx.HTTPError:
        return ""


def _compact_digest(cards: list[dict[str, Any]], max_chars: int = 8000) -> str:
    """Build a compact digest of all knowledge cards for the lint prompt."""
    lines: list[str] = []
    for card in cards:
        title = str(card.get("title", card.get("source", "?")))
        summary = str(card.get("summary", ""))[:180]
        entities = ", ".join(str(e) for e in card.get("entities", [])[:6])
        concepts = ", ".join(str(c) for c in card.get("concepts", [])[:4])
        lines.append(f"## {title}")
        if summary:
            lines.append(f"Summary: {summary}")
        if entities:
            lines.append(f"Entities: {entities}")
        if concepts:
            lines.append(f"Concepts: {concepts}")
        lines.append("")

    full = "\n".join(lines)
    return full[:max_chars]


def _parse_sections(text: str) -> dict[str, str]:
    """Split markdown LLM response into named sections."""
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = stripped.lstrip("#").strip().lower()
            current_lines = []
        elif stripped.startswith("#") and current_heading is None:
            # skip top-level title
            pass
        else:
            if current_heading is not None:
                current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


# ---------------------------------------------------------------------------
# Core linter
# ---------------------------------------------------------------------------

def run_wiki_lint(
    knowledge_cards: list[dict[str, Any]],
    wiki_dir: Path,
    *,
    model: str,
    ollama_base_url: str,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Health-check the wiki corpus and write ``wiki_dir/lint_report.md``.

    Returns a summary dict with section excerpts.
    """
    started = time.time()
    digest = _compact_digest(knowledge_cards)

    entity_pages = sorted(
        [p.stem for p in (wiki_dir / "entities").glob("*.md")]
        if (wiki_dir / "entities").exists()
        else []
    )
    concept_pages = sorted(
        [p.stem for p in (wiki_dir / "concepts").glob("*.md")]
        if (wiki_dir / "concepts").exists()
        else []
    )
    answer_pages_count = len(list((wiki_dir / "answers").glob("*.md"))) if (wiki_dir / "answers").exists() else 0

    existing_pages_text = (
        f"Existing entity pages: {', '.join(entity_pages[:30]) or 'none'}\n"
        f"Existing concept pages: {', '.join(concept_pages[:20]) or 'none'}\n"
        f"Filed answer pages: {answer_pages_count}"
    )

    if not knowledge_cards:
        report_text = (
            "## Orphan Topics\n"
            "* None. No documents were available for linting.\n\n"
            "## Coverage Gaps\n"
            "* Cannot assess coverage gaps because no documents were reviewed.\n\n"
            "## Potential Contradictions\n"
            "* None detected. No document pairs available for analysis.\n\n"
            "## Stale Claims\n"
            "* Cannot assess stale claims because no source content was provided.\n\n"
            "## Suggested New Sources\n"
            "* Add at least one source document under the configured Resources directory, then rerun lint.\n\n"
            "## Summary\n"
            "No lint analysis was performed because the knowledge-card corpus is empty."
        )
    else:
        prompt = render_prompt(
            "deploy_intel.wiki_lint.v1",
            values={
                "digest": digest,
                "existing_pages_text": existing_pages_text,
            },
        )

        report_text = _safe_generate(
            model=model,
            prompt=prompt,
            ollama_base_url=ollama_base_url,
            timeout_seconds=timeout_seconds,
        )

    elapsed = round(time.time() - started, 2)

    if not report_text:
        report_text = (
            "## Orphan Topics\n"
            "* Could not assess orphan topics because the lint model did not respond.\n\n"
            "## Coverage Gaps\n"
            "* Could not assess coverage gaps because the lint model did not respond.\n\n"
            "## Potential Contradictions\n"
            "* Could not assess contradictions because the lint model did not respond.\n\n"
            "## Stale Claims\n"
            "* Could not assess stale claims because the lint model did not respond.\n\n"
            "## Suggested New Sources\n"
            "* Retry lint after verifying the local Ollama model is available.\n\n"
            "## Summary\n"
            "Lint report could not be generated because the LLM did not respond."
        )

    # Prepend metadata header
    now_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    header = (
        f"# Wiki Lint Report\n\n"
        f"> **Generated:** {now_str}  \n"
        f"> **Documents reviewed:** {len(knowledge_cards)}  \n"
        f"> **Entity pages:** {len(entity_pages)}  \n"
        f"> **Concept pages:** {len(concept_pages)}  \n"
        f"> **Answer pages:** {answer_pages_count}  \n"
        f"> **Elapsed:** {elapsed}s\n\n"
        "---\n\n"
    )

    full_report = header + report_text

    wiki_dir.mkdir(parents=True, exist_ok=True)
    lint_path = wiki_dir / "lint_report.md"
    lint_path.write_text(full_report, encoding="utf-8")

    sections = _parse_sections(report_text)

    from app.jobs.deploy_intelligence.wiki_writer import append_wiki_log

    append_wiki_log(
        f"Wiki lint complete — {len(knowledge_cards)} docs reviewed, elapsed {elapsed}s",
        wiki_dir,
    )

    return {
        "elapsed_seconds": elapsed,
        "documents_reviewed": len(knowledge_cards),
        "report_path": str(lint_path),
        "orphan_topics": sections.get("orphan topics", ""),
        "coverage_gaps": sections.get("coverage gaps", ""),
        "summary": sections.get("summary", ""),
    }
