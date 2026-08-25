"""What the investigation concluded, and what the auditor decided about it.

Until now the investigation was computed and thrown away: `GET /cases/{id}/investigate`
re-ran the whole pipeline on every request and returned the result without storing a row.
That is fine for a read-only display and impossible for anything else. An auditor cannot
accept a finding that does not exist between page loads; a hypothesis cannot be *re*-tested
after new evidence arrives if nothing remembers it was tested the first time; and a report
written next week cannot trace a sentence back to reasoning that was discarded on render.

So these tables hold the investigation's own memory. Three rules shape them:

* **A run is a fact, not a state.** `InvestigationRun` records one invocation of the
  orchestrator. Runs accumulate; the loop (investigate -> ask the taxpayer -> investigate
  again) is legible because each pass left a row behind.
* **A hypothesis is identified by what it claims, not by when it ran.** The natural key is
  `(case_id, hypothesis_id)` — the agents already use stable ids (`RG-S1`, `CA-01`) rather
  than generating fresh ones per run, so a re-run merges into the same row and a changed
  verdict is visible as a change rather than as a second, contradictory record.
* **A refuted hypothesis is kept.** What was investigated and ruled out is part of the audit
  trail; deleting it would leave the file looking as though nobody had asked.

`AuditorDecision` lives in `core` because it is a case fact — a person's act, not a computed
one. The hypotheses and runs live in `recon` alongside `GapFinding`, for the same reason it
does: they are derived working state that a re-run may legitimately change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Numeric, DateTime, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

CORE = "core"
RECON = "recon"

# What the investigation says about a hypothesis now. Wider than the adjudicator's own three
# verdicts because two of these are not the adjudicator's to reach: `partially-supported` is a
# reading of a confirmed amount against the difference it was meant to explain, and
# `pending-info` is set when the case is waiting on the taxpayer, which no test can detect.
STATUS_SUPPORTED = "supported"
STATUS_PARTIAL = "partially-supported"
STATUS_REFUTED = "refuted"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_PENDING_INFO = "pending-info"

# What the auditor decided. Only `accepted` reaches the report.
DECISION_ACCEPTED = "accepted"
DECISION_REJECTED = "rejected"
DECISION_MORE_INVESTIGATION = "needs-more-investigation"
DECISION_IRRELEVANT = "irrelevant"
DECISION_MORE_INFO = "needs-more-info"
DECISIONS = (DECISION_ACCEPTED, DECISION_REJECTED, DECISION_MORE_INVESTIGATION,
             DECISION_IRRELEVANT, DECISION_MORE_INFO)


class InvestigationRun(Base):
    """One invocation of the orchestrator over this case."""
    __tablename__ = "investigation_run"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)          # 1-based, per case
    # why this run happened: initial | new-evidence | auditor-requested | zatca-upload
    trigger: Mapped[str] = mapped_column(String(30), default="initial")
    note: Mapped[str] = mapped_column(String(300), default="")
    hypothesis_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)  # verdicts that moved
    conclusion: Mapped[str] = mapped_column(Text, default="")
    unexplained: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersistedHypothesis(Base):
    """A hypothesis and its current verdict, surviving between runs.

    `superseded_status` is the point of the table: when a re-run moves a verdict, the previous
    one is kept beside the new one so the case file reads "refuted in run 1, supported in run 2"
    rather than silently showing only the latest answer. An auditor who accepted a finding is
    entitled to know it changed under them.
    """
    __tablename__ = "persisted_hypothesis"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    hypothesis_id: Mapped[str] = mapped_column(String(30), index=True)   # RG-S1, CA-01, ...
    agent: Mapped[str] = mapped_column(String(60), default="")

    # provenance across runs
    first_seen_run: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_run: Mapped[int] = mapped_column(Integer, default=1)
    # a hypothesis whose preconditions no longer hold (its document was removed) stops being
    # proposed. The row stays, flagged, rather than vanishing mid-audit.
    stale: Mapped[bool] = mapped_column(default=False)

    # the claim — language only, exactly as the agent proposed it
    claim: Mapped[str] = mapped_column(Text, default="")
    why: Mapped[str] = mapped_column(Text, default="")
    outcome_code: Mapped[str] = mapped_column(String(20), default="")
    reason_code: Mapped[str] = mapped_column(String(10), default="")
    test_kind: Mapped[str] = mapped_column(String(40), default="")
    test_box: Mapped[str] = mapped_column(String(10), default="output")
    test_params: Mapped[dict] = mapped_column(JSON, default=dict)

    # the verdict — every figure here was computed by the adjudicator, never proposed
    status: Mapped[str] = mapped_column(String(30), default=STATUS_INCONCLUSIVE)
    superseded_status: Mapped[str] = mapped_column(String(30), default="")
    superseded_at_run: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)     # carries `basis`
    adjudicated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    # confidence — a deterministic composite over named signals. The band is what is shown;
    # the score and the signals are there so the band can be defended rather than trusted.
    confidence_score: Mapped[int] = mapped_column(Integer, default=0)
    confidence_band: Mapped[str] = mapped_column(String(20), default="")
    confidence_signals: Mapped[list] = mapped_column(JSON, default=list)

    contradictions: Mapped[list] = mapped_column(JSON, default=list)
    needs_info_note: Mapped[str] = mapped_column(Text, default="")
    linked_thread_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class HypothesisRegulatoryRef(Base):
    """The article behind a hypothesis, or an explicit record that none was found.

    `lookup_state` carries `not-found` as a real value. A regulatory basis that is simply
    absent from the table is indistinguishable from one nobody looked for, and "we could not
    confidently identify the applicable provision" is a different statement from silence —
    it is the one the auditor needs.

    Populated from Phase E onward; the table exists now so the hypothesis rows it hangs off
    never need reshaping later.
    """
    __tablename__ = "hypothesis_regulatory_ref"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    hypothesis_id: Mapped[str] = mapped_column(String(30), index=True)
    lookup_state: Mapped[str] = mapped_column(String(20), default="not-found")

    unit_id: Mapped[str] = mapped_column(String(64), default="")
    citation_label: Mapped[str] = mapped_column(String(200), default="")
    authority: Mapped[str] = mapped_column(String(60), default="")
    article_no: Mapped[str] = mapped_column(String(10), default="")
    clause: Mapped[str] = mapped_column(String(30), default="")
    effective_from: Mapped[str] = mapped_column(String(20), default="")
    effective_to: Mapped[str] = mapped_column(String(20), default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    retrieval_trace_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AuditorDecision(Base):
    """What the auditor decided about a hypothesis. Only `accepted` reaches the report.

    One row per hypothesis, updated in place — the auditor's current position, not a log of
    every click. `superseded_by_run` is set when a later run contradicts a decision that was
    already made: the decision is not rewritten, it is flagged, because an acceptance that
    quietly survived the evidence changing underneath it is exactly the failure this whole
    table exists to prevent.
    """
    __tablename__ = "auditor_decision"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    hypothesis_id: Mapped[str] = mapped_column(String(30), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str] = mapped_column(String(120), default="auditor")
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    # the status the hypothesis carried when the decision was made, so a later change is
    # detectable without re-deriving history
    decided_on_status: Mapped[str] = mapped_column(String(30), default="")
    superseded_by_run: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class AuditorFinding(Base):
    """A finding the auditor wrote themselves, with no agent hypothesis behind it.

    The agents cover what they can test. An auditor who sees something the roster has no test
    for must still be able to put it on the case file, and it must be distinguishable in the
    report from anything a model proposed — hence its own table rather than a synthetic
    hypothesis row wearing an agent's name.
    """
    __tablename__ = "auditor_finding"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    statement: Mapped[str] = mapped_column(Text)
    outcome_code: Mapped[str] = mapped_column(String(20), default="")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    basis: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="auditor")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
