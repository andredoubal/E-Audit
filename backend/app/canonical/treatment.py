"""Which VAT treatment a record carries, decided from structured fields and nothing else.

The specification is explicit and it is the right call: **do not ask a model to guess a VAT
classification simply to populate a dashboard.** A wrong treatment does not merely mislabel a
row — it moves money between categories in a breakdown an auditor is reading to decide where the
difference is, which is worse than leaving the row uncategorised.

So classification runs down a ladder of signals, strongest first, and stops at the first one
that actually decides. Where none of them does, the record is `unclassified` and the dashboard
says so. `unclassified` is a real category with its own row in every breakdown; it is not a
bucket that quietly disappears.

The ladder, in order:

    1  an explicit treatment or tax-category column, read literally
    2  an export or import indicator, where the file carries one
    3  the VAT rate — 0 with a taxable amount reads as zero-rated, the standard rate as
       standard-rated, and any other rate is left alone rather than folded into standard
    4  VAT and taxable amounts together, where a rate can be derived from them reliably

Nothing infers a treatment from a description, a counterparty name or a filename.
"""
from __future__ import annotations

import re
from typing import Any

from .model import (EXEMPT, OUT_OF_SCOPE, STANDARD, UNCLASSIFIED, ZERO_RATED)

#: The standard rate for the jurisdiction this PoC serves. A jurisdiction fact, not a case fact,
#: and configurable rather than assumed: a rate change would otherwise silently reclassify every
#: historic record read after it.
STANDARD_RATE = 15.0

#: What a treatment column may say. Matched whole-word against the cell, lowercased.
_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ZERO_RATED, ("zero", "zero rated", "zero-rated", "zerorated", "z", "0%", "zr",
                  "export", "exports", "exported")),
    (EXEMPT, ("exempt", "exempted", "exemption", "e", "ex")),
    (OUT_OF_SCOPE, ("out of scope", "outside scope", "out-of-scope", "o", "oos",
                    "non taxable", "non-taxable", "not taxable", "n/a vat")),
    (STANDARD, ("standard", "standard rated", "standard-rated", "s", "sr", "15%", "std",
                "taxable")),
)


def _word_match(cell: Any) -> tuple[str, str] | None:
    text = str(cell or "").strip().lower()
    if not text:
        return None
    for treatment, spellings in _WORDS:
        if text in spellings:
            return treatment, f"the file states '{cell}'"
    # A cell that contains the word among others — "Zero rated export of goods" — still says
    # what it says. Whole-word so 'standard' does not match inside 'non-standard'.
    for treatment, spellings in _WORDS:
        for s in spellings:
            if len(s) > 2 and re.search(rf"\b{re.escape(s)}\b", text):
                return treatment, f"the file states '{cell}'"
    return None


def classify(*, stated: Any = None, indicator: Any = None, vat_rate: float | None = None,
             taxable_amount: float | None = None,
             vat_amount: float | None = None) -> tuple[str, str]:
    """(treatment, how it was decided). Returns `unclassified` rather than guessing."""

    # 1 · an explicit column wins over anything derived from figures
    if stated is not None:
        hit = _word_match(stated)
        if hit:
            return hit

    # 2 · an export/import indicator
    if indicator is not None:
        text = str(indicator or "").strip().lower()
        if text in ("export", "exports", "e", "x", "yes", "y", "true", "1"):
            return ZERO_RATED, f"the file flags this as an export ('{indicator}')"

    # 3 · the rate, where one is stated
    if vat_rate is not None:
        if vat_rate == 0:
            # A zero rate with no taxable amount says nothing — an empty row is not a
            # zero-rated supply.
            if taxable_amount:
                return ZERO_RATED, "the stated VAT rate is 0% on a taxable amount"
            return UNCLASSIFIED, "the stated VAT rate is 0% with no taxable amount to place it"
        if abs(vat_rate - STANDARD_RATE) < 0.01:
            return STANDARD, f"the stated VAT rate is {STANDARD_RATE:g}%"
        return (UNCLASSIFIED,
                f"the stated VAT rate is {vat_rate:g}%, which is neither the standard rate nor "
                f"zero — it is left uncategorised rather than folded into a box it was not "
                f"shown to belong to")

    # 4 · a rate derived from the two amounts, where both are present and the base is non-zero
    if taxable_amount and vat_amount is not None:
        derived = round(vat_amount / taxable_amount * 100, 2)
        if abs(derived - STANDARD_RATE) < 0.15:
            return STANDARD, (f"no rate column, but VAT is {derived:g}% of the taxable amount, "
                              f"which is the standard rate")
        if abs(derived) < 0.01:
            return ZERO_RATED, "no rate column, but no VAT is charged on a taxable amount"
        return (UNCLASSIFIED,
                f"no rate column, and VAT is {derived:g}% of the taxable amount, which matches "
                f"neither the standard rate nor zero")

    return UNCLASSIFIED, "the file carries nothing that decides the VAT treatment"
