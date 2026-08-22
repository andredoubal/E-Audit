"""Which article establishes the obligation behind each finding.

A finding an auditor can defend has three parts, and today the application produces only the
first and third:

    what the evidence shows  ·  why that matters in law  ·  what follows

The middle part is this table. `SAL-HIGHER` is not a finding because a spreadsheet totals more
than a box — it is a finding because **Article 14** imposes VAT on taxable supplies made in the
course of an economic activity, so supplies the records evidence but the return omits are
output tax that was due.

**This is a reviewed mapping, not retrieval.** Which provision a finding rests on is a legal
judgement, and asking a model to pick one per case would produce a different answer on two runs
over the same evidence — the one property a tax authority cannot defend. So the mapping is
written down, checked against the corpus at load time (`validate`), and a code with no entry
resolves to `not-found` rather than to whatever an embedding search ranks first.

`establishes` is a short editorial gloss so a finding reads as a sentence. It is **not** the
law: the article's own text travels with every citation, and the UI shows it, because a
paraphrase is what an auditor checks against the source rather than something to rely on.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Basis:
    outcome_code: str
    article: int                     # the provision the finding rests on
    establishes: str                 # editorial gloss, shown as such
    consequence: str                 # what follows when the evidence is as found
    supporting: tuple[int, ...] = ()  # provisions that bear on it without founding it


# Article 14 is the backbone: it is the charging provision, so every finding that says
# "supplies were made that the return does not reflect" rests on it.
_CHARGING = 14

BASES: tuple[Basis, ...] = (
    Basis("SAL-HIGHER", _CHARGING,
          "VAT is imposed on all taxable supplies of goods and services made by a taxable "
          "person in the Kingdom in the course of carrying on an economic activity",
          "taxable sales evidenced by the records but not reflected in the return may "
          "understate taxable supplies and the output VAT due",
          supporting=(45,)),
    Basis("SAL-UNDISCLOSED", _CHARGING,
          "VAT is imposed on all taxable supplies made in the course of an economic activity, "
          "whether or not they are declared",
          "supplies that were not disclosed in the return may understate taxable supplies and "
          "the output VAT due"),
    Basis("SAL-POS", _CHARGING,
          "VAT is imposed on all taxable supplies made in the course of an economic activity, "
          "however the consideration is received",
          "receipts evidenced by point-of-sale or bank records above the declared figure may "
          "understate taxable supplies and the output VAT due"),
    Basis("SAL-POSADJ", _CHARGING,
          "VAT is imposed on taxable supplies at the standard rate unless another rate or an "
          "exemption applies",
          "an adjustment to standard-rated sales follows from the point-of-sale records",
          supporting=(45,)),
    Basis("SAL-SECONDARY", _CHARGING,
          "VAT is imposed on taxable supplies made in the course of an economic activity — the "
          "activity as carried on, not only as registered",
          "revenue from an activity the registration does not disclose is still within the "
          "scope of the tax and may understate taxable supplies",
          supporting=(2,)),
    Basis("SAL-MISMATCH", 66,
          "a taxable person must keep records that allow the tax due to be established",
          "records that do not correspond to the declared supplies do not substantiate the "
          "return, and the declared figure cannot be verified from them",
          supporting=(_CHARGING,)),
    Basis("SAL-NOTB", 66,
          "a taxable person must keep records adequate to establish the tax due",
          "an excess of the records over the return that no trial balance reconciles is "
          "unsubstantiated, and the supplies behind it remain within the scope of the tax",
          supporting=(_CHARGING,)),
    Basis("DOC-INVOICE", 53,
          "a tax invoice must be issued for every taxable supply and must contain the "
          "particulars the article specifies",
          "supplies evidenced by documents that do not meet those conditions are not "
          "substantiated by a valid tax invoice"),
    Basis("DOC-CREDIT", 54,
          "a credit or debit note must be issued to adjust a supply already accounted for, and "
          "must contain the particulars the article specifies",
          "an adjustment resting on a note that does not meet those conditions does not "
          "reduce the output tax already accounted for",
          supporting=(40,)),
    Basis("PUR-NODOC", 49,
          "input tax is deductible only where the taxable person holds a tax invoice or "
          "customs documentation evidencing the supply",
          "input tax claimed with no supporting document behind it is not shown to be "
          "deductible",
          supporting=(53,)),
    Basis("PUR-BLOCKED", 50,
          "goods and services in the categories the article lists are deemed to be received "
          "outside the course of the economic activity, so the input tax on them is not "
          "deductible unless the article's own exceptions apply",
          "input tax claimed on those categories requires review against the article, "
          "including its exceptions, before the claim stands"),
    Basis("PUR-NOCOOP", 56,
          "the Authority may require a taxable person to provide the information and documents "
          "it needs to establish the tax due",
          "claims that depend on documents which were requested and not supplied cannot be "
          "substantiated",
          supporting=(66,)),
)

BY_CODE: dict[str, Basis] = {b.outcome_code: b for b in BASES}


def for_code(code: str) -> Basis | None:
    return BY_CODE.get(code or "")


def validate(corpus: dict) -> list[str]:
    """Every article this table names must exist in the corpus. Returns the problems found.

    Run at load time. A mapping that points at an article the corpus does not contain would
    produce a citation to nothing, which is worse than no citation.
    """
    numbers = {a["article"] for a in corpus.get("articles", [])}
    problems: list[str] = []
    for b in BASES:
        for n in (b.article, *b.supporting):
            if n not in numbers:
                problems.append(f"{b.outcome_code}: article {n} is not in the corpus")
    return problems


def uncovered(outcome_codes) -> list[str]:
    """Outcome codes with no legal basis recorded. Visible rather than silent."""
    return sorted(c for c in outcome_codes if c not in BY_CODE)
