from pathlib import Path

import pytest

from app.jobs.deploy_intelligence import wiki_writer


class _PolicySettings:
    wiki_learning_requires_explicit_trigger = True
    wiki_allowed_update_triggers = "deploy-intelligence,feedback-auto-helpful,admin-api"
    wiki_require_sources_for_answer_pages = True
    wiki_enforce_feedback_confidence = True
    wiki_auto_file_min_confidence = 0.8


def test_write_answer_page_rejects_unknown_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_writer, "get_settings", lambda: _PolicySettings())

    with pytest.raises(PermissionError):
        wiki_writer.write_answer_page(
            question="What changed?",
            answer="Details",
            wiki_dir=tmp_path / "wiki",
            confidence=0.95,
            sources=["Resources/doc-a.pdf"],
            filed_by="admin-api",
            trigger="background-loop",
        )


def test_write_answer_page_requires_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_writer, "get_settings", lambda: _PolicySettings())

    with pytest.raises(ValueError):
        wiki_writer.write_answer_page(
            question="What changed?",
            answer="Details",
            wiki_dir=tmp_path / "wiki",
            confidence=0.95,
            sources=[],
            filed_by="admin-api",
            trigger="admin-api",
        )


def test_auto_helpful_requires_confidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_writer, "get_settings", lambda: _PolicySettings())

    with pytest.raises(ValueError):
        wiki_writer.write_answer_page(
            question="What changed?",
            answer="Details",
            wiki_dir=tmp_path / "wiki",
            confidence=0.65,
            sources=["Resources/doc-a.pdf"],
            filed_by="auto-helpful",
            trigger="feedback-auto-helpful",
        )


def test_run_wiki_generation_requires_allowed_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiki_writer, "get_settings", lambda: _PolicySettings())

    with pytest.raises(PermissionError):
        wiki_writer.run_wiki_generation(
            knowledge_cards=[],
            wiki_dir=tmp_path / "wiki",
            min_entity_docs=2,
            trigger="continuous-background",
        )


def test_write_answer_page_merges_semantic_variant_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiki_writer, "get_settings", lambda: _PolicySettings())

    wiki_dir = tmp_path / "wiki"

    first = wiki_writer.write_answer_page(
        question="What is IROP?",
        answer="IROP means Irregular Operations.",
        wiki_dir=wiki_dir,
        confidence=0.9,
        sources=["Resources/doc-a.pdf"],
        filed_by="admin-api",
        trigger="admin-api",
    )
    second = wiki_writer.write_answer_page(
        question="Can you explain irregular operations?",
        answer="Irregular operations are disruption handling workflows. They activate during cancellations, weather, or crew issues.",
        wiki_dir=wiki_dir,
        confidence=0.88,
        sources=["Resources/doc-a.pdf"],
        filed_by="admin-api",
        trigger="admin-api",
    )

    assert first == second
    answers_dir = wiki_dir / "answers"
    assert len(list(answers_dir.glob("*.md"))) == 1

    content = first.read_text(encoding="utf-8")
    assert "Can you explain irregular operations?" in content
    # Enriched answer should include the more detailed incoming answer
    assert "disruption handling workflows" in content
    assert "cancellations, weather, or crew issues" in content
