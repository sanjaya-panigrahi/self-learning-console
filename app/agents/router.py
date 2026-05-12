"""Router agent for selecting retrieval orchestrator."""


def choose_orchestrator(default_orchestrator: str, requested_orchestrator: str | None = None) -> str:
    """Choose effective orchestrator based on optional request override."""
    value = (requested_orchestrator or default_orchestrator or "custom").strip().lower()
    if value in {"custom", "llamaindex"}:
        return value
    return "custom"
