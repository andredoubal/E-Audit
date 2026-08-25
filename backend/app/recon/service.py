"""Every comparison a case supports, run — and every one it does not, explained.

Derived on demand rather than stored, like the lifecycle and the ZATCA comparison before it. A
reconciliation is a pure function of the evidence and the return, so recomputing it is cheaper
than keeping it in step, and there is no stale variance to reconcile against a file that has
since been replaced.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..evidence import service as evidence_service
from ..models import AuditCase, VatReturn
from . import engine, planner, registry as reg, status as S


def _declared(db: Session, case: AuditCase) -> tuple[dict[str, float], bool]:
    ret = db.scalar(select(VatReturn).where(
        VatReturn.taxpayer_id == case.taxpayer_id,
        VatReturn.period_from == case.period_from,
        VatReturn.current_flag.is_(True)))
    if ret is None:
        return {}, False
    return {b.box_code: round(float(b.vat_amount), 2) for b in ret.boxes}, True




def state(db: Session, case_id: str, *, workstream: str = "") -> dict:
    """Both workstreams, or one, with every comparison the evidence supports."""
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if case is None:
        raise ValueError("case not found")

    profile_rows = evidence_service.profiles(db, case_id)
    profiles = {p["filename"]: p for p in profile_rows}
    rows_by_file = evidence_service.rows_by_file(db, case_id)
    declared, return_on_file = _declared(db, case)

    plans = planner.plan(profile_rows, return_on_file=return_on_file, workstream=workstream)
    results = [engine.run(p, profiles=profiles, rows_by_file=rows_by_file, declared=declared,
                          period_from=case.period_from, period_to=case.period_to).to_dict()
               for p in plans]
    # Most attention first, so the auditor reads the questions before the agreements.
    results.sort(key=lambda r: (-r["attention"], r["id"]))

    return {
        "case_id": case_id,
        "period_from": case.period_from.isoformat(),
        "period_to": case.period_to.isoformat(),
        "return_on_file": return_on_file,
        "workstreams": {
            side: _summary([r for r in results if r["workstream"] == side])
            for side in (reg.SALES, reg.PURCHASES)
        },
        "results": results,
    }


def _summary(results: list[dict]) -> dict:
    """What a workstream comes to, in the counts the overview shows.

    **The unexplained differences are deliberately not summed.** Several comparisons rest on the
    same file: a sales register that exceeds the return by SAR 618,000 and misses SAR 2,618,000
    of the Authority's invoices is one population read two ways, and adding them reports SAR
    3,236,000 of a difference that does not exist. It is the same defect `findings.exposure()`
    exists to prevent one stage later, and it is worth preventing here too — a headline figure
    is the number a stakeholder repeats.

    So the summary reports the **largest single** unexplained difference and how many
    comparisons carry one. What the case actually comes to is a question for the adjudicator,
    which counts each basis once, and ultimately for the auditor.
    """
    by_status = {s: sum(1 for r in results if r["status"] == s) for s in S.STATUSES}
    unexplained = [r for r in results if r["status"] in (S.VARIANCE, S.PARTIAL)]
    amounts = [abs(r["residual"] or r["variance"]) for r in unexplained]
    largest = max(amounts, default=0.0)
    return {
        "total": len(results),
        "by_status": by_status,
        "runnable": sum(1 for r in results if r["status"] != S.INSUFFICIENT),
        "unexplained_count": len(unexplained),
        "largest_unexplained": round(largest, 2),
        "largest_unexplained_from": next(
            (r["title"] for r in unexplained
             if abs(r["residual"] or r["variance"]) == largest), ""),
        "not_summed_because": (
            "Several comparisons can rest on the same file, so adding their differences would "
            "report money twice. The largest single difference is shown instead."
            if len(unexplained) > 1 else ""),
        "needs": sorted({n for r in results for n in r["needs"]}),
    }
