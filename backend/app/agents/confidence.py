"""How much weight a hypothesis can bear — computed, banded, and defensible.

The auditors asked for a confidence score. The dangerous way to give them one is a percentage:
"65% confident" reads as a calibrated probability, as though 65 of 100 comparable cases turn out
this way. Nothing here can support that claim. The number would come from weights somebody chose,
and in a dispute it would be quoted back as though it had been measured.

So the number is computed and kept, but what is *shown* is a band. Expanding it shows which
signals fired and which did not, which is the part an auditor can actually argue with — "you say
limited confidence because there is no trial balance; here is the trial balance" is a useful
conversation in a way that "you say 65%" is not.

Two rules hold this together:

* **Confidence is not materiality.** A hypothesis can be strongly supported and worth very
  little, or weakly supported and worth a great deal. They are different questions and the UI
  shows them as two separate facts. Blending them into one number would hide both.
* **The model does not touch the number.** Every signal below is read from engine output —
  adjudicator detail, gap rows, the case's own documents. Claude may later be asked to phrase
  the explanation; it is never asked what the score is. Same division of labour as everywhere
  else: the numbers live in Python.

Weights sum to 1.0 and are named. They are a starting position, not a measurement, and the
signal breakdown is published precisely so that stays obvious.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- the signals, and what each is worth ------------------------------------------------
W_DATA_COMPLETE = 0.20      # is the evidence base itself complete
W_EVIDENCE = 0.20           # how much documentary evidence the test actually found
W_CONSISTENCY = 0.15        # does a second, independent source agree
W_REGULATORY = 0.20         # is there an article behind it
W_VALIDATED = 0.10          # did the engine recompute it deterministically
W_NO_CONTRADICTION = 0.10   # is there evidence pointing the other way
W_NO_PENDING = 0.05         # is it waiting on the taxpayer

_WEIGHTS = {
    "data_completeness": W_DATA_COMPLETE,
    "evidence_strength": W_EVIDENCE,
    "cross_source_consistency": W_CONSISTENCY,
    "regulatory_support": W_REGULATORY,
    "independently_validated": W_VALIDATED,
    "no_contradictory_evidence": W_NO_CONTRADICTION,
    "no_outstanding_information": W_NO_PENDING,
}
assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9

LABELS = {
    "data_completeness": "Data completeness",
    "evidence_strength": "Documentary evidence",
    "cross_source_consistency": "Cross-source consistency",
    "regulatory_support": "Regulatory support",
    "independently_validated": "Independently validated",
    "no_contradictory_evidence": "No contradictory evidence",
    "no_outstanding_information": "No outstanding information request",
}

# Bands. A hypothesis nobody could test does not get a low score, it gets no band at all —
# "insufficient" is a real verdict and reads differently from "weak".
BAND_STRONG, BAND_MODERATE, BAND_LIMITED, BAND_INSUFFICIENT = (
    "Strong", "Moderate", "Limited", "Insufficient")


def band_for(score: int) -> str:
    if score >= 75:
        return BAND_STRONG
    if score >= 50:
        return BAND_MODERATE
    if score >= 25:
        return BAND_LIMITED
    return BAND_INSUFFICIENT


@dataclass
class Signal:
    key: str
    value: float          # 0.0 - 1.0
    weight: float
    note: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key)

    @property
    def contribution(self) -> float:
        return round(self.value * self.weight * 100, 1)

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "value": round(self.value, 3),
                "weight": self.weight, "contribution": self.contribution, "note": self.note}


@dataclass
class Assessment:
    score: int
    band: str
    signals: list[Signal] = field(default_factory=list)

    @property
    def weakest(self) -> Signal | None:
        """The signal costing the most — what to fix to raise the band."""
        missing = [s for s in self.signals if s.value < 1.0]
        return min(missing, key=lambda s: s.value * s.weight) if missing else None

    def to_dict(self) -> dict:
        w = self.weakest
        return {"score": self.score, "band": self.band,
                "signals": [s.to_dict() for s in self.signals],
                "weakest": w.key if w else "",
                "improve": (f"{w.label.lower()} would raise this most" if w else "")}


# --- reading the signals off engine output ----------------------------------------------
# Each adjudicator test names its row count differently — `listing-vs-declared` counts the
# rows it summed, `blocked-input` the rows it matched, `invoice-conditions` the rows that
# failed. Reading only one of them would score a well-evidenced test as unevidenced, so the
# family is listed explicitly rather than guessed at.
_ROW_KEYS = ("rows_matched", "rows_failing", "rows_unsupported", "rows_outside",
             "rows", "rows_tested")


def _evidence_strength(detail: dict) -> tuple[float, str]:
    """How much the test actually found. The row count is the honest proxy: one line hit is a
    lead, forty is a pattern. Capped, because past a point more rows do not make it truer."""
    rows = next((detail[k] for k in _ROW_KEYS
                 if isinstance(detail.get(k), int)), None)
    if rows is None:
        examples = detail.get("examples") or []
        rows = len(examples) if examples else None
    if rows is None:
        return 0.5, "no row-level evidence recorded for this test"
    if rows <= 0:
        return 0.0, "no rows matched"
    if rows >= 20:
        return 1.0, f"{rows} rows matched"
    return round(0.4 + 0.6 * (rows / 20), 3), f"{rows} rows matched"


def _data_completeness(blocking_gaps: int) -> tuple[float, str]:
    if blocking_gaps <= 0:
        return 1.0, "the response meets the request"
    if blocking_gaps >= 5:
        return 0.0, f"{blocking_gaps} requested items still outstanding"
    return round(1.0 - (blocking_gaps / 5), 3), f"{blocking_gaps} requested items outstanding"


def assess(*, detail: dict | None = None, status: str = "", blocking_gaps: int = 0,
           corroborating_sources: int = 0, regulatory_state: str = "not-found",
           independently_validated: bool = False,
           contradictions: list | None = None) -> Assessment:
    """Build the assessment from engine facts only.

    `regulatory_state` is one of found / needs-validation / not-found. Until the regulatory
    corpus is wired in (Phase E) every hypothesis reads `not-found`, which is honest: there is
    no article behind any of them yet, and the band should say so rather than quietly assuming
    the leg is satisfied.
    """
    detail = detail or {}
    contradictions = contradictions or []

    ev_v, ev_n = _evidence_strength(detail)
    dc_v, dc_n = _data_completeness(blocking_gaps)

    if corroborating_sources >= 2:
        cs_v, cs_n = 1.0, f"{corroborating_sources} independent sources agree"
    elif corroborating_sources == 1:
        cs_v, cs_n = 0.6, "one corroborating source"
    else:
        cs_v, cs_n = 0.0, "no second source to corroborate against"

    reg = {"found": (1.0, "an article supports this"),
           "needs-validation": (0.5, "the provision needs legal validation"),
           }.get(regulatory_state, (0.0, "no regulatory basis identified yet"))

    signals = [
        Signal("data_completeness", dc_v, W_DATA_COMPLETE, dc_n),
        Signal("evidence_strength", ev_v, W_EVIDENCE, ev_n),
        Signal("cross_source_consistency", cs_v, W_CONSISTENCY, cs_n),
        Signal("regulatory_support", reg[0], W_REGULATORY, reg[1]),
        Signal("independently_validated", 1.0 if independently_validated else 0.0, W_VALIDATED,
               "the engine recomputed this deterministically" if independently_validated
               else "not independently recomputed"),
        Signal("no_contradictory_evidence", 0.0 if contradictions else 1.0, W_NO_CONTRADICTION,
               f"{len(contradictions)} contradictory observation(s)" if contradictions
               else "nothing on file points the other way"),
        Signal("no_outstanding_information", 0.0 if status == "pending-info" else 1.0,
               W_NO_PENDING,
               "waiting on the taxpayer" if status == "pending-info" else "nothing outstanding"),
    ]
    score = int(round(sum(s.value * s.weight for s in signals) * 100))

    # A refuted or untestable hypothesis has no confidence to report — the verdict already
    # says what happened, and a band beside it would only invite it to be read as a score
    # against the claim rather than against the evidence.
    band = BAND_INSUFFICIENT if status in ("refuted", "inconclusive") else band_for(score)
    return Assessment(score=score, band=band, signals=signals)
