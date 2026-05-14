"""File readers for different document types."""

from pathlib import Path
from typing import Any

from pypdf import PdfReader


def _extract_pdf_metadata(reader: PdfReader) -> dict[str, Any]:
    """Extract document-level metadata from PDF.

    Args:
        reader: PyPDF reader instance

    Returns:
        Dict with metadata fields: title, author, subject, creator, creation_date, modified_date
    """
    metadata = {}
    try:
        doc_info = reader.metadata
        if doc_info:
            # Extract standard metadata fields
            if "/Title" in doc_info:
                metadata["doc_title"] = str(doc_info["/Title"]).strip()
            if "/Author" in doc_info:
                metadata["doc_author"] = str(doc_info["/Author"]).strip()
            if "/Subject" in doc_info:
                metadata["doc_subject"] = str(doc_info["/Subject"]).strip()
            if "/Creator" in doc_info:
                metadata["doc_creator"] = str(doc_info["/Creator"]).strip()
            if "/CreationDate" in doc_info:
                metadata["doc_creation_date"] = str(doc_info["/CreationDate"]).strip()
            if "/ModDate" in doc_info:
                metadata["doc_modified_date"] = str(doc_info["/ModDate"]).strip()
            
            # Add page count
            metadata["doc_page_count"] = len(reader.pages)
    except Exception:
        # Gracefully handle metadata extraction errors
        pass
    
    return metadata


def read_text_file(file_path: Path) -> str:
    """Read plain text file.

    Args:
        file_path: Path to text file

    Returns:
        File contents as string
    """
    return file_path.read_text(encoding="utf-8", errors="ignore").strip()


def read_pdf_file(file_path: Path) -> tuple[str, dict[str, Any]]:
    """Read PDF file with optional OCR fallback.

    Args:
        file_path: Path to PDF file

    Returns:
        Tuple of (extracted_text, metadata)
    """
    reader = PdfReader(str(file_path))
    
    # Extract document metadata
    doc_metadata = _extract_pdf_metadata(reader)
    
    # Extract text with page number tracking
    pages_with_numbers = []
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages_with_numbers.append({"page": page_num, "text": text.strip()})
    
    extracted_text = "\n".join(p["text"] for p in pages_with_numbers)

    from app.core.config.settings import get_settings

    settings = get_settings()
    if not bool(getattr(settings, "ingestion_ocr_enabled", False)):
        return extracted_text, {
            "ocr_used": False,
            "ocr_pages": 0,
            "ingestion_method": "pdf_text",
            "pages_with_text": pages_with_numbers,
            **doc_metadata
        }

    min_chars = max(1, int(getattr(settings, "ingestion_ocr_min_chars", 120)))
    if len(extracted_text.strip()) >= min_chars:
        return extracted_text, {
            "ocr_used": False,
            "ocr_pages": 0,
            "ingestion_method": "pdf_text",
            "pages_with_text": pages_with_numbers,
            **doc_metadata
        }

    ocr_text, ocr_pages = _read_pdf_file_with_ocr(file_path)
    if not ocr_text.strip():
        return extracted_text, {
            "ocr_used": False,
            "ocr_pages": 0,
            "ingestion_method": "pdf_text",
            "pages_with_text": pages_with_numbers,
            **doc_metadata
        }

    if extracted_text.strip():
        combined = f"{extracted_text}\n\n{ocr_text}".strip()
    else:
        combined = ocr_text.strip()
    return combined, {
        "ocr_used": True,
        "ocr_pages": ocr_pages,
        "ingestion_method": "pdf_text_plus_ocr",
        "pages_with_text": pages_with_numbers,
        **doc_metadata
    }


def _read_pdf_file_with_ocr(file_path: Path) -> tuple[str, int]:
    """Extract text from PDF using OCR (Tesseract + pypdfium2).

    Args:
        file_path: Path to PDF file

    Returns:
        Tuple of (ocr_text, num_pages_processed)
    """
    from app.core.config.settings import get_settings

    settings = get_settings()
    max_pages = max(1, int(getattr(settings, "ingestion_ocr_max_pages", 20)))
    dpi = max(72, int(getattr(settings, "ingestion_ocr_dpi", 200)))
    scale = dpi / 72.0

    try:
        import pypdfium2 as pdfium
        import pytesseract
    except Exception:
        return "", 0

    snippets: list[str] = []
    pages_with_text = 0
    try:
        document = pdfium.PdfDocument(str(file_path))
    except Exception:
        return "", 0

    page_count = len(document)
    for index in range(min(page_count, max_pages)):
        try:
            page = document[index]
            pil_image = page.render(scale=scale).to_pil()
            text = pytesseract.image_to_string(pil_image).strip()
            if text:
                snippets.append(text)
                pages_with_text += 1
        except Exception:
            continue

    return "\n".join(snippets).strip(), pages_with_text


def read_source_file(file_path: Path) -> tuple[str, dict[str, Any]]:
    """Read any supported source file (delegates to specific readers).

    Args:
        file_path: Path to file

    Returns:
        Tuple of (content, metadata)
    """
    if file_path.suffix.lower() == ".pdf":
        return read_pdf_file(file_path)
    return read_text_file(file_path), {"ocr_used": False, "ocr_pages": 0, "ingestion_method": "text_reader"}
