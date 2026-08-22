from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Taxpayer, VatReturn, Invoice, AuditCase, Rule, TaxpayerResponse, EventLog, GapFinding,
    AuditorCalculation, AuditorDecision, AuditorFinding, PersistedHypothesis,
)
from ..requests import service as req_service
from ..requests import from_email
from ..agents import calc_service
from ..agents import investigation_service as inv_service
from ..agents.correspondence import draft_followup, draft_request
from ..recon_engine import reconcile_case
from ..priority import score_case
from ..pipeline.rules import coded_rules as wired_codes
from ..rule_taxonomy import REASON_CODES, STAGES, KINDS
from ..scope import scope_card
from ..dossier import collect as collect_dossier
from ..llm.service import llm
from ..config import settings

router = APIRouter(prefix="/api")


def _rule_rows(db: Session) -> list[dict]:
    return [
        {"code": r.code, "family": r.family, "title": r.title,
         "explains_gap": r.explains_gap, "severity": r.severity}
        for r in db.scalars(select(Rule).order_by(Rule.code)).all()
    ]


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return {
        "status": "ok",
        "taxpayers": db.scalar(select(func.count()).select_from(Taxpayer)),
        "cases": db.scalar(select(func.count()).select_from(AuditCase)),
        "rules": db.scalar(select(func.count()).select_from(Rule)),
    }


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    """The rule library, each row carrying its taxonomy and whether the engine can fire it.

    `wired` comes from the reconciling-item registry rather than a hard-coded list in the
    UI, so a rule added to the registry is badged live without a frontend change.
    """
    wired = wired_codes()
    rows = db.scalars(select(Rule).order_by(Rule.code)).all()
    return [
        {
            "code": r.code, "family": r.family, "title": r.title,
            "explains_gap": r.explains_gap, "gap_band": r.gap_band,
            "severity": r.severity, "severity_band": r.severity_band,
            "root_cause_code": r.root_cause_code, "enabled": r.enabled,
            "rule_kind": r.rule_kind, "stage": r.stage,
            "reason_code": r.reason_code,
            "reason_label": REASON_CODES.get(r.reason_code, ("", ""))[1],
            "wired": r.code in wired,
        }
        for r in rows
    ]


@router.get("/reason-codes")
def list_reason_codes():
    """The difference taxonomy: why a return may legitimately differ from the e-invoices."""
    return {
        "kinds": list(KINDS),
        "stages": list(STAGES),
        "codes": [
            {"code": code, "group": group, "label": label}
            for code, (group, label) in REASON_CODES.items()
        ],
    }


@router.get("/scope")
def scope():
    """What this PoC reconciles, and what it deliberately leaves out."""
    return scope_card()


@router.get("/cases/{case_id}/dossier")
def case_dossier(case_id: str, db: Session = Depends(get_db)):
    """Everything ZATCA already holds on this taxpayer and period, in one call.

    The auditors start a case by investigating internal data — returns, e-invoicing, imports and
    exports, history, prior audits, financials — and only then decide what is genuinely missing.
    Doing that today means opening several systems. This is that step, assembled.
    """
    try:
        return collect_dossier(db, case_id)
    except LookupError:
        raise HTTPException(404, "case not found")


@router.get("/cases/{case_id}/precedent")
def case_precedent(case_id: str, db: Session = Depends(get_db)):
    """What comparable closed cases turned out to be, and which evidence actually closed them.

    Deterministic retrieval over labelled closed cases — no model, no embeddings. Every figure
    is a count or a median taken here, which is what makes the ranked list reproducible.
    """
    from ..agents.precedent_analyst import brief

    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    return brief(db, c).to_dict()


def _case_or_404(db: Session, case_id: str) -> AuditCase:
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    return c


@router.get("/cases/{case_id}/investigate")
def investigate_case(case_id: str, db: Session = Depends(get_db)):
    """Run the multi-agent investigation over the reconciled case, without storing it.

    Evidence agents propose typed hypotheses; a deterministic adjudicator settles each one
    against the engine's figures. No model is involved in any number here, and the whole
    loop runs without credentials — the agents are pattern detectors, not writers.

    This is the stateless view. `/cases/{id}/investigation` is the same pipeline with its
    conclusions kept, which is what the auditor rules on; both assemble their context from
    `investigation_service.context_args` so the two can never disagree about what the agents
    were shown.
    """
    from ..agents.orchestrator import investigate

    c = _case_or_404(db, case_id)
    recon = reconcile_case(db, case_id, persist=False)
    return investigate(recon, **inv_service.context_args(db, c)).model_dump()


# ======================================================= the investigation, remembered
#
# `/investigate` above recomputes and returns; it never stored anything, which is why an
# auditor could read a hypothesis but not rule on one. These endpoints work over the
# persisted view instead: the same pipeline, with its conclusions kept so a decision has
# something to attach to and a re-run has something to compare against.


@router.get("/cases/{case_id}/investigation")
def investigation_state(case_id: str, db: Session = Depends(get_db)):
    """The persisted investigation: hypotheses, their verdicts, and what the auditor decided.

    Runs the investigation once on first read so opening the tab shows a worked case rather
    than an empty page asking to be told to start.
    """
    c = _case_or_404(db, case_id)
    inv_service.ensure_run(db, c)
    return inv_service.state(db, c)


class RunIn(BaseModel):
    trigger: str = "auditor-requested"
    note: str = ""


@router.post("/cases/{case_id}/investigation/run")
def investigation_run(case_id: str, body: RunIn | None = None,
                      db: Session = Depends(get_db)):
    """Investigate again, merging into what the case already concluded.

    This is the loop: new documents arrive, the auditor re-runs, and each hypothesis is
    re-adjudicated against the larger evidence base. A verdict that moves keeps the old one
    beside it, and any decision made before the ground shifted is flagged rather than
    silently overwritten.
    """
    c = _case_or_404(db, case_id)
    body = body or RunIn()
    run = inv_service.run(db, c, trigger=body.trigger, note=body.note)
    state = inv_service.state(db, c)
    state["last_run"] = {"seq": run.seq, "changed_count": run.changed_count}
    return state


class DecisionIn(BaseModel):
    decision: str
    comment: str = ""


@router.post("/cases/{case_id}/hypotheses/{hypothesis_id}/decision")
def decide(case_id: str, hypothesis_id: str, body: DecisionIn,
           db: Session = Depends(get_db)):
    """Record what the auditor decided about one hypothesis.

    Only `accepted` reaches the report. The rest are kept because what was rejected, and
    why, is as much a part of the audit file as what was upheld — and because an auditor
    who reopens the case in a month needs to see that a question was already answered.
    """
    from ..models.investigation import DECISIONS

    c = _case_or_404(db, case_id)
    if body.decision not in DECISIONS:
        raise HTTPException(422, f"decision must be one of {', '.join(DECISIONS)}")
    h = db.scalar(select(PersistedHypothesis).where(
        PersistedHypothesis.case_id == case_id,
        PersistedHypothesis.hypothesis_id == hypothesis_id))
    if h is None:
        raise HTTPException(404, "hypothesis not found on this case")

    row = db.scalar(select(AuditorDecision).where(
        AuditorDecision.case_id == case_id,
        AuditorDecision.hypothesis_id == hypothesis_id))
    if row is None:
        row = AuditorDecision(case_id=case_id, hypothesis_id=hypothesis_id)
        db.add(row)
    row.decision = body.decision
    row.comment = (body.comment or "").strip()
    row.decided_on_status = h.status
    row.superseded_by_run = None          # deciding again clears the re-confirmation flag
    db.add(EventLog(case_id=case_id, actor="auditor", action="hypothesis-decision",
                    payload={"hypothesis_id": hypothesis_id, "decision": body.decision,
                             "status": h.status}))
    db.commit()
    return inv_service.state(db, c)


class AuditorFindingIn(BaseModel):
    statement: str
    outcome_code: str = ""
    amount: float = 0.0
    note: str = ""


@router.post("/cases/{case_id}/auditor-findings")
def add_auditor_finding(case_id: str, body: AuditorFindingIn,
                        db: Session = Depends(get_db)):
    """A finding the auditor wrote themselves.

    The agents cover what they have tests for. Anything else still has to be recordable, and
    it has to stay distinguishable in the report from what a model proposed.
    """
    _case_or_404(db, case_id)
    statement = (body.statement or "").strip()
    if not statement:
        raise HTTPException(422, "statement is required")
    seq = 1 + len(db.scalars(select(AuditorFinding).where(
        AuditorFinding.case_id == case_id)).all())
    row = AuditorFinding(case_id=case_id, seq=seq, statement=statement,
                         outcome_code=(body.outcome_code or "").strip(),
                         amount=round(float(body.amount or 0), 2),
                         basis=f"auditor|{seq}", note=(body.note or "").strip())
    db.add(row)
    db.add(EventLog(case_id=case_id, actor="auditor", action="auditor-finding-added",
                    payload={"seq": seq, "statement": statement[:200]}))
    db.commit()
    return {"seq": seq, "statement": statement, "amount": float(row.amount),
            "outcome_code": row.outcome_code, "note": row.note, "basis": row.basis}


@router.get("/cases/{case_id}/auditor-findings")
def list_auditor_findings(case_id: str, db: Session = Depends(get_db)):
    _case_or_404(db, case_id)
    return [{"seq": r.seq, "statement": r.statement, "amount": float(r.amount or 0),
             "outcome_code": r.outcome_code, "note": r.note, "basis": r.basis,
             "created_at": r.created_at.isoformat() if r.created_at else ""}
            for r in db.scalars(select(AuditorFinding)
                                .where(AuditorFinding.case_id == case_id)
                                .order_by(AuditorFinding.seq)).all()]


class RulePatch(BaseModel):
    enabled: bool


@router.patch("/rules/{code}")
def update_rule(code: str, body: RulePatch, db: Session = Depends(get_db)):
    """Enable/disable a detection rule.

    Disabling a wired rule changes which documents qualify — e.g. turning COR-01 off means
    credit notes no longer belong in the box, so they leave the qualifying set entirely.
    """
    r = db.get(Rule, code)
    if not r:
        raise HTTPException(404, "rule not found")
    r.enabled = body.enabled
    db.commit()
    return {"code": r.code, "enabled": r.enabled}


@router.delete("/rules/{code}")
def delete_rule(code: str, db: Session = Depends(get_db)):
    r = db.get(Rule, code)
    if not r:
        raise HTTPException(404, "rule not found")
    db.delete(r)
    db.commit()
    return {"status": "deleted", "code": code}


@router.get("/cases")
def list_cases(db: Session = Depends(get_db)):
    """Open cases, each scored by the composite priority engine, sorted most-urgent first."""
    cases = db.scalars(
        select(AuditCase).where(AuditCase.status != "closed").order_by(AuditCase.case_id)
    ).all()
    rows = [
        {
            "case_id": c.case_id,
            "taxpayer": c.taxpayer.name,
            "vat_no": c.taxpayer.vat_registration_number,
            "sector": c.taxpayer.ind_sector,
            "period": f"{c.period_from:%Y-%m-%d} → {c.period_to:%Y-%m-%d}",
            "reason": c.case_reason_code,
            "risk": c.risk_category,
            "referral_priority": c.vat_priority,
            "status": c.status,
            "scenario": c.scenario_key,
            "priority": score_case(db, c),
        }
        for c in cases
    ]
    rows.sort(key=lambda r: r["priority"]["score"], reverse=True)
    return rows


# ------------------------------------------------------------------- manual case creation
# There is no live risk-engine integration in this PoC — every case up to now has come from
# a seed script. This is the only way an auditor can actually put a case in front of the
# tool themselves, so it doubles as the one place several report-template fields
# ("Case Creation Reason", "Assigned Audit Team information", taxpayer contact details) can
# ever be filled with something real instead of [not held]. See reporting/audit_report.py.
class NewCaseTaxpayerIn(BaseModel):
    name: str
    vat_registration_number: str
    ind_sector: str = ""
    economic_activities: list = []
    contact_phone: str = ""
    contact_email: str = ""
    contact_address: str = ""
    audited_before: bool = False
    audited_before_note: str = ""


class NewCaseIn(BaseModel):
    case_id: str = ""                    # blank = auto-generate the next CASE-{year}-NNNN
    period_from: date
    period_to: date
    creation_date: date | None = None     # blank = today
    creation_reason: str = ""             # one of audit_report.CREATION_REASONS
    audit_manager: str = ""
    audit_supervisor: str = ""
    audit_officer: str = ""
    taxpayer: NewCaseTaxpayerIn


def _next_case_id(db: Session, year: int) -> str:
    """CASE-{year}-NNNN, one past whatever already exists for that year.

    Deliberately not the CASE-H{year}-... shape corpus.py uses for the historical/precedent
    corpus — that prefix marks a different population and must not collide with live cases.
    """
    prefix = f"CASE-{year}-"
    existing = db.scalars(
        select(AuditCase.case_id).where(AuditCase.case_id.like(f"{prefix}%"))
    ).all()
    max_seq = 0
    for cid in existing:
        tail = cid[len(prefix):]
        if tail.isdigit():
            max_seq = max(max_seq, int(tail))
    return f"{prefix}{max_seq + 1:04d}"


@router.post("/cases")
def create_case(body: NewCaseIn, db: Session = Depends(get_db)):
    """Create a case by hand. Reuses the taxpayer by VAT registration number if one already
    exists, rather than erroring on the unique constraint — an auditor re-testing with the
    same synthetic TIN should update the record, not be blocked by it."""
    tp_in = body.taxpayer
    if not tp_in.name.strip() or not tp_in.vat_registration_number.strip():
        raise HTTPException(422, "taxpayer name and VAT registration number are required")
    if body.period_from > body.period_to:
        raise HTTPException(422, "period_from must not be after period_to")

    tp = db.scalar(select(Taxpayer).where(
        Taxpayer.vat_registration_number == tp_in.vat_registration_number.strip()))
    if tp:
        tp.name = tp_in.name.strip()
        tp.ind_sector = tp_in.ind_sector.strip()
        tp.economic_activities = tp_in.economic_activities
        tp.contact_phone = tp_in.contact_phone.strip()
        tp.contact_email = tp_in.contact_email.strip()
        tp.contact_address = tp_in.contact_address.strip()
        tp.audited_before = tp_in.audited_before
        tp.audited_before_note = tp_in.audited_before_note.strip()
    else:
        tp = Taxpayer(
            vat_registration_number=tp_in.vat_registration_number.strip(),
            name=tp_in.name.strip(), ind_sector=tp_in.ind_sector.strip(),
            economic_activities=tp_in.economic_activities,
            contact_phone=tp_in.contact_phone.strip(), contact_email=tp_in.contact_email.strip(),
            contact_address=tp_in.contact_address.strip(),
            audited_before=tp_in.audited_before,
            audited_before_note=tp_in.audited_before_note.strip(),
        )
        db.add(tp)
    db.flush()   # assign tp.id for a brand-new taxpayer

    creation_date = body.creation_date or date.today()
    case_id = body.case_id.strip() or _next_case_id(db, creation_date.year)
    if db.scalar(select(AuditCase).where(AuditCase.case_id == case_id)):
        raise HTTPException(409, f"case {case_id} already exists")

    db.add(AuditCase(
        case_id=case_id, taxpayer_id=tp.id,
        period_from=body.period_from, period_to=body.period_to,
        audit_type="desk", status="referred", referral_date=creation_date,
        creation_reason=body.creation_reason.strip(),
        audit_manager=body.audit_manager.strip(),
        audit_supervisor=body.audit_supervisor.strip(),
        audit_officer=body.audit_officer.strip(),
    ))
    db.add(EventLog(case_id=case_id, actor="auditor", action="case-created",
                    payload={"taxpayer": tp.name, "vat_no": tp.vat_registration_number}))
    db.commit()
    return {"case_id": case_id}


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Executive tiles — aggregated live across every open case's deterministic reconciliation."""
    cases = db.scalars(select(AuditCase).where(AuditCase.status != "closed")).all()
    exposure = accounted = differences = 0.0
    supported = findings = review = 0
    for c in cases:
        try:
            r = reconcile_case(db, c.case_id, persist=False)
        except Exception:
            continue
        combined = r.get("combined") or {}
        differences += abs(r["difference"])
        accounted += float(r.get("evidence_total", 0.0))
        state = combined.get("state", r["state"])          # worst of output + input boxes
        if state == "potential-finding":
            exposure += float(combined.get("total_exposure", max(r["unexplained"], 0.0)))
            findings += 1
        elif state == "unresolved":
            review += 1
        elif state == "supported":
            supported += 1
    n = len(cases)
    return {
        "open_cases": n,
        "exposure_total": round(exposure, 2),
        "difference_total": round(differences, 2),
        "accounted_total": round(accounted, 2),
        "auto_clearable": supported,
        "auto_clearable_pct": round(supported / n, 4) if n else 0.0,
        "needs_action": findings + review,
        "findings": findings,
        "to_review": review,
    }


@router.post("/admin/reseed")
def reseed_demo():
    """Restore the demo database to its seeded state. Synthetic data only — drops and rebuilds all tables."""
    if not settings.data_is_synthetic:
        raise HTTPException(403, "reseed is disabled unless the data is synthetic")
    from ..seed.seed import run as _run
    _run()
    return {"status": "ok", "message": "Demo data restored"}


@router.get("/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    tp = c.taxpayer
    vret = db.scalar(
        select(VatReturn).where(
            VatReturn.taxpayer_id == tp.id,
            VatReturn.period_from == c.period_from,
            VatReturn.current_flag.is_(True),
        )
    )
    n_inv = db.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.taxpayer_id == tp.id)
    )
    return {
        "case_id": c.case_id,
        "status": c.status,
        "reason": c.case_reason_code,
        "risk": c.risk_category,
        "priority": c.vat_priority,
        "scenario": c.scenario_key,
        "period": f"{c.period_from:%Y-%m-%d} → {c.period_to:%Y-%m-%d}",
        "taxpayer": {
            "name": tp.name, "vat_no": tp.vat_registration_number,
            "sector": tp.ind_sector, "size": tp.business_size,
            "accounting_method": tp.accounting_method, "resident": tp.resident_flag,
            "vat_group": tp.vat_group_rep_flag,
        },
        "return": None if not vret else {
            "form_number": vret.form_number,
            "data_version": vret.data_version,
            "submission_date": vret.submission_date and vret.submission_date.isoformat(),
            "filing_deadline": vret.filing_deadline and vret.filing_deadline.isoformat(),
            "total_vat_due": float(vret.total_vat_due),
            "net_due_vat": float(vret.net_due_vat),
            "boxes": [
                {
                    "box_code": b.box_code, "label": b.box_label, "direction": b.direction,
                    "category": b.category, "rate": b.rate,
                    "base_amount": float(b.base_amount), "vat_amount": float(b.vat_amount),
                    "adjustment": float(b.adjustment),
                }
                for b in vret.boxes
            ],
        },
        "invoice_count": n_inv,
    }


@router.get("/cases/{case_id}/reconcile")
def reconcile(case_id: str, db: Session = Depends(get_db)):
    """Qualify the e-invoice lines, sum what belongs to this box, and compare with the return."""
    try:
        return reconcile_case(db, case_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- taxpayer response loop
class ResponseIn(BaseModel):
    label: str
    amount: float           # SAR the evidence accounts for (auditor-confirmed)
    doc_name: str = ""


@router.get("/cases/{case_id}/responses")
def list_responses(case_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(TaxpayerResponse).where(TaxpayerResponse.case_id == case_id)
        .order_by(TaxpayerResponse.seq)
    ).all()
    return [{"seq": r.seq, "code": r.code, "label": r.label,
             "amount": float(r.amount), "doc_name": r.doc_name} for r in rows]


@router.post("/cases/{case_id}/responses")
def add_response(case_id: str, body: ResponseIn, db: Session = Depends(get_db)):
    """Record evidence the taxpayer supplied, then regenerate the whole reconciliation."""
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    if not body.label.strip() or abs(body.amount) < 0.005:
        raise HTTPException(422, "a description and a non-zero amount are required")
    n = db.scalar(select(func.count()).select_from(TaxpayerResponse)
                  .where(TaxpayerResponse.case_id == case_id)) or 0
    seq = n + 1
    db.add(TaxpayerResponse(
        case_id=case_id, seq=seq, code=f"RESP-{seq:02d}",
        label=body.label.strip(), amount=abs(body.amount), doc_name=body.doc_name.strip(),
    ))
    db.add(EventLog(case_id=case_id, actor="auditor", action="taxpayer-response",
                    payload={"seq": seq, "amount": abs(body.amount), "doc": body.doc_name}))
    db.commit()
    return reconcile_case(db, case_id)


@router.delete("/cases/{case_id}/responses/{seq}")
def delete_response(case_id: str, seq: int, db: Session = Depends(get_db)):
    db.execute(delete(TaxpayerResponse).where(
        TaxpayerResponse.case_id == case_id, TaxpayerResponse.seq == seq))
    db.add(EventLog(case_id=case_id, actor="auditor", action="taxpayer-response-removed",
                    payload={"seq": seq}))
    db.commit()
    return reconcile_case(db, case_id)


# ------------------------------------------------- information request / response loop


@router.get("/cases/{case_id}/plan")
def request_plan(case_id: str, db: Session = Depends(get_db)):
    """What to ask the taxpayer for — and what was dropped because ZATCA already holds it."""
    from ..requests.planner import plan

    return plan(db, _case_or_404(db, case_id)).to_dict()


@router.get("/cases/{case_id}/requests")
def request_loop(case_id: str, db: Session = Depends(get_db)):
    """Every round of correspondence on this case: items, documents received, and gaps."""
    return req_service.state(db, _case_or_404(db, case_id))


@router.post("/cases/{case_id}/requests")
def open_round(case_id: str, db: Session = Depends(get_db)):
    """Open the next round from the current plan, as a draft the auditor approves."""
    case = _case_or_404(db, case_id)
    current = req_service.current_request(db, case_id)
    if current is not None and current.status not in ("satisfied",):
        raise HTTPException(409, f"round {current.seq} is still {current.status}")
    req = req_service.open_request(db, case)
    drafted = draft_request(case, case.taxpayer, req)
    req.body, req.body_source = drafted["text"], drafted["source"]
    db.add(EventLog(case_id=case_id, actor="auditor", action="request-drafted",
                    payload={"round": req.seq, "items": len(req.items)}))
    db.commit()
    return {**req_service.state(db, case), "draft": drafted}


@router.post("/cases/{case_id}/requests/{seq}/issue")
def issue_round(case_id: str, seq: int, db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    req = next((r for r in req_service.rounds(db, case_id) if r.seq == seq), None)
    if req is None:
        raise HTTPException(404, "round not found")
    req_service.issue(db, req)
    db.add(EventLog(case_id=case_id, actor="auditor", action="request-issued",
                    payload={"round": seq}))
    db.commit()
    return req_service.state(db, case)


@router.post("/cases/{case_id}/documents")
async def upload_document(case_id: str, file: UploadFile = File(...),
                          item_id: int | None = Form(None),
                          db: Session = Depends(get_db)):
    """Record a file the taxpayer sent, extract it, and re-run the completeness checks."""
    case = _case_or_404(db, case_id)
    req = req_service.current_request(db, case_id)
    if req is None:
        raise HTTPException(409, "no information request has been issued on this case")
    data = await file.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "file too large for the demo (8 MB limit)")
    doc = req_service.record_document(
        db, case=case, req=req, item_id=item_id, filename=file.filename or "response",
        data=data, file_format=(file.filename or "").rsplit(".", 1)[-1].lower())
    report = req_service.run_checks(db, case)
    db.add(EventLog(case_id=case_id, actor="taxpayer", action="document-received",
                    payload={"round": req.seq, "file": doc.filename,
                             "gaps": len(report.gaps)}))
    db.commit()
    return {**req_service.state(db, case), "report": report.to_dict()}


@router.post("/cases/{case_id}/requests/check")
def recheck(case_id: str, db: Session = Depends(get_db)):
    """Re-run the deterministic completeness checks over what has been received."""
    case = _case_or_404(db, case_id)
    report = req_service.run_checks(db, case)
    db.commit()
    return {**req_service.state(db, case), "report": report.to_dict()}


@router.get("/cases/{case_id}/followup")
def followup(case_id: str, db: Session = Depends(get_db)):
    """Draft the chase letter from the outstanding gaps only."""
    case = _case_or_404(db, case_id)
    req = req_service.current_request(db, case_id)
    if req is None:
        raise HTTPException(409, "no information request has been issued on this case")
    gaps = db.scalars(
        select(GapFinding).where(GapFinding.case_id == case_id, GapFinding.round == req.seq,
                                 GapFinding.severity == "blocking")
        .order_by(GapFinding.id)).all()
    return draft_followup(case, case.taxpayer, req, list(gaps))


@router.get("/cases/{case_id}/lifecycle")
def lifecycle(case_id: str, db: Session = Depends(get_db)):
    """Where this case is in the five-stage run, and whose move it is.

    Derived from the case's own data rather than a stored status, so it cannot fall out of
    step with reality. No stage advances by itself — every gate is a human decision (§6).
    """
    from ..casefile import status as case_status

    return case_status(db, _case_or_404(db, case_id))


@router.get("/cases/{case_id}/verdict")
def verdict(case_id: str, db: Session = Depends(get_db)):
    """Draft the taxpayer letter reporting the outcome. §8's second administrative burden."""
    from ..agents.correspondence import draft_verdict
    from ..agents.orchestrator import investigate

    case = _case_or_404(db, case_id)
    recon = reconcile_case(db, case_id, persist=False)
    inv = investigate_case(case_id, db)
    return draft_verdict(case, case.taxpayer, recon, inv, inv.get("findings"))


# ============================================================ THE AUDIT REPORT
# The auditors asked for two outputs, not one: the email and the audit report. This is the
# second. It targets the Authority's own template rather than a layout of ours, and a field the
# case cannot answer says which kind of gap it is instead of being filled from a guess.

def _audit_report(db: Session, case_id: str) -> dict:
    """Assemble the report from everything on the case file.

    The findings here are the ones the **auditor accepted**, not every hypothesis the engine
    confirmed. That distinction is the whole point: an adjudicated hypothesis is a proposal
    that survived testing, and it becomes a finding when a person says so. A case with nothing
    accepted yet reports no finding — which is correct, not broken.
    """
    from ..agents.calc_service import documents_for
    from ..agents.findings import exposure
    from ..reporting import audit_report

    case = _case_or_404(db, case_id)
    recon = reconcile_case(db, case_id, persist=False)
    inv_service.ensure_run(db, case)
    confirmed = inv_service.confirmed_findings(db, case)
    runs = inv_service.state(db, case)["runs"]
    inv = {"findings": [f.to_dict() for f in confirmed],
           "exposure": exposure(confirmed),
           "conclusion": runs[-1]["conclusion"] if runs else ""}

    req = req_service.current_request(db, case_id)
    requested = [{"key": i.catalog_key, "label": i.label} for i in (req.items if req else [])]
    gaps = [{"item_label": g.item_label, "kind": g.kind, "severity": g.severity,
             "detail": g.detail, "citation": g.citation}
            for g in db.scalars(select(GapFinding)
                                .where(GapFinding.case_id == case_id,
                                       GapFinding.round == (req.seq if req else 1))
                                .order_by(GapFinding.id)).all()]
    return audit_report.build(
        case, case.taxpayer, recon, inv,
        priority=score_case(db, case), requested=requested,
        received=documents_for(db, case_id), gaps=gaps)


@router.get("/cases/{case_id}/audit-report")
def audit_report_view(case_id: str, db: Session = Depends(get_db)):
    """The audit report, section by section, in the template's own order."""
    return _audit_report(db, case_id)


@router.get("/cases/{case_id}/audit-report.doc")
def audit_report_word(case_id: str, db: Session = Depends(get_db)):
    """The same report as a Word document. One render serves Word and print — see reporting."""
    from ..reporting import render

    report = _audit_report(db, case_id)
    return Response(
        content=render.to_html(report, for_word=True).encode("utf-8"),
        media_type="application/msword",
        headers={"Content-Disposition":
                 f'attachment; filename="{render.filename_for(report, "doc")}"'})


@router.get("/cases/{case_id}/audit-report.html")
def audit_report_print(case_id: str, db: Session = Depends(get_db)):
    """The printable page. The browser's own print-to-PDF is the PDF renderer."""
    from ..reporting import render

    report = _audit_report(db, case_id)
    return Response(content=render.to_html(report).encode("utf-8"),
                    media_type="text/html; charset=utf-8")


@router.get("/demo/response-file")
def demo_response_file():
    """The taxpayer's deficient sales analysis, so the upload path can be demonstrated live."""
    from ..seed.demo_files import sales_analysis_xlsx

    return Response(
        content=sales_analysis_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Sales_Analysis_Q1_2025.xlsx"'},
    )


# ---------------------------------------------------------------- AI layer (Phase 2)
@router.get("/cases/{case_id}/narrate")           # FEATURE 1 — box narration (verified prose)
def narrate(case_id: str, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id, persist=False)
    return llm.narrate(recon, _rule_rows(db))


@router.get("/cases/{case_id}/nba")               # FEATURE 2 — next best action (structured)
def nba(case_id: str, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id, persist=False)
    return llm.next_best_action(recon, _rule_rows(db))


@router.get("/cases/{case_id}/summary")           # FEATURE 3 — taxpayer brief (figure-free)
def summary(case_id: str, db: Session = Depends(get_db)):
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    tp = c.taxpayer
    profile = {"name": tp.name, "sector": tp.ind_sector, "size": tp.business_size,
               "accounting_method": tp.accounting_method, "resident": tp.resident_flag,
               "vat_group": tp.vat_group_rep_flag}
    prior_returns = [
        {"data_version": r.data_version, "current": r.current_flag,
         "reason_for_amendment": r.reason_for_amendment,
         "submitted": r.submission_date and r.submission_date.isoformat()}
        for r in db.scalars(select(VatReturn).where(VatReturn.taxpayer_id == tp.id)
                            .order_by(VatReturn.data_version)).all()
    ]
    prior_cases = [
        {"case_id": pc.case_id, "reason": pc.case_reason_code, "risk": pc.risk_category,
         "result": pc.audit_result_type, "root_cause": pc.root_cause_code, "action": pc.action_taken}
        for pc in db.scalars(select(AuditCase).where(
            AuditCase.taxpayer_id == tp.id, AuditCase.case_id != case_id)).all()
    ]
    return llm.summarise_history(profile, prior_returns, prior_cases)


class LetterIn(BaseModel):
    text: str


@router.post("/cases/{case_id}/read-letter")     # FEATURE 5 — read a taxpayer letter (draft extraction)
def read_letter(case_id: str, body: LetterIn, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id, persist=False)
    return llm.read_letter(recon, body.text)


@router.get("/cases/{case_id}/report")            # FEATURE 4 — AI-drafted report (streamed SSE)
def report(case_id: str, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id)
    return StreamingResponse(llm.stream_report(recon, _rule_rows(db)),
                             media_type="text/event-stream")


# ============================================================ THE CALCULATION AGENT
# The auditors asked for help with their own arithmetic and for a check on it. Both run the same
# executor: the model turns a described method into a query, Python computes the figure.

class AskIn(BaseModel):
    question: str = ""
    spec: dict | None = None        # an auditor-specified query, used verbatim if supplied


class CheckIn(BaseModel):
    label: str = ""
    method: str = ""
    # Optional: the auditors write freely — "I summed the VAT column and got 2,618,000" states
    # the figure in the same breath as the method, and made them retype it into its own box.
    stated_amount: float | None = None
    document_name: str = ""
    spec: dict | None = None


@router.post("/cases/{case_id}/calc/ask")
def calc_ask(case_id: str, body: AskIn, db: Session = Depends(get_db)):
    """Answer a question off the uploaded documents. Every figure comes from Python."""
    _case_or_404(db, case_id)
    return calc_service.ask(db, case_id, body.question, body.spec)


@router.post("/cases/{case_id}/calc/check")
def calc_check(case_id: str, body: CheckIn, db: Session = Depends(get_db)):
    """Record a figure the auditor calculated and verify it against the source documents."""
    from ..agents import calc_language

    _case_or_404(db, case_id)
    stated = body.stated_amount
    if stated is None:
        stated = calc_language.stated_amount_in(body.method)
    if stated is None:
        raise HTTPException(422, "No figure to check — state the amount you arrived at.")
    label = body.label or calc_language.label_for(body.method) or "Auditor calculation"
    out = calc_service.check(db, case_id, label, body.method, stated,
                             body.spec, body.document_name)
    db.add(EventLog(case_id=case_id, actor="auditor", action="calculation-checked",
                    payload={"label": body.label, "status": out["status"],
                             "delta": out["delta"]}))
    db.commit()
    return out


@router.get("/cases/{case_id}/calc")
def calc_list(case_id: str, db: Session = Depends(get_db)):
    _case_or_404(db, case_id)
    return {"calculations": calc_service.listing(db, case_id),
            "documents": [{"filename": d["filename"], "columns": d["columns"],
                           "row_count": d["row_count"]}
                          for d in calc_service.documents_for(db, case_id)]}


@router.delete("/cases/{case_id}/calc/{calc_id}")
def calc_delete(case_id: str, calc_id: int, db: Session = Depends(get_db)):
    _case_or_404(db, case_id)
    db.execute(delete(AuditorCalculation).where(
        AuditorCalculation.id == calc_id, AuditorCalculation.case_id == case_id))
    db.commit()
    return {"ok": True}


# ============================================================ THE REQUEST EMAIL
# Planning is out of scope, so the spec the completeness check enforces has to be recovered from
# the email the auditor already sent. The parse is a proposal: nothing binds until it is confirmed.

class EmailIn(BaseModel):
    text: str


@router.post("/cases/{case_id}/request-email/parse")
def parse_request_email(case_id: str, body: EmailIn, db: Session = Depends(get_db)):
    """Read the request email into a proposed spec, for the auditor to confirm or edit."""
    _case_or_404(db, case_id)
    parsed = from_email.parse_email(body.text)
    return {**parsed.to_dict(), "catalog": from_email.catalog_choices()}


# ============================================================ STEP EMAILS
# The auditors asked for a draft at each point where something leaves the building. There are
# two: the chase, written from the completeness gaps alone, and the verdict, written from the
# confirmed findings. Both are drafts for a human to edit and send — nothing is sent from here.

@router.get("/cases/{case_id}/emails")
def step_emails(case_id: str, db: Session = Depends(get_db)):
    """Every outbound draft that is live for this case, and which step each belongs to.

    A draft appears only when its trigger exists: the chase when something is outstanding, the
    verdict when the review has a position to report. Offering an email with nothing in it to
    say would train the auditor to ignore the panel.
    """
    from ..agents.correspondence import draft_verdict

    case = _case_or_404(db, case_id)
    out: list[dict] = []

    req = req_service.current_request(db, case_id)
    gaps = list(db.scalars(select(GapFinding).where(GapFinding.case_id == case_id)).all())
    if req is not None and gaps:
        draft = draft_followup(case, case.taxpayer, req, gaps)
        out.append({
            "step": "response-check", "kind": "follow-up",
            "title": "What is missing from the response",
            "trigger": f"{len(gaps)} gap(s) found in what was received",
            **draft,
        })

    inv = investigate_case(case_id, db)
    recon = reconcile_case(db, case_id, persist=False)
    findings = inv.get("findings") or []
    if not gaps or findings:
        draft = draft_verdict(case, case.taxpayer, recon, inv, findings)
        out.append({
            "step": "closure", "kind": "verdict",
            "title": "Outcome of the review",
            "trigger": (f"{len(findings)} finding{'' if len(findings) == 1 else 's'} established" if findings
                        else "no finding — the declared position is supported"),
            **draft,
        })

    return {"case_id": case_id, "emails": out,
            "findings": findings, "exposure": inv.get("exposure", {})}
