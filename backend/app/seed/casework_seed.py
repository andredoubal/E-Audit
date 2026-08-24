"""Seed one full round trip on the hero case, so the loop has something to show on load.

The demo needs to open on the state auditors actually spend their time in: a request already
issued, a response already received, and the response not quite right. Building it here — by
running the real planner, the real extractor and the real checker rather than writing the
outcome down — means the seeded state is a genuine product of the pipeline, and any drift in
the pipeline shows up immediately as different seeded gaps.

Only the hero case is seeded this far. The others open at the planning stage, which is where a
new case starts.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.correspondence import draft_request
from ..models import AuditCase, Taxpayer
from ..agents import zatca_service
from ..requests import service
from ..requests import threads as thread_service
from . import demo_files

HERO = "CASE-2025-0481"


def build(db: Session) -> dict:
    """Issue round 1 on the hero case and record the taxpayer's deficient response."""
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == HERO))
    if case is None:
        return {"seeded": False}
    taxpayer = db.get(Taxpayer, case.taxpayer_id)

    req = service.open_request(db, case)
    if not req.items:
        return {"seeded": False, "reason": "planner produced no items"}

    issued = (case.referral_date or date.today()) + timedelta(days=4)
    drafted = draft_request(case, taxpayer, req)
    service.issue(db, req, body=drafted["text"], source=drafted["source"], when=issued)

    # Round one is a conversation, so it opens as one and the request letter is the first thing
    # on it. Seeding the round without its thread left the demo saying "nothing sent yet" above
    # a chase letter itemising the gaps in a document that had plainly arrived.
    thread = thread_service.start(db, case.case_id, subject=req.subject)
    thread_service.add_message(db, thread, direction="outbound", body=drafted["text"],
                               subject=req.subject, drafted_by="ai-drafted",
                               audit_stage="request", request_id=req.id)

    # the taxpayer answers the sales analysis — late, and not quite as asked
    sales_item = next((i for i in req.items if i.catalog_key == "sales-analysis"), req.items[0])
    service.record_document(
        db, case=case, req=req, item_id=sales_item.id,
        filename="Sales_Analysis_Q1_2025.xlsx",
        data=demo_files.sales_analysis_xlsx(),
        file_format="xlsx",
        received=issued + timedelta(days=34),      # the months-long wait, in miniature
    )

    report = service.run_checks(db, case)

    # The Authority's own records for the same period. Seeded so the comparison has both sides
    # on the hero case — with one side it correctly refuses to compare, which is right and
    # shows nothing.
    zatca_service.record(db, case, filename="ZATCA_Invoices_Q1_2025.xlsx",
                         data=demo_files.zatca_invoices_xlsx(), source="seed")

    # None of these answers a request item. The customs declarations were obtained by the
    # auditor, and the trial balance is not the return-to-ledger reconciliation that was asked
    # for — it is the accounts themselves. Filed against an item they do not answer, the
    # checker correctly reports them as the wrong document; filed with no item, they are what
    # they are, and the reconciliation the auditor actually asked for stays outstanding.
    for filename, data in (("Customs_Imports_Q1_2025.xlsx", demo_files.customs_imports_xlsx()),
                           ("Customs_Exports_Q1_2025.xlsx", demo_files.customs_exports_xlsx()),
                           ("Trial_Balance_Q1_2025.xlsx", demo_files.trial_balance_xlsx())):
        service.record_document(
            db, case=case, req=req, filename=filename, data=data,
            file_format="xlsx", received=issued + timedelta(days=34))

    return {"seeded": True, "case_id": HERO, "round": req.seq,
            "items": len(req.items), "gaps": len(report.gaps),
            "blocking": len(report.blocking)}
