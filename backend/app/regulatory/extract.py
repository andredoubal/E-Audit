"""Text extraction — an interface so an OCR extractor (Type C, scanned PDFs) can be added later
without changing ingest.py's caller. The real ZATCA Implementing Regulations is a clean,
digitally-generated PDF (Type A/B), not scanned, so OCR is explicitly out of scope for Phase A.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ExtractedPage:
    page_no: int
    text: str


class TextExtractor(Protocol):
    def extract(self, path: Path) -> list[ExtractedPage]: ...


class PdfplumberExtractor:
    """Type A/B digitally-generated PDFs — what the real ZATCA Implementing Regulations is."""

    def extract(self, path: Path) -> list[ExtractedPage]:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return [
                ExtractedPage(i + 1, page.extract_text() or "")
                for i, page in enumerate(pdf.pages)
            ]


class PlainTextExtractor:
    """Test-fixture extractor — a .txt blob standing in for a PDF, treated as one page."""

    def extract(self, path: Path) -> list[ExtractedPage]:
        return [ExtractedPage(1, Path(path).read_text(encoding="utf-8"))]
