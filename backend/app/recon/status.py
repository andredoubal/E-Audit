"""The five things a reconciliation is allowed to conclude, and the words it may not use.

This is a small module carrying a large rule. A reconciliation stage that can return
"non-compliant" will eventually return it, and once the word is in the data model it reaches
the screen, the report and the taxpayer letter. So the vocabulary is closed and the forbidden
words are checked rather than avoided by convention — `assert_neutral` raises, and the tests
call it over every explanation the engine produces.

The distinction between the five is not decoration:

* **reconciled** — the two sources agree within the tolerance declared for this comparison.
* **reconciled-with-explained-difference** — they differ, and deterministic analysis identified
  the whole of the cause: period scope, sign convention, rounding, an aggregation difference,
  a known adjustment. Nothing here is a matter for the auditor.
* **partially-reconciled** — part of the difference has a deterministic cause and a residual
  does not. This is the common real answer and the one a two-state model cannot express.
* **variance-identified** — a material difference remains with no deterministic cause. It is a
  question, not an allegation.
* **insufficient-evidence** — the comparison could not be run. One side is missing, or a column
  it needs is not readable. Never a variance: an absent document is a missing document.
"""
from __future__ import annotations

import re

RECONCILED = "reconciled"
EXPLAINED = "reconciled-with-explained-difference"
PARTIAL = "partially-reconciled"
VARIANCE = "variance-identified"
INSUFFICIENT = "insufficient-evidence"

STATUSES = (RECONCILED, EXPLAINED, PARTIAL, VARIANCE, INSUFFICIENT)

LABEL: dict[str, str] = {
    RECONCILED: "Reconciled",
    EXPLAINED: "Reconciled — difference explained",
    PARTIAL: "Partially reconciled",
    VARIANCE: "Variance identified",
    INSUFFICIENT: "Insufficient evidence",
}

#: How much attention each state deserves, for ordering and for the workstream summary. Not a
#: severity in the compliance sense — a variance is a question, and a question is not a finding.
ATTENTION: dict[str, int] = {
    VARIANCE: 4, PARTIAL: 3, INSUFFICIENT: 2, EXPLAINED: 1, RECONCILED: 0,
}

# ---------------------------------------------------------------- explained-difference causes
PERIOD = "period-scope"
SIGN = "sign-convention"
ROUNDING = "rounding"
AGGREGATION = "aggregation"
ADJUSTMENT = "known-adjustment"
DATA_QUALITY = "data-quality"

CAUSE_LABEL: dict[str, str] = {
    PERIOD: "Period scope",
    SIGN: "Sign convention",
    ROUNDING: "Rounding",
    AGGREGATION: "Aggregation difference",
    ADJUSTMENT: "Known adjustment",
    DATA_QUALITY: "Data quality",
}

# ---------------------------------------------------------------- the guard
#: Words that assert a compliance conclusion. None of them belongs to this stage: the numbers
#: cannot establish any of them, and a reconciliation that says one has skipped four stages of
#: the process and three people's judgement.
_FORBIDDEN = re.compile(
    r"\b(violation|violat\w*|non-?compliant|noncompliance|non-?compliance|fraud\w*|evasion|"
    r"evad\w*|illegal|unlawful|penalt\w*|invalid\s+deduction|not\s+deductible|"
    r"non-?deductible|underpaid|guilty|offence|offense)\b", re.I)


def assert_neutral(text: str, *, where: str = "") -> None:
    """Raise if a reconciliation sentence asserts a conclusion it cannot support."""
    hit = _FORBIDDEN.search(text or "")
    if hit:
        raise ValueError(
            f"the reconciliation stage may not use the word '{hit.group(0)}'"
            + (f" (in {where})" if where else "")
            + " — it states a compliance conclusion the numbers cannot establish, and this "
              "stage exists to keep that separate")


def is_neutral(text: str) -> bool:
    return _FORBIDDEN.search(text or "") is None
