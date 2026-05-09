import re
from pathlib import Path
from urllib.parse import quote

from app.core.config.settings import get_settings
from app.ingestion.pipeline import resolve_ingestion_source_dir
from app.retrieval.service.schemas import RetrievalVisualReference


def resolve_visual_reference_source(source_name: str) -> Path | None:
    source_dir = resolve_ingestion_source_dir()
    requested = Path(source_name)
    direct_path = source_dir / requested
    if direct_path.exists() and direct_path.is_file():
        return direct_path

    matches = [path for path in source_dir.rglob("*") if path.is_file() and path.name == requested.name]
    if not matches:
        return None
    matches.sort(key=lambda path: (len(path.parts), str(path)))
    return matches[0]


def visual_preview_dir() -> Path:
    settings = get_settings()
    preview_dir = Path(settings.local_index_path).parent.parent / "visual_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    return preview_dir


def render_pdf_preview(source_path: Path) -> Path | None:
    preview_dir = visual_preview_dir()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", source_path.stem).strip("-") or "preview"
    preview_path = preview_dir / f"{safe_stem}.png"
    if preview_path.exists() and preview_path.stat().st_mtime >= source_path.stat().st_mtime:
        return preview_path

    try:
        import fitz

        with fitz.open(source_path) as document:
            if document.page_count == 0:
                return None
            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
            pixmap.save(preview_path)
        return preview_path
    except Exception:
        return None


def render_chunk_page_image(source: str, chunk_text: str) -> Path | None:
    source_path = resolve_visual_reference_source(source)
    if not source_path or source_path.suffix.lower() != ".pdf" or not source_path.exists():
        return None

    try:
        import fitz
    except ImportError:
        return None

    preview_dir = visual_preview_dir()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", source_path.stem).strip("-") or "doc"
    key_text = re.sub(r"[^a-zA-Z0-9]+", "-", chunk_text[:80].lower()).strip("-")
    preview_path = preview_dir / f"{safe_stem}--chunk--{key_text}.png"
    if preview_path.exists():
        return preview_path

    try:
        search_snippet = " ".join(chunk_text.split()[:30])
        with fitz.open(source_path) as document:
            best_page_idx = 0
            best_score = 0
            tokens = [t.lower() for t in search_snippet.split() if len(t) >= 4]
            for page_idx in range(document.page_count):
                page_text = document.load_page(page_idx).get_text("text").lower()
                score = sum(1 for token in tokens if token in page_text)
                if score > best_score:
                    best_score = score
                    best_page_idx = page_idx

            page = document.load_page(best_page_idx)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            pixmap.save(preview_path)
        return preview_path
    except Exception:
        return None


def build_visual_references(sources: list[str]) -> list[RetrievalVisualReference]:
    references: list[RetrievalVisualReference] = []
    seen: set[str] = set()
    for source_name in sources:
        normalized = source_name.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        source_path = resolve_visual_reference_source(normalized)
        if not source_path or source_path.suffix.lower() != ".pdf":
            continue

        preview_path = render_pdf_preview(source_path)
        references.append(
            {
                "source": normalized,
                "kind": "pdf",
                "preview_url": f"/visual-previews/{quote(preview_path.name)}" if preview_path else "",
                "document_url": f"/api/admin/visual-reference-document?source={quote(normalized)}",
                "note": "Preview generated from the first page of the cited PDF guide.",
            }
        )
        if len(references) >= 3:
            break

    return references


__all__ = [
    "build_visual_references",
    "render_chunk_page_image",
    "render_pdf_preview",
    "resolve_visual_reference_source",
    "visual_preview_dir",
]
