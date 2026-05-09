from app.ingestion.pipeline import run_ingestion


def run_reindex() -> dict[str, object]:
    return run_ingestion()
