from app.retrieval import service


class _FallbackOnSettings:
    retrieval_llm_fallback_enabled = True
    retrieval_llm_fallback_min_chars = 80
    retrieval_llm_entity_fallback_min_chars = 140
    retrieval_llm_fallback_phrases = "i cannot provide,not enough context"


class _FallbackOffSettings:
    retrieval_llm_fallback_enabled = False
    retrieval_llm_fallback_min_chars = 80
    retrieval_llm_entity_fallback_min_chars = 140
    retrieval_llm_fallback_phrases = "i cannot provide,not enough context"


def test_insufficient_when_contains_weak_phrase(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _FallbackOnSettings())

    assert service._is_llm_answer_insufficient(
        "I cannot provide an answer for this request.",
        "What is SSDP?",
    )


def test_insufficient_for_short_entity_answer_without_definition_pattern(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _FallbackOnSettings())

    assert service._is_llm_answer_insufficient(
        "SSDP appears in onboarding content but details are limited.",
        "What is SSDP?",
    )


def test_sufficient_for_entity_answer_with_definition(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _FallbackOnSettings())

    long_answer = (
        "SSDP means Self Service Disruption Portal and is used by travel agents and operations teams "
        "to process disruption workflows, validate policy constraints, and submit approved actions "
        "through the enterprise onboarding and operations flow."
    )

    assert not service._is_llm_answer_insufficient(long_answer, "What is SSDP?")


def test_insufficient_for_procedural_answer_that_only_points_to_document(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _FallbackOnSettings())

    assert service._is_llm_answer_insufficient(
        "Refer to Edit Country module in TA Manager_v1.9.pdf for filtering and sorting country data.",
        "How do you filter and sort country data within the TA Manager interface?",
    )


def test_sufficient_for_detailed_procedural_answer(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _FallbackOnSettings())

    detailed_answer = (
        "Apply the filter first, identify the country record to update, and then sort by clicking the required "
        "column heading to switch between ascending and descending order. In the Edit Country flow, click Edit, "
        "make the required changes, and save the update once the correct country row is selected."
    )

    assert not service._is_llm_answer_insufficient(
        detailed_answer,
        "How do you filter and sort country data within the TA Manager interface?",
    )


def test_fallback_gate_disabled(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _FallbackOffSettings())

    assert not service._is_llm_answer_insufficient(
        "brief answer",
        "What is SSDP?",
    )
