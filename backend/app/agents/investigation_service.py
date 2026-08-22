"""Run the investigation, and remember what it concluded.

`orchestrator.investigate()` is deliberately untouched by this module. It is a single-pass
pipeline that takes engine facts and returns hypotheses with verdicts, and it is the part of
the system with the most careful work in it. Making it internally iterative — agents reacting
to each other mid-run — would mean rewriting tested logic to get something this wrapper
provides more safely: **iteration between runs**.

So a "loop" here is not a loop inside one call. It is:

    run 1 -> auditor sees a hypothesis needs taxpayer input -> correspondence -> new documents
          -> run 2 -> the same hypothesis, re-adjudicated against the larger evidence base

The merge key is `(case_id, hypothesis_id)`, which works because the agents use stable ids
(`RG-S1`, `CA-01`) rather than minting fresh ones per run. Run 2 finds run 1's row and updates
it, so a verdict that moves is visible *as a movement* — `superseded_status` keeps the old one
beside the new. A hypothesis that stops being proposed (its document was withdrawn) is marked
stale rather than deleted: what was investigated is part of the file even when it no longer
applies.

Nothing in this module calls a model. Confidence is arithmetic over engine output, the verdict
is the adjudicator's, and the decision is the auditor's.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from . import confidence as conf
from .findings import Finding, exposure
from .orchestrator import investigate
from .. import outcomes as oc
from ..models import (
    AuditCase, AuditorDecision, AuditorFinding, EventLog, GapFinding, InvestigationRun,
    PersistedHypothesis, TaxpayerResponse, VatReturn,
)
from ..models.investigation import (
    DECISION_ACCEPTED, STATUS_INCONCLUSIVE, STATUS_PARTIAL, STATUS_REFUTED, STATUS_SUPPORTED,
)
from ..recon_engine import reconcile_case
from ..requests import service as req_service
from . import calc_service


# ---------------------------------------------------------------- context assembly
def context_args(db, case: AuditCase) -> dict:
    """Everything the agents may reason over, read from the case as it stands right now.

    Extracted so the persisted run and the existing read-only `/investigate` endpoint cannot
    drift apart: two assemblies of the same context would eventually disagree about what the
    agents were shown, which is exactly the sort of discrepancy an audit trail exists to
    prevent.
    """
    case_id = case.case_id
    prior_returns = [
        {"form_number": r.form_number,
         "period_from": r.period_from.isoformat(), "period_to": r.period_to.isoformat(),
         "vat_amount": next((float(b.vat_amount) for b in r.boxes
                             if b.box_code == "standard_rate_sales" and b.direction == "sale"), 0.0)}
        for r in db.scalars(
            select(VatReturn).where(VatReturn.taxpayer_id == case.taxpayer_id,
                                    VatReturn.period_from < case.period_from)
            .order_by(VatReturn.period_from)).all()
    ]
    prior_cases = [
        {"case_id": pc.case_id, "root_cause_code": pc.root_cause_code,
         "result": pc.audit_result_type, "action": pc.action_taken}
        for pc in db.scalars(
            select(AuditCase).where(AuditCase.taxpayer_id == case.taxpayer_id,
                                    AuditCase.case_id != case_id,
                                    AuditCase.scenario_key != "corpus")).all()
    ]
    docs = [
        {"id": d.id, "filename": d.filename,
         "columns": (d.content or {}).get("columns", []),
         "rows": (d.content or {}).get("rows", [])}
        for d in req_service.documents(db, case_id)
    ]
    recorded = [
        {"seq": r.seq, "label": r.label, "amount": float(r.amount), "doc_name": r.doc_name}
        for r in db.scalars(
            select(TaxpayerResponse).where(TaxpayerResponse.case_id == case_id)
            .order_by(TaxpayerResponse.seq)).all()
    ]
    activities = list(case.taxpayer.economic_activities or []) if case.taxpayer else []
    gaps = [
        {"kind": g.kind, "item_label": g.item_label, "detail": g.detail, "severity": g.severity}
        for g in db.scalars(select(GapFinding).where(GapFinding.case_id == case_id)).all()
    ]
    req = req_service.current_request(db, case_id)
    requested = [{"key": i.catalog_key, "label": i.label} for i in (req.items if req else [])]
    return {"prior_returns": prior_returns, "prior_cases": prior_cases, "documents": docs,
            "recorded": recorded, "cr_activities": activities,
            "calculations": calc_service.listing(db, case_id), "gaps": gaps,
            "requested": requested}


# ---------------------------------------------------------------- status + signals
def status_for(adj, recon: dict) -> str:
    """The adjudicator's three verdicts, widened by one reading it cannot make itself.

    `partially-supported` is not a fourth verdict — it is `confirmed` seen against the size of
    the difference it was supposed to explain. A confirmed hypothesis that accounts for a tenth
    of the gap is true and insufficient at the same time, and reporting it as flatly "supported"
    invites it to be read as the answer.
    """
    if adj.status == "refuted":
        return STATUS_REFUTED
    if adj.status != "confirmed":
        return STATUS_INCONCLUSIVE
    amount = abs(float(adj.amount or 0))
    if amount == 0:
        return STATUS_SUPPORTED          # corroborating context, carries no money to weigh
    difference = abs(float(recon.get("unexplained") or 0))
    materiality = abs(float(recon.get("materiality") or 0))
    if amount + materiality >= difference:
        return STATUS_SUPPORTED
    return STATUS_PARTIAL


def _validated(detail: dict, amount: float) -> bool:
    """Did the engine derive this figure from counted rows, or merely assert it?"""
    counted = detail.get("rows_matched") is not None or bool(detail.get("examples"))
    return bool(counted and amount)


def assess_one(h, adj, *, status: str, recon: dict, blocking_gaps: int,
               all_adjudications: list, by_id: dict, control_confirmed: bool) -> conf.Assessment:
    detail = dict(adj.detail or {})
    basis = detail.get("basis", "")

    # Corroboration: another confirmed hypothesis resting on *different* evidence. Two readings
    # of one spreadsheet are not two sources, which is why this counts distinct bases and not
    # distinct hypotheses — the same reason `findings.exposure` counts a basis once.
    others = {
        (a.detail or {}).get("basis", "")
        for a in all_adjudications
        if a.status == "confirmed" and a.hypothesis_id != h.id
    }
    corroborating = len({b for b in others if b and b != basis})

    # A confirmed recomputation means a figure on this case was transcribed wrongly. The
    # orchestrator already reports it first "because everything downstream of it is unsafe
    # until it is fixed" — so it contradicts every other hypothesis on the case, including
    # ones that are otherwise well evidenced.
    contradictions = []
    if control_confirmed and h.test.kind != "recomputed-total":
        contradictions.append(
            "A figure recorded on this case could not be reproduced from its source document, "
            "so every amount here is provisional until that is resolved.")

    return conf.assess(
        detail=detail, status=status, blocking_gaps=blocking_gaps,
        corroborating_sources=corroborating,
        regulatory_state="not-found",       # until the corpus lands (Phase E), honestly absent
        independently_validated=_validated(detail, float(adj.amount or 0)),
        contradictions=contradictions,
    )


# ---------------------------------------------------------------- the run
def run(db, case: AuditCase, *, trigger: str = "initial", note: str = "") -> InvestigationRun:
    """Investigate, then merge the result into what the case already knew."""
    case_id = case.case_id
    recon = reconcile_case(db, case_id, persist=False)
    result = investigate(recon, **context_args(db, case))

    seq = 1 + len(db.scalars(
        select(InvestigationRun).where(InvestigationRun.case_id == case_id)).all())
    run_row = InvestigationRun(
        case_id=case_id, seq=seq, trigger=trigger, note=note,
        conclusion=result.conclusion, unexplained=round(float(result.unexplained), 2),
        hypothesis_count=len(result.hypotheses))
    db.add(run_row)
    db.flush()

    by_id = {h.id: h for h in result.hypotheses}
    adj_by_id = {a.hypothesis_id: a for a in result.adjudications}
    blocking = len([g for g in db.scalars(
        select(GapFinding).where(GapFinding.case_id == case_id)).all()
        if g.severity == "blocking"])
    control_confirmed = any(
        a.status == "confirmed" and by_id[a.hypothesis_id].test.kind == "recomputed-total"
        for a in result.adjudications if a.hypothesis_id in by_id)

    existing = {
        r.hypothesis_id: r for r in db.scalars(
            select(PersistedHypothesis).where(PersistedHypothesis.case_id == case_id)).all()
    }
    seen: set[str] = set()
    changed = 0

    for h in result.hypotheses:
        adj = adj_by_id.get(h.id)
        if adj is None:
            continue
        seen.add(h.id)
        status = status_for(adj, recon)
        assessment = assess_one(h, adj, status=status, recon=recon, blocking_gaps=blocking,
                                all_adjudications=result.adjudications, by_id=by_id,
                                control_confirmed=control_confirmed)
        row = existing.get(h.id)
        if row is None:
            row = PersistedHypothesis(
                case_id=case_id, hypothesis_id=h.id, first_seen_run=seq)
            db.add(row)
        else:
            # A verdict that moves is kept beside the one that replaced it. The auditor is
            # entitled to see that this was refuted last week and is supported today.
            if row.status and row.status != status:
                row.superseded_status = row.status
                row.superseded_at_run = seq
                changed += 1
            # An auditor who already ruled on this needs telling that the ground moved.
            if row.status != status:
                for d in db.scalars(select(AuditorDecision).where(
                        AuditorDecision.case_id == case_id,
                        AuditorDecision.hypothesis_id == h.id)).all():
                    d.superseded_by_run = seq

        row.agent = h.agent
        row.last_seen_run = seq
        row.stale = False
        row.claim, row.why = h.claim, h.why
        row.outcome_code, row.reason_code = h.outcome_code, h.reason_code
        row.test_kind, row.test_box = h.test.kind, h.test.box
        row.test_params = dict(h.test.params or {})
        row.status = status
        row.amount = round(float(adj.amount or 0), 2)
        row.explanation = adj.explanation
        row.detail = dict(adj.detail or {})
        row.adjudicated_at = datetime.now(timezone.utc)
        row.confidence_score = assessment.score
        row.confidence_band = assessment.band
        row.confidence_signals = [s.to_dict() for s in assessment.signals]
        row.contradictions = [
            s.note for s in assessment.signals
            if s.key == "no_contradictory_evidence" and s.value == 0.0]

    # Anything the roster stopped proposing: its preconditions no longer hold. Keep the row and
    # its last verdict, flagged, rather than removing evidence that the question was asked.
    for hid, row in existing.items():
        if hid not in seen:
            row.stale = True

    run_row.changed_count = changed
    db.add(EventLog(case_id=case_id, actor="system", action="investigation-run",
                    payload={"seq": seq, "trigger": trigger,
                             "hypotheses": len(seen), "changed": changed}))
    db.commit()
    db.refresh(run_row)
    return run_row


def ensure_run(db, case: AuditCase) -> InvestigationRun:
    """The first run, created on demand — so opening the tab shows a case, not an empty page."""
    latest = db.scalars(
        select(InvestigationRun).where(InvestigationRun.case_id == case.case_id)
        .order_by(InvestigationRun.seq.desc())).first()
    return latest or run(db, case, trigger="initial")


# ---------------------------------------------------------------- reading it back
def confirmed_findings(db, case: AuditCase) -> list[Finding]:
    """What the auditor accepted — the only thing the report is written from.

    The engine's own verdict is not the audit's conclusion. A hypothesis the adjudicator
    confirmed is a proposal that survived testing; it becomes a finding when a person says so.
    Everything else stays on the case file, visible in the investigation, and out of the
    report.

    Returns the same `Finding` objects the stateless path produces, so `audit_report.build`
    and `findings.exposure` need no change — they receive the familiar type, just a filtered
    set, and the basis-dedup arithmetic that keeps one excess from being assessed twice still
    applies. Auditor-authored findings come through the same door, tagged so the report can
    tell them apart from anything an agent proposed.
    """
    case_id = case.case_id
    decisions = {
        d.hypothesis_id: d for d in db.scalars(
            select(AuditorDecision).where(
                AuditorDecision.case_id == case_id,
                AuditorDecision.decision == DECISION_ACCEPTED)).all()
    }
    out: list[Finding] = []
    if decisions:
        rows = db.scalars(select(PersistedHypothesis).where(
            PersistedHypothesis.case_id == case_id,
            PersistedHypothesis.hypothesis_id.in_(list(decisions)))).all()
        for r in rows:
            outcome = oc.BY_CODE.get(r.outcome_code or "")
            if not outcome:
                # Accepted, but it names no vocabulary entry — a keying explanation, say.
                # It settled the investigation without being a defect the Authority states.
                continue
            d = decisions[r.hypothesis_id]
            out.append(Finding(
                code=outcome.code, statement=outcome.statement,
                amount=round(float(r.amount or 0), 2),
                effect=outcome.effect, direction=outcome.direction, agent=outcome.agent,
                hypothesis_id=r.hypothesis_id,
                basis=(r.detail or {}).get("basis", "") or r.hypothesis_id,
                why=r.why, explanation=r.explanation, detail=r.detail or {},
                source="agent-proposed-auditor-confirmed",
                confidence_band=r.confidence_band,
                decided_at=d.decided_at.isoformat() if d.decided_at else "",
                decided_by=d.decided_by, auditor_comment=d.comment))

    for f in db.scalars(select(AuditorFinding).where(AuditorFinding.case_id == case_id)
                        .order_by(AuditorFinding.seq)).all():
        outcome = oc.BY_CODE.get(f.outcome_code or "")
        out.append(Finding(
            code=f.outcome_code or "AUD-OWN",
            # The auditor's own words, not the vocabulary's — this did not come from an agent
            # and must not be dressed in the Authority's standard phrasing as though it had.
            statement=f.statement,
            amount=round(float(f.amount or 0), 2),
            effect=outcome.effect if outcome else oc.DOCUMENTATION,
            direction=outcome.direction if outcome else "",
            agent="Auditor", hypothesis_id="",
            basis=f.basis or f"auditor|{f.seq}",
            why="Recorded by the auditor during the review.",
            explanation=f.note, detail={},
            source="auditor-authored",
            decided_at=f.created_at.isoformat() if f.created_at else "",
            decided_by=f.created_by, auditor_comment=f.note))
    return sorted(out, key=lambda f: -abs(f.amount))


def state(db, case: AuditCase) -> dict:
    """The persisted investigation as the UI needs it: hypotheses, decisions, run history."""
    case_id = case.case_id
    runs = db.scalars(select(InvestigationRun).where(InvestigationRun.case_id == case_id)
                      .order_by(InvestigationRun.seq)).all()
    rows = db.scalars(select(PersistedHypothesis)
                      .where(PersistedHypothesis.case_id == case_id)).all()
    decisions = {
        d.hypothesis_id: d for d in db.scalars(
            select(AuditorDecision).where(AuditorDecision.case_id == case_id)).all()
    }

    def one(r: PersistedHypothesis) -> dict:
        d = decisions.get(r.hypothesis_id)
        return {
            "hypothesis_id": r.hypothesis_id, "agent": r.agent, "claim": r.claim, "why": r.why,
            "outcome_code": r.outcome_code, "reason_code": r.reason_code,
            "test": {"kind": r.test_kind, "box": r.test_box, "params": r.test_params or {}},
            "status": r.status, "superseded_status": r.superseded_status,
            "superseded_at_run": r.superseded_at_run,
            "amount": float(r.amount or 0), "explanation": r.explanation,
            "detail": r.detail or {},
            "confidence": {"score": r.confidence_score, "band": r.confidence_band,
                           "signals": r.confidence_signals or []},
            "contradictions": r.contradictions or [],
            "needs_info_note": r.needs_info_note,
            "first_seen_run": r.first_seen_run, "last_seen_run": r.last_seen_run,
            "stale": r.stale,
            "decision": ({"decision": d.decision, "comment": d.comment,
                          "decided_at": d.decided_at.isoformat() if d.decided_at else "",
                          "decided_on_status": d.decided_on_status,
                          "needs_reconfirmation": d.superseded_by_run is not None}
                         if d else None),
        }

    # Ordering: what the auditor has to deal with first. Undecided before decided, then by
    # amount — the same "biggest thing you have not looked at yet" rule the case queue uses.
    ordered = sorted(rows, key=lambda r: (
        r.stale,
        decisions.get(r.hypothesis_id) is not None,
        -abs(float(r.amount or 0)),
        r.hypothesis_id))

    accepted = [r for r in rows if (decisions.get(r.hypothesis_id) is not None
                                    and decisions[r.hypothesis_id].decision == "accepted")]
    return {
        "case_id": case_id,
        "runs": [{"seq": r.seq, "trigger": r.trigger, "note": r.note,
                  "hypothesis_count": r.hypothesis_count, "changed_count": r.changed_count,
                  "conclusion": r.conclusion, "unexplained": float(r.unexplained or 0),
                  "started_at": r.started_at.isoformat() if r.started_at else ""}
                 for r in runs],
        "hypotheses": [one(r) for r in ordered],
        "counts": {
            "total": len(rows),
            "decided": len([r for r in rows if r.hypothesis_id in decisions]),
            "accepted": len(accepted),
            "needs_reconfirmation": len([
                d for d in decisions.values() if d.superseded_by_run is not None]),
        },
    }
