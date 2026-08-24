"""The two invoice registers, each set against its own box on the VAT return.

This is the first question an auditor asks and the last one they want to hunt for: **the
taxpayer's own invoice listing totals X, their return declares Y — what is the gap, and where
does it come from?** One register for sales, one for purchases, because the return has a box
for each and an over-declared sale and an over-claimed purchase are opposite risks.

It is deliberately **not a bridge.** An earlier version of this screen drew a waterfall —
reconstructed total, minus a clearance-lag rule, minus netted credit notes, arriving at
declared — and the rule lines are what made it unreadable and what made it arguable. What is
here instead is three numbers per box:

    register total   Σ the VAT the listing itself states, row by row
    declared         the figure in that box of the return
    difference       the first, less the second

No rule acts on any of them. That matters for more than legibility: the funnel in the detailed
section exists to say **which documents qualify** for a box, and it is answerable to a
different question. Reading the listing's own arithmetic is not a qualification judgement and
must not borrow one — so nothing here is set aside, deferred, or explained away, and the
register total is exactly what an auditor would get by summing the VAT column themselves.

Where the difference comes from is answered separately, and only from things already
established elsewhere: invoices the Authority holds that the listing omits, rows whose VAT
could not be read, a stated total that does not foot to its own rows, and coverage short of the
period. Each names a count and an amount and hands over the rows behind it. **Nothing is
attributed to an invoice unless that attribution is real** — a difference against a single
declared figure cannot be pinned on particular rows, and inventing that link would be the most
confident-sounding way to be wrong on this screen.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditCase, GapFinding, VatReturn
from .pipeline import source as line_source
from .pipeline.rules import BOX_PURCHASE, BOX_SALES
from .requests import service as req_service

CREDIT_NOTE = 381

#: One register per box the PoC reconciles. Zero-rated is out: it carries no input side and
#: its own panel already states it is a first, direct comparison.
DIRECTIONS = (
    ("sale", BOX_SALES, "Sales", "Standard-rated sales",
     "Output VAT the listing evidences, against the output VAT declared."),
    ("purchase", BOX_PURCHASE, "Purchases", "Standard-rated purchases",
     "Input VAT the listing evidences, against the input VAT claimed."),
)


def _declared(ret: VatReturn | None, code: str, direction: str) -> float:
    if not ret:
        return 0.0
    for b in ret.boxes:
        if b.box_code == code and b.direction == direction:
            return round(float(b.vat_amount), 2)
    return 0.0


def _invoice_row(line: dict) -> dict:
    """One row of a register, in the shape the drill-down table already renders."""
    return {
        "uuid": line["invoice_uuid"],
        "type_code": line["type_code"],
        "type": "Credit note" if line["type_code"] == CREDIT_NOTE else "Tax invoice",
        "issue_date": line["issue_date"].isoformat() if line.get("issue_date") else None,
        "delivery_date": line["delivery_date"].isoformat() if line.get("delivery_date") else None,
        "status": line.get("status", ""),
        "base": round(float(line.get("taxable_amount") or 0.0), 2),
        "tax_amount": round(float(line.get("tax_amount") or 0.0), 2),
        "row_number": line.get("row_number"),
        "document": line.get("document", ""),
    }


def _risk(direction: str, difference: float, materiality: float) -> str:
    """What a gap in this direction *means*, which is not the same on both sides.

    On sales, a listing above the return is output tax that was due and not declared. On
    purchases it is the mirror: a return above the listing is input tax claimed beyond what the
    invoices support. Reporting "difference" without saying which way the exposure runs leaves
    the auditor to work out the sign every time.
    """
    if abs(difference) <= materiality:
        return "agrees"
    if direction == "sale":
        return "under-declared" if difference > 0 else "over-declared"
    return "over-claimed" if difference < 0 else "under-claimed"


RISK_LABEL = {
    "no-register": "No listing on file — nothing to compare",
    "agrees": "Register and return agree",
    "under-declared": "Register exceeds the return — output VAT may be under-declared",
    "over-declared": "Return exceeds the register — more output VAT declared than evidenced",
    "over-claimed": "Return exceeds the register — input VAT may be over-claimed",
    "under-claimed": "Register exceeds the return — less input VAT claimed than evidenced",
}


def _insights(db: Session, case_id: str, direction: str, lines: list[dict],
              doc: dict | None, zatca: dict | None,
              period_from: date, period_to: date) -> list[dict]:
    """Where the difference comes from — only where that can actually be established.

    Every entry is read from something the engine already settled. An insight with nothing
    behind it is not written, because a panel that always finds four reasons teaches an auditor
    to stop reading it.
    """
    out: list[dict] = []

    # 1 · Invoices the Authority holds that the listing does not (ZR-01). The one attribution
    #     here that is genuinely per-invoice: these are named records carrying named amounts,
    #     and their VAT is money the register is short by rather than an inference about it.
    if zatca and zatca.get("comparable") and direction == "sale":
        missing = [m for m in zatca.get("mismatches", []) if m.get("code") == "ZR-01"]
        if missing:
            amount = round(sum(float(m.get("vat_at_stake") or 0.0) for m in missing), 2)
            out.append({
                "key": "zatca-omitted",
                "headline": f"{len(missing)} invoice"
                            f"{'' if len(missing) == 1 else 's'} in ZATCA's records "
                            f"{'is' if len(missing) == 1 else 'are'} not in the register",
                "detail": "The Authority holds these invoices for this period and the listing "
                          "supplied does not include them, so the register is short by their "
                          "VAT. This is the one line here that names particular invoices.",
                "count": len(missing),
                "amount": amount,
                "invoices": [{"uuid": m.get("ref", ""), "type": "Tax invoice",
                              "type_code": 388, "issue_date": None, "delivery_date": None,
                              "status": "in ZATCA's records only", "base": 0.0,
                              "tax_amount": round(float(m.get("vat_at_stake") or 0.0), 2),
                              "document": "ZATCA extract"}
                             for m in missing],
                "ask": "the invoices the Authority holds that the listing omits",
            })

    # 2 · Rows whose VAT could not be read. They are not in the total — and a blank cell counted
    #     as nothing would quietly shrink the register, which is the same rule the population
    #     follows.
    if doc:
        skipped = max(len(doc.get("rows") or []) - len(lines), 0)
        if skipped:
            out.append({
                "key": "unreadable-vat",
                "headline": f"{skipped} row{'' if skipped == 1 else 's'} carry no readable VAT "
                            "amount",
                "detail": "These rows are in the file but not in the register total — a blank "
                          "or unparseable cell is skipped rather than summed as zero, which "
                          "would understate the register without saying so.",
                "count": skipped,
                "amount": 0.0,
                "invoices": [],
                "ask": "a corrected listing with the VAT amount completed on every row",
            })

    # 3 · The file's own stated total against its own rows. Already checked on arrival; repeated
    #     here because it is a direct explanation of a register the auditor is looking at.
    if doc:
        for g in db.scalars(select(GapFinding).where(
                GapFinding.case_id == case_id,
                GapFinding.kind == "arithmetic-mismatch")).all():
            if not (g.detail or ""):
                continue
            out.append({
                "key": "stated-total",
                "headline": "The file's stated total does not agree with its own rows",
                "detail": g.detail,
                "count": 0,
                "amount": 0.0,
                "invoices": [],
                "ask": "confirmation of which figure is correct — the stated total or the rows",
            })
            break

    # 4 · Coverage. A register built from two months of a three-month period is a floor, and the
    #     difference against a full-quarter return is not a finding until that is resolved.
    if lines:
        dated = [l["issue_date"] for l in lines if l.get("issue_date")]
        if dated:
            last = max(dated)
            first = min(dated)
            if last < period_to or first > period_from:
                out.append({
                    "key": "period-coverage",
                    "headline": f"The register runs {first.isoformat()} to {last.isoformat()}, "
                                f"the period runs {period_from.isoformat()} to "
                                f"{period_to.isoformat()}",
                    "detail": "Part of the period is not covered by the listing, so the "
                              "register is a floor rather than the period's full total and the "
                              "difference cannot yet be read as an adjustment.",
                    "count": 0,
                    "amount": 0.0,
                    "invoices": [],
                    "ask": "a listing covering the whole period under review",
                })

    return out


def build(db: Session, case_id: str, *, zatca: dict | None = None) -> dict:
    """The registers for a case: what the listings total, what the return declares, the gap."""
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not case:
        raise ValueError("case not found")
    tp = case.taxpayer
    ret = db.scalar(select(VatReturn).where(
        VatReturn.taxpayer_id == tp.id,
        VatReturn.period_from == case.period_from,
        VatReturn.current_flag.is_(True)))

    docs = [{"filename": d.filename,
             "columns": (d.content or {}).get("columns", []),
             "rows": (d.content or {}).get("rows", [])}
            for d in req_service.documents(db, case_id)]

    registers = []
    for direction, box_code, title, box_label, note in DIRECTIONS:
        doc = line_source.pick_listing(docs, direction)
        lines = (line_source.lines_from_document(
            doc, direction=direction, period_from=case.period_from,
            period_to=case.period_to, sector=tp.ind_sector) if doc else [])

        rows = [_invoice_row(l) for l in lines]
        register_total = round(sum(r["tax_amount"] for r in rows), 2)
        notes = [r for r in rows if r["type_code"] == CREDIT_NOTE]
        declared = _declared(ret, box_code, direction)

        # No listing is not a register of zero. Subtracting an absent listing from a declared
        # figure would report the whole box as a discrepancy — SAR 150,000 "over-claimed"
        # because nobody has uploaded the purchases analysis yet — which is a finding
        # fabricated out of a missing file. Same rule the ZATCA matcher enforces: one side is
        # not a comparison, and the honest answer names the side that is missing.
        comparable = bool(rows)
        difference = round(register_total - declared, 2) if comparable else 0.0
        # The same 1% floor the engine uses, so a rounding tail is not reported as a gap.
        materiality = round(max(abs(declared), abs(register_total)) * 0.01, 2)
        risk = _risk(direction, difference, materiality) if comparable else "no-register"

        registers.append({
            "direction": direction,
            "title": title,
            "box_label": box_label,
            "box_code": box_code,
            "note": note,
            "comparable": comparable,
            "not_comparable_note": "" if comparable else
                f"No {title.lower()} listing has been filed on this case, so there is nothing "
                f"to set against the {declared:,.2f} declared. This is a missing document, not "
                f"a discrepancy — ask for it in Taxpayer Correspondence.",
            "document": ({"filename": doc["filename"],
                          "rows": len(doc.get("rows") or []),
                          "columns": doc.get("columns") or []} if doc else None),
            "invoice_count": len(rows) - len(notes),
            "credit_note_count": len(notes),
            "register_total": register_total,
            "declared": declared,
            "difference": difference,
            "materiality": materiality,
            "risk": risk,
            "risk_label": RISK_LABEL[risk],
            "invoices": rows,
            "insights": _insights(db, case_id, direction, lines, doc, zatca,
                                  case.period_from, case.period_to) if comparable else [],
        })

    return {
        "case_id": case_id,
        "period_from": case.period_from.isoformat(),
        "period_to": case.period_to.isoformat(),
        "return_on_file": ret is not None,
        "registers": registers,
    }
