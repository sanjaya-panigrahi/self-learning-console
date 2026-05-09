"""Contradiction detector: compares knowledge cards from different documents and flags
conflicting claims using an LLM judge.

Only compares pairs of documents that share at least one named entity — this
bounds the comparison to semantically related document pairs and avoids O(n²) LLM calls.

Output is written to ``wiki_dir/contradictions.json``.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from app.core.prompts.toon import render_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_generate_json(
    model: str,
    prompt: str,
    ollama_base_url: str,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    timeout = httpx.Timeout(connect=5.0, read=max(float(timeout_seconds), 30.0), write=10.0, pool=5.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{ollama_base_url}/api/generate", json=payload)
            response.raise_for_status()
            raw = str(response.json().get("response", "")).strip()
        if not raw:
            return {}
        return json.loads(raw)
    except (httpx.HTTPError, json.JSONDecodeError):
        return {}


def _build_entity_pairs(
    cards: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return unique document pairs that share at least one named entity."""
    entity_to_cards: dict[str, list[int]] = defaultdict(list)
    for idx, card in enumerate(cards):
        for entity in card.get("entities", []):
            name = str(entity).strip().lower()
            if name:
                entity_to_cards[name].append(idx)

    seen: set[tuple[int, int]] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for _entity, indices in entity_to_cards.items():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = sorted((indices[i], indices[j]))
                if (a, b) not in seen:
                    seen.add((a, b))
                    pairs.append((cards[a], cards[b]))

    return pairs


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------

def detect_contradictions(
    knowledge_cards: list[dict[str, Any]],
    wiki_dir: Path,
    *,
    model: str,
    ollama_base_url: str,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Compare knowledge card pairs for conflicting claims.

    Returns a summary dict and writes ``wiki_dir/contradictions.json``.
    """
    started = time.time()
    pairs = _build_entity_pairs(knowledge_cards)

    contradictions: list[dict[str, Any]] = []

    for card_a, card_b in pairs:
        title_a = str(card_a.get("title", card_a.get("source", "Doc A")))
        title_b = str(card_b.get("title", card_b.get("source", "Doc B")))

        kp_a = [str(k).strip() for k in card_a.get("key_points", []) if str(k).strip()]
        kp_b = [str(k).strip() for k in card_b.get("key_points", []) if str(k).strip()]

        if not kp_a or not kp_b:
            continue

        kp_a_text = "\n".join(f"- {k}" for k in kp_a[:8])
        kp_b_text = "\n".join(f"- {k}" for k in kp_b[:8])

        prompt = render_prompt(
            "deploy_intel.contradictions.v1",
            values={
                "title_a": title_a,
                "kp_a_text": kp_a_text,
                "title_b": title_b,
                "kp_b_text": kp_b_text,
            },
        )

        result = _safe_generate_json(
            model=model,
            prompt=prompt,
            ollama_base_url=ollama_base_url,
            timeout_seconds=timeout_seconds,
        )

        found = result.get("contradictions", [])
        if not isinstance(found, list):
            found = []

        for item in found:
            if not isinstance(item, dict):
                continue
            claim_a = str(item.get("claim_a", "")).strip()
            claim_b = str(item.get("claim_b", "")).strip()
            explanation = str(item.get("explanation", "")).strip()
            if claim_a and claim_b:
                contradictions.append(
                    {
                        "doc_a": title_a,
                        "source_a": str(card_a.get("source", "")),
                        "doc_b": title_b,
                        "source_b": str(card_b.get("source", "")),
                        "claim_a": claim_a,
                        "claim_b": claim_b,
                        "explanation": explanation,
                    }
                )

    elapsed = round(time.time() - started, 2)
    output = {
        "generated_at": int(time.time()),
        "pairs_checked": len(pairs),
        "contradictions_found": len(contradictions),
        "elapsed_seconds": elapsed,
        "contradictions": contradictions,
    }

    wiki_dir.mkdir(parents=True, exist_ok=True)
    contradiction_path = wiki_dir / "contradictions.json"
    contradiction_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    # Append to wiki log
    from app.jobs.deploy_intelligence.wiki_writer import append_wiki_log  # local import to avoid circular

    append_wiki_log(
        f"Contradiction detection complete — {len(pairs)} pairs checked, "
        f"{len(contradictions)} contradiction(s) found",
        wiki_dir,
    )

    return {
        "pairs_checked": len(pairs),
        "contradictions_found": len(contradictions),
        "elapsed_seconds": elapsed,
    }
