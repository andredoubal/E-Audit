"""The regulations corpus, and the citations built on it.

Extraction from these two PDFs is unusually easy to get quietly wrong, so the tests assert
against facts established independently of the extractor:

* the Implementing Regulations have **79 articles**, and both editions must agree on that;
* **Article 14** is the charging provision and **Article 50** the blocked-input article — read
  from the Arabic before any of this code existed;
* the English edition is ZATCA's **unofficial** translation of **November 2021**, while the
  Arabic carries amendments to 2024, so 31 articles are shown in superseded wording.

The last of those is the one with teeth. Article 14 founds six of the twelve outcomes, and its
English text is out of date — a citation that failed to say so would put superseded wording
under a finding.
"""
from __future__ import annotations

import pytest

from app.regulatory import basis as basis_table
from app.regulatory import lookup
from app import outcomes as oc

ARTICLE_COUNT = 79


@pytest.fixture(scope="module")
def corpus():
    c = lookup._corpus()
    if not c.get("articles"):
        pytest.skip("the corpus JSON has not been built")
    return c


# --------------------------------------------------------------- the corpus
def test_the_corpus_holds_every_article(corpus):
    assert corpus["article_count"] == ARTICLE_COUNT
    numbers = sorted(a["article"] for a in corpus["articles"])
    assert numbers == list(range(1, ARTICLE_COUNT + 1)), "the numbering has a gap"


def test_both_editions_agree_on_the_numbering(corpus):
    """English numbering is derived from position, Arabic from the ordinal words. Two
    independent sources agreeing is what makes a cited article number safe to print."""
    unconfirmed = [a["article"] for a in corpus["articles"] if not a["numbering_confirmed"]]
    assert unconfirmed == [], f"the editions disagree on {unconfirmed}"


def test_the_articles_we_cite_are_the_ones_we_think_they_are(corpus):
    by = {a["article"]: a for a in corpus["articles"]}
    assert "TAXABLE SUPPLIES IN THE KINGDOM" in by[14]["title"]
    assert "RELATED PERSONS" in by[37]["title"]
    assert "INPUT TAX DEDUCTION" in by[49]["title"]
    assert "DEEMED TO BE RECEIVED OUTSIDE" in by[50]["title"]
    assert "TAX INVOICES" in by[53]["title"]
    assert "CREDIT AND DEBIT NOTES" in by[54]["title"]


def test_article_fourteen_carries_the_charging_words(corpus):
    """The provision behind six of the twelve outcomes. If this text is wrong, the citations
    that rest on it are wrong."""
    text = next(a for a in corpus["articles"] if a["article"] == 14)["text"].lower()
    assert "tax is imposed on all taxable supplies" in text
    assert "economic activity" in text


def test_every_article_has_a_title_and_a_body(corpus):
    thin = [a["article"] for a in corpus["articles"]
            if not a["title"].strip() or len(a["text"]) < 40]
    assert thin == [], f"articles extracted with no usable content: {thin}"


def test_footnote_digits_are_not_part_of_a_title(corpus):
    """The PDF sets amendment footnotes as digits glued to the title ("TAX INVOICES21"). Left
    in, they break the match against the Arabic and look like nonsense in a citation."""
    for a in corpus["articles"]:
        assert not a["title"].rstrip().endswith(tuple("0123456789")), a["title"]


# --------------------------------------------------------------- what is out of date
def test_the_english_edition_is_known_to_be_older_than_the_arabic(corpus):
    assert corpus["english_edition_year"] == 2021
    assert len(corpus["amended_since_english_edition"]) > 20, \
        "the whole point of holding both editions is knowing which wording is superseded"


def test_the_charging_article_is_flagged_as_superseded(corpus):
    """Article 14 was amended in 2024; the English shown for it is the 2021 wording."""
    a = next(x for x in corpus["articles"] if x["article"] == 14)
    assert a["last_amended_year"] == 2024
    assert a["english_current"] is False


# --------------------------------------------------------------- the mapping
def test_every_outcome_in_the_vocabulary_has_a_legal_basis():
    """A finding with no provision behind it is an assertion. All twelve are covered."""
    missing = basis_table.uncovered([o.code for o in oc.OUTCOMES])
    assert missing == [], f"no legal basis recorded for {missing}"


def test_the_mapping_only_points_at_articles_that_exist(corpus):
    assert basis_table.validate(corpus) == []


def test_the_charging_provision_founds_the_sales_outcomes():
    for code in ("SAL-HIGHER", "SAL-UNDISCLOSED", "SAL-POS", "SAL-SECONDARY"):
        assert basis_table.for_code(code).article == 14, code


# --------------------------------------------------------------- citations
def test_a_citation_carries_the_articles_own_words(corpus):
    c = lookup.for_outcome("SAL-HIGHER")
    assert c.article == 14
    assert c.label == "Article 14"
    assert "taxable supplies" in c.text.lower()
    assert c.establishes and c.consequence


def test_a_superseded_article_is_needs_validation_and_says_why(corpus):
    c = lookup.for_outcome("SAL-HIGHER")
    assert c.state == lookup.NEEDS_VALIDATION
    assert c.english_current is False
    assert "2024" in c.note and "verify" in c.note.lower()


def test_an_article_still_current_in_english_is_simply_found(corpus):
    """Article 53 was last amended in 2021, so the English wording is the current wording."""
    c = lookup.for_outcome("DOC-INVOICE")
    assert c.article == 53
    assert c.state == lookup.FOUND
    assert c.note == ""


def test_an_unknown_outcome_resolves_to_not_found_rather_than_to_something_plausible():
    """With 79 articles available, the failure mode to guard is a confident wrong citation."""
    c = lookup.for_outcome("NOT-A-CODE")
    assert c.state == lookup.NOT_FOUND
    assert c.article is None
    assert c.note, "and it says that no provision was identified, rather than going silent"


def test_the_finding_reads_as_evidence_then_basis_then_consequence(corpus):
    s = lookup.sentence("SAL-HIGHER")
    assert s.startswith(oc.statement("SAL-HIGHER"))
    assert "Article 14 establishes that" in s
    assert "accordingly," in s
    assert s.rstrip().endswith(".")


def test_a_finding_with_no_basis_is_just_the_statement():
    from app.agents.findings import Finding

    f = Finding(code="X", statement="Something was observed.", amount=1.0, effect="documentation",
                direction="sale", agent="A", hypothesis_id="H")
    assert f.reads_as == "Something was observed."


def test_coverage_is_publishable(corpus):
    c = lookup.coverage()
    assert c["loaded"] is True
    assert c["article_count"] == ARTICLE_COUNT
    assert c["outcomes_with_basis"] == c["outcomes_total"] == 12
    assert c["problems"] == []


def test_no_article_ends_in_a_footnote_marker(corpus):
    """A trailing "75" under a quoted provision makes an auditor distrust the whole citation."""
    import re

    bad = [a["article"] for a in corpus["articles"]
           if re.search(r"\.\s*\d{1,2}\s*$", a["text"])]
    assert bad == [], f"footnote apparatus left in the text of {bad}"
