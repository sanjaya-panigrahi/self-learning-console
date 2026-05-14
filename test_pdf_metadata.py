#!/usr/bin/env python3
"""Test script to verify PDF metadata extraction."""

from pathlib import Path
from app.ingestion.readers import read_pdf_file

# Test with a sample PDF
test_pdf = Path("Resources/Documents/User Guides/TA Ramp User Guide_v1.5 1.pdf")

if test_pdf.exists():
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
