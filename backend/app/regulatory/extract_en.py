"""Segment the English Implementing Regulations into articles.

The problem this solves is not obvious from reading the PDF. Visually every article opens
**ARTICLE THIRTY-SEVEN. RELATED PERSONS** — but only the *title* half is text. The
`ARTICLE THIRTY-SEVEN.` half is an **embedded image**, a ~10pt strip drawn at the left margin,
and no text extractor returns it: pdfplumber, pdfplumber's word-level API and pypdf all hand
back `RELATED PERSONS` with the number silently gone.

That is why this module segments on *structure* rather than on a text pattern:

    an image ~10pt tall at the left margin, with green title text on the same row
      = an article starts here

The marker is a reliable boundary even though it is unreadable, so the article number comes
from **position in the document** — the nth marker is article n — and is then cross-checked
against the Arabic edition, which does carry explicit numbers. Two independent sources agreeing
is what makes the numbering trustworthy; a number derived from sequence alone would be an
assumption, and a wrong article number on a finding is the kind of error that is very visible
on appeal.

Colour does the rest of the work. The document is set in three colours and they are consistent
throughout: blue for chapter headings, green for article titles and list markers, grey for body
prose. So a chapter is recognised by colour rather than by the word "CHAPTER", and a title is
recognised by being green *and* upper-case, which is what keeps the green `1-` list markers out
of the titles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# The document's own palette, sampled from the file. Compared with a tolerance because PDF
# colour components are floats and the writer is not bit-exact between objects.
GREEN = (0.3843137, 0.7019608, 0.3098039)      # article titles and list markers
BLUE = (0.1098039, 0.6039216, 0.8392157)       # chapter headings
EPS = 0.03

MARKER_MIN_H, MARKER_MAX_H = 7.0, 15.0         # the article-number image strip
MARKER_MAX_X = 90.0                            # it sits at the left margin
ROW_TOLERANCE = 6.0                            # words on "the same line" as the marker

# Footnote references are set as digits immediately after the title ("TAX INVOICES21",
# "DATE OF SUPPLY ... CIRCUMSTANCES 9 10"). They are part of the amendment apparatus, not the
# title, and leaving them in would make an article's title fail to match its Arabic counterpart.
_TRAILING_FOOTNOTES = re.compile(r"[\s\d]+$")
_INNER_FOOTNOTE = re.compile(r"(?<=[A-Z])\d+$")


@dataclass
class Article:
    seq: int                    # 1-based position in the document
    title: str
    chapter: str
    page: int                   # 1-based page the article starts on
    text: str = ""
    number: int | None = None   # filled by the Arabic cross-check
    paragraphs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"seq": self.seq, "number": self.number, "title": self.title,
                "chapter": self.chapter, "page": self.page, "text": self.text,
                "paragraphs": self.paragraphs}


def _is(colour, target) -> bool:
    return (isinstance(colour, (list, tuple)) and len(colour) >= 3
            and all(abs(a - b) < EPS for a, b in zip(colour[:3], target)))


def _clean_title(words: list[str]) -> str:
    t = " ".join(words).strip()
    t = _TRAILING_FOOTNOTES.sub("", t).strip()
    t = _INNER_FOOTNOTE.sub("", t).strip()
    return re.sub(r"\s+", " ", t)


# A footnote reference is a bare one- or two-digit number sitting after the full stop that ends
# a sentence — "…into the Kingdom. 7". Deliberately narrow: this text is full of legitimate
# numbers ("two hundred (200) SAR", "fifty percent (50%)"), and stripping those would corrupt
# the words a finding is quoted from. Only a lone digit run terminating the text or a line is
# treated as apparatus.
_FOOTNOTE_MARK = re.compile(r"(?<=\.)\s*\d{1,2}\s*(?=\n|$)")


def _strip_footnote_marks(text: str) -> str:
    return _FOOTNOTE_MARK.sub("", text).strip()


def _rows(words: list[dict]) -> list[tuple[float, list[dict]]]:
    """Group words into visual lines, keyed by their top coordinate."""
    out: dict[float, list[dict]] = {}
    for w in words:
        key = next((k for k in out if abs(k - w["top"]) < 3.0), w["top"])
        out.setdefault(key, []).append(w)
    return sorted(((k, sorted(v, key=lambda w: w["x0"])) for k, v in out.items()),
                  key=lambda kv: kv[0])


def _is_title_row(row: list[dict]) -> bool:
    """Green and upper-case. The `and` matters: list markers are green too."""
    if not row:
        return False
    if not all(_is(w.get("non_stroking_color"), GREEN) for w in row):
        return False
    letters = [c for w in row for c in w["text"] if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def articles(pdf_path: str | Path) -> list[Article]:
    """Every article in the English edition, in document order."""
    import pdfplumber

    found: list[Article] = []
    chapter = ""
    pending: Article | None = None
    buffer: list[str] = []

    def close(article: Article | None, lines: list[str]) -> None:
        if article is None:
            return
        body = "\n".join(l for l in lines if l.strip())
        article.text = _strip_footnote_marks(body.strip())
        article.paragraphs = _split_paragraphs(article.text)
        found.append(article)

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(extra_attrs=["fontname", "size", "non_stroking_color"])
            markers = [im for im in page.images
                       if MARKER_MIN_H <= im["bottom"] - im["top"] <= MARKER_MAX_H
                       and im["x0"] < MARKER_MAX_X]
            marker_tops = [im["top"] for im in markers]
            rows = _rows(words)

            i = 0
            while i < len(rows):
                top, row = rows[i]
                text = " ".join(w["text"] for w in row)

                if all(_is(w.get("non_stroking_color"), BLUE) for w in row) and row:
                    chapter = re.sub(r"\s+", " ", text).strip()
                    i += 1
                    continue

                starts_article = (any(abs(top - m) < ROW_TOLERANCE for m in marker_tops)
                                  and _is_title_row(row))
                if starts_article:
                    close(pending, buffer)
                    buffer = []
                    title_words = [w["text"] for w in row]
                    # a title may wrap onto the following line(s)
                    j = i + 1
                    while j < len(rows) and _is_title_row(rows[j][1]):
                        title_words += [w["text"] for w in rows[j][1]]
                        j += 1
                    pending = Article(seq=len(found) + 1, title=_clean_title(title_words),
                                      chapter=chapter, page=page_no)
                    i = j
                    continue

                buffer.append(text)
                i += 1

    close(pending, buffer)
    for n, a in enumerate(found, start=1):
        a.seq = n
    return found


_PARA_START = re.compile(r"^\s*(\d+)\s*[-–]\s")


def _split_paragraphs(text: str) -> list[str]:
    """The numbered paragraphs an article is actually cited by ("Article 50(1)(b)")."""
    paras: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if _PARA_START.match(line) and current:
            paras.append(" ".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        paras.append(" ".join(current).strip())
    return [p for p in paras if p.strip()]
