"""Article-level chunking for the real (Arabic) KSA VAT Implementing Regulations.

Deliberately a distinct grammar from `chunker.py`, not a language flag on it: Arabic articles
are numbered by spelled-out ordinal words ("المادة التاسعة" — "Article Nine"), never digits,
so the whole matching strategy differs (arabic_ordinals.parse_ordinal, not \\d+). Also
article-level granularity ONLY — no paragraph/subparagraph splitting. Two independent risks
compound at paragraph level: Arabic legal paragraph markers are dash-suffixed digits mixed with
footnote-reference digits and stray page numbers from the PDF's running header/footer (visible
in the raw extraction), and this file's own RTL reconstruction (below) has only been validated
at the line/article level. Splitting further without that validation would risk exactly the
"losing article numbers" / "incorrect Arabic reading order" failure the architecture is meant
to guard against, for marginal retrieval benefit at this corpus size. Promoting to
paragraph-level is real future work, not a shortcut taken here.

RTL reconstruction: pdfplumber extracts this PDF's text in glyph-presentation-form order
(Arabic Presentation Forms, U+FB50-FDFF/FE70-FEFF) and effectively visual rather than logical
order. `bidi.algorithm.get_display` (python-bidi, the reference Unicode Bidirectional Algorithm
implementation) followed by NFKC normalization (which folds presentation-form glyphs back to
base Arabic letters) recovers correct, readable logical-order text — verified line-by-line
against the real PDF's own table of contents during development (see the module's ingestion
report, not fixture data).
"""
from __future__ import annotations

import re
import unicodedata

from .arabic_ordinals import parse_ordinal, parse_ordinal_masculine, repeated_marker_suffix
from .chunker import make_unit_id

# .search(), not .match(): the real PDF's extraction leaves stray leading digits (footnote
# markers, page numbers caught by the layout) before the marker on some lines — see this
# module's docstring. Anchoring at line-start would silently miss every one of those articles.
_ARTICLE_RE = re.compile(r"المادة\s+([^:\d]{2,45}?(?:\([^)]*\))?)\s*:\s*(.*)")
_CHAPTER_RE = re.compile(r"الفصل\s+([^:\d]{2,40}?)\s*:\s*(.*)")
_ARTICLE_REF_RE = re.compile(r"المادة\s+([^\s.,;:)]{2,25}(?:\s+عشرة)?(?:\s+و[^\s.,;:)]{2,15})?)")
_TOC_DOT_LEADER_RE = re.compile(r"\.{3,}")  # table-of-contents lines use a dot leader to a
                                             # page number — never present in body prose


def reconstruct_lines(raw_text: str) -> list[str]:
    """Bidi-reorder + NFKC-normalize each line of a page's raw pdfplumber extraction. Only the
    real-PDF ingestion path needs this — it undoes an extraction artifact specific to
    pdfplumber's presentation-form/visual-order output, so it must never be applied to text
    that is already in correct logical order (e.g. a hand-written test fixture)."""
    from bidi.algorithm import get_display

    out = []
    for line in (raw_text or "").split("\n"):
        if not line.strip():
            continue
        out.append(unicodedata.normalize("NFKC", get_display(line, base_dir="L")))
    return out


def reconstruct_pages(pages_text: list[str]) -> list[str]:
    """RTL-reconstructed lines for every page of a real pdfplumber extraction, flattened."""
    lines: list[str] = []
    for page in pages_text:
        lines.extend(reconstruct_lines(page))
    return lines


def chunk_arabic(text: str, *, regulation_code: str) -> tuple[list[dict], list[str]]:
    """Article-level units from already logical-order Arabic text (one line of body text per
    newline) — the same shape as `chunker.chunk`. Real-PDF callers pass
    "\\n".join(reconstruct_pages(pages_text)); test fixtures, already correctly ordered, pass
    their text directly. Returns (units, warnings) — a warning is recorded (never silently
    dropped) whenever an "المادة" marker is seen but its ordinal cannot be parsed, so a QA pass
    can find exactly what needs review."""
    lines = [ln for ln in (text or "").split("\n") if ln.strip()]

    units: list[dict] = []
    warnings: list[str] = []
    cur_chapter_no, cur_chapter_title = "", ""
    cur: dict | None = None
    body_lines: list[str] = []

    def flush():
        if cur is not None:
            cur["text"] = (cur["title"] + "\n" + "\n".join(body_lines)).strip()
            units.append(cur)

    for line in lines:
        if _TOC_DOT_LEADER_RE.search(line):
            continue  # table-of-contents entry, not a real chapter/article header

        cm = _CHAPTER_RE.search(line)
        if cm:
            n = parse_ordinal_masculine(cm.group(1).strip())  # "الفصل" is masculine
            if n is not None:
                cur_chapter_no, cur_chapter_title = str(n), cm.group(2).strip()
            continue

        am = _ARTICLE_RE.search(line)
        if am:
            ordinal_text = am.group(1).strip()
            n = parse_ordinal(ordinal_text)
            if n is None:
                warnings.append(f"unparsed article ordinal: {ordinal_text!r} "
                                f"(line: {line[:80]!r})")
                body_lines.append(line)
                continue
            flush()
            # A "(مكرر)" article is a later amendment inserted between two existing articles
            # (e.g. 32-bis sits between 32 and 33) — kept as its own unit, not merged into 32.
            # A trailing digit ("مكرر (2)") distinguishes a second bis article for the same
            # base number from the first, so the two never collide on one unit_id.
            suffix = repeated_marker_suffix(ordinal_text)
            article_no = f"{n}R{suffix}" if suffix is not None else str(n)
            unit_id = make_unit_id(regulation_code, article_no)
            cur = {
                "unit_id": unit_id, "level": "article", "parent_id": None,
                "article_no": article_no, "paragraph_no": "", "subparagraph_no": "",
                "chapter_no": cur_chapter_no, "chapter_title": cur_chapter_title,
                "title": am.group(2).strip(),
                "citation_label": f"Article {n}" + (" (repeated)" if "R" in article_no else ""),
                "lang": "ar",
            }
            body_lines = []
            continue

        if cur is not None:
            body_lines.append(line)

    flush()
    return units, warnings


def find_arabic_article_references(text: str, *, exclude_article: str = "") -> set[str]:
    refs = set()
    for m in _ARTICLE_REF_RE.finditer(text or ""):
        n = parse_ordinal(m.group(1).strip())
        if n is not None and str(n) != exclude_article:
            refs.add(str(n))
    return refs
