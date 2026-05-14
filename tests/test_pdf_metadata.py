#!/usr/bin/env python3
"""Test script to verify PDF metadata extraction."""

import argparse
import os
from pathlib import Path
from app.ingestion.readers import read_pdf_file

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect extracted metadata for a PDF file.")
    parser.add_argument(
        "pdf_path",
        nargs="?",
        help="Path to a PDF file. You can also set TEST_PDF_PATH.",
    )
    return parser.parse_args()


def resolve_pdf_path() -> Path | None:
    args = parse_args()
    candidate = args.pdf_path or os.environ.get("TEST_PDF_PATH", "")
    candidate = str(candidate).strip()
    if not candidate:
        return None
    return Path(candidate)


test_pdf = resolve_pdf_path()

if test_pdf is None:
    print("Usage: python test_pdf_metadata.py <path-to-pdf>")
    print("Or set environment variable TEST_PDF_PATH.")
elif test_pdf.exists():
    print(f"Testing PDF: {test_pdf}")
    print("-" * 80)
    
    text, metadata = read_pdf_file(test_pdf)
    
    print(f"Text length: {len(text)} characters")
    print(f"OCR used: {metadata.get('ocr_used')}")
    print(f"Ingestion method: {metadata.get('ingestion_method')}")
    print()
    
    # Print extracted metadata
    print("Document Metadata:")
    for key in ["doc_title", "doc_author", "doc_subject", "doc_creator", 
                "doc_creation_date", "doc_modified_date", "doc_page_count"]:
        if key in metadata:
            print(f"  {key}: {metadata[key]}")
    
    print()
    print("Pages with text:")
    pages = metadata.get("pages_with_text", [])
    for page_info in pages[:5]:  # Show first 5 pages
        page_num = page_info.get("page")
        text_len = len(page_info.get("text", ""))
        print(f"  Page {page_num}: {text_len} characters")
    
    if len(pages) > 5:
        print(f"  ... and {len(pages) - 5} more pages")
    
    print()
    print("First 200 chars of extracted text:")
    print(text[:200])
else:
    print(f"Test PDF not found: {test_pdf}")
