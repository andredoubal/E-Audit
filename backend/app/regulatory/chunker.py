"""Regex-based legal hierarchy chunking: Regulation -> Chapter -> Article -> Paragraph ->
Subparagraph, producing stable IDs and a flat list of unit drafts with parent links.

This is the highest-risk piece of the ingestion pipeline: the regulations already contain
semantic/legal boundaries (an article, a paragraph, an exception), and the whole point of the
hierarchy is to retrieve at those boundaries instead of an arbitrary token window that could
split a condition from its exception. Get the boundary detection wrong here and every
downstream citation is wrong with it — so this file is the most heavily unit-tested piece of
the pipeline (test_regulatory_chunker.py).

English patterns only. Arabic hierarchy detection (the real ZATCA Implementing Regulations is
Arabic-only, with articles numbered by spelled-out ordinal words rather than digits — e.g.
"Article Nine" rather than "Article 9") is a distinct grammar handled by
`regulatory/arabic_chunker.py`, not a variant of these regexes.
"""
from __future__ import annotations

import re

CHAPTER_RE = re.compile(r"^Chapter\s+(\w+)\s*:?\s*(.*)$", re.M | re.I)
ARTICLE_RE = re.compile(r"^Article\s+(\d+)\s*:?\s*(.*)$", re.M | re.I)
PARAGRAPH_RE = re.compile(r"^\s{0,3}(\d+)\.\s+(.*)$", re.M)
SUBPARA_RE = re.compile(r"^\s*\(([a-z])\)\s+(.*)$", re.M)
ARTICLE_REF_RE = re.compile(r"\bArticle\s+(\d+)\b", re.I)  # cross-reference detection


def make_unit_id(regulation_code: str, article: str, paragraph: str = "", subpara: str = "") -> str:
    parts = [regulation_code, f"A{article}"]
    if paragraph:
        parts.append(f"P{int(paragraph):02d}")
    if subpara:
        parts.append(f"S{subpara}")
    return "-".join(parts)


def _find_all(pattern: re.Pattern, text: str) -> list[tuple[int, re.Match]]:
    return [(m.start(), m) for m in pattern.finditer(text)]


def chunk(text: str, *, regulation_code: str) -> list[dict]:
    """Walks the text once, tracking the current chapter/article/paragraph, and emits a flat
    list of unit drafts. Each dict has: unit_id, level, parent_id, article_no, paragraph_no,
    subparagraph_no, chapter_no, chapter_title, title, citation_label, text.

    Boundaries are found in one pass over the whole text (chapters, articles, paragraphs,
    subparagraphs all located up front), then each unit's body text is sliced between its own
    start and the start of the next marker at the same level-or-higher — this is what keeps a
    condition and its exception together: a subparagraph's text runs until the next
    subparagraph/paragraph/article/chapter marker, never a fixed token count.
    """
    chapters = _find_all(CHAPTER_RE, text)
    articles = _find_all(ARTICLE_RE, text)
    paragraphs = _find_all(PARAGRAPH_RE, text)
    subparas = _find_all(SUBPARA_RE, text)

    all_markers = sorted(
        [(pos, "chapter", m) for pos, m in chapters]
        + [(pos, "article", m) for pos, m in articles]
        + [(pos, "paragraph", m) for pos, m in paragraphs]
        + [(pos, "subparagraph", m) for pos, m in subparas]
    )

    def body_between(start_pos: int, header_end: int, min_level_rank: int) -> str:
        """Text from header_end up to the next marker whose rank is <= min_level_rank."""
        rank = {"chapter": 0, "article": 1, "paragraph": 2, "subparagraph": 3}
        end = len(text)
        for pos, kind, _m in all_markers:
            if pos > start_pos and rank[kind] <= min_level_rank:
                end = pos
                break
        return text[header_end:end].strip()

    units: list[dict] = []
    cur_chapter_no, cur_chapter_title = "", ""
    cur_article_no, cur_article_id = "", None
    cur_paragraph_no, cur_paragraph_id = "", None

    for pos, kind, m in all_markers:
        if kind == "chapter":
            cur_chapter_no, cur_chapter_title = m.group(1), m.group(2).strip()
            continue

        if kind == "article":
            article_no, title = m.group(1), m.group(2).strip()
            unit_id = make_unit_id(regulation_code, article_no)
            body = body_between(pos, m.end(), min_level_rank=1)
            units.append({
                "unit_id": unit_id, "level": "article", "parent_id": None,
                "article_no": article_no, "paragraph_no": "", "subparagraph_no": "",
                "chapter_no": cur_chapter_no, "chapter_title": cur_chapter_title,
                "title": title, "citation_label": f"Article {article_no}",
                "text": (title + "\n" + body).strip() if body else title,
            })
            cur_article_no, cur_article_id = article_no, unit_id
            cur_paragraph_no, cur_paragraph_id = "", None
            continue

        if kind == "paragraph":
            if cur_article_id is None:
                continue  # a numbered line before any Article header is not a legal paragraph
            paragraph_no, ptext = m.group(1), m.group(2).strip()
            unit_id = make_unit_id(regulation_code, cur_article_no, paragraph_no)
            body = body_between(pos, m.end(), min_level_rank=2)
            units.append({
                "unit_id": unit_id, "level": "paragraph", "parent_id": cur_article_id,
                "article_no": cur_article_no, "paragraph_no": paragraph_no, "subparagraph_no": "",
                "chapter_no": cur_chapter_no, "chapter_title": cur_chapter_title,
                "title": "", "citation_label": f"Article {cur_article_no}, Paragraph {paragraph_no}",
                "text": (ptext + "\n" + body).strip() if body else ptext,
            })
            cur_paragraph_no, cur_paragraph_id = paragraph_no, unit_id
            continue

        if kind == "subparagraph":
            if cur_paragraph_id is None:
                continue  # a lettered line before any paragraph is not a legal subparagraph
            sub_no, stext = m.group(1), m.group(2).strip()
            unit_id = make_unit_id(regulation_code, cur_article_no, cur_paragraph_no, sub_no)
            body = body_between(pos, m.end(), min_level_rank=3)
            units.append({
                "unit_id": unit_id, "level": "subparagraph", "parent_id": cur_paragraph_id,
                "article_no": cur_article_no, "paragraph_no": cur_paragraph_no,
                "subparagraph_no": sub_no,
                "chapter_no": cur_chapter_no, "chapter_title": cur_chapter_title,
                "title": "",
                "citation_label": (
                    f"Article {cur_article_no}, Paragraph {cur_paragraph_no}({sub_no})"),
                "text": (stext + "\n" + body).strip() if body else stext,
            })

    return units


def find_article_references(text: str, *, exclude_article: str = "") -> set[str]:
    """Cross-reference detection: every "Article N" mentioned in a unit's own text, other than
    a self-reference."""
    return {n for n in ARTICLE_REF_RE.findall(text or "") if n != exclude_article}
