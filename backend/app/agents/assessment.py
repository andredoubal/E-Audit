"""The auditor's assessment of the investigation — drafted by the engine, owned by the auditor.

Until this existed the auditor's judgement was expressed only as a verdict per hypothesis:
twelve accept/reject controls, one on every card, which said the tool expected a separate ruling
on every piece of evidence. That is not how the conclusion is reached. An auditor reads the
whole investigation and writes *one* position — this matter is a timing difference, that one is
not supported, and the remainder is a proposed adjustment of so much.

So there is one assessment per case. It is drafted from what the engine settled, and from that
point it is a document the auditor edits. Two rules keep it honest:

- **The draft states no figure the engine did not compute.** The facts block is engine-authored
  and `verify_correspondence` enforces the same rule it enforces on outbound letters: every
  numeric literal in the draft must already appear in the facts. Claude may repeat a figure it
  was handed; it may not introduce one. With no credentials the deterministic draft is complete
  prose, not a stub.
- **What was replaced is kept.** `original` travels with the text, so an auditor's rewrite is
  visible and reversible, and the case file can say which of the two wrote what is stored.

The findings that reach the report are still the ones the auditor accepted — this is the place
the accepting is done, not a second parallel truth.
"""
from __future__ import annotations

from sqlalchemy import select

from ..models import AuditCase, CaseAssessment
from . import investigation_service as inv_service
from . import summary as summary_mod

_SAR = "SAR {:,.0f}"


def _sar(v: float) -> str:
    return _SAR.format(abs(v or 0))


def facts(state: dict, cards: dict) -> str:
    """Everything the draft is allowed to say, as the engine established it.

    Written as a block rather than passed as structure because it is also the verifier's
    reference: a figure is admissible in the draft precisely when it appears here.
    """
    lines: list[str] = []
    t = cards["totals"]
    lines.append(f"Investigation runs completed: {cards['runs']}")
    lines.append(f"Matters observed and settled by a deterministic test: {t['observations']}")
    lines.append(f"Matters that could not be settled on the evidence held: {t['unresolved']}")
    lines.append(f"Defects found in the records themselves: {t['record_defects']}")
    lines.append(f"Hypotheses tested and not supported: {t['not_supported']}")
    lines.append(f"Total at stake across the matters observed: {_sar(t['at_stake'])} "
                 "(each amount counted once against the evidence it rests on; not a "
                 "proposed adjustment)")
    lines.append("")

    for c in cards["cards"]:
        head = f"- {c['title']}"
        if c["amount"]:
            head += f" — {_sar(c['amount'])}"
        lines.append(head)
        lines.append(f"    observed: {c['observed']}")
        if c["reading"]:
            lines.append(f"    would report as: {c['reading']}")
        if c["confidence"]:
            lines.append(f"    confidence in the supporting evidence: {c['confidence']}")
        if c["decision"]:
            lines.append(f"    the auditor has already ruled: {c['decision'].replace('-', ' ')}")
        if c["needs_info"]:
            lines.append(f"    outstanding with the taxpayer: {c['needs_info']}")

    accepted = [c for c in cards["cards"] if c["decision"] == "accepted"]
    lines.append("")
    if accepted:
        lines.append("Accepted by the auditor, and therefore reaching the audit report:")
        for c in accepted:
            lines.append(f"- {c['title']}"
                         + (f" — {_sar(c['amount'])}" if c["amount"] else ""))
    else:
        lines.append("Accepted by the auditor so far: NONE. No finding has been confirmed, so "
                     "the review is not concluded and no adjustment is proposed.")
    return "\n".join(lines)


def fallback(state: dict, cards: dict) -> str:
    """The assessment with no model available — complete prose, not a placeholder.

    It says what was observed, what remains open, and what the auditor has confirmed, and it
    stops there. Everything it cannot know — whether a difference is a timing matter, whether
    the explanation offered is accepted — is exactly what the auditor is here to write.
    """
    t = cards["totals"]
    obs = [c for c in cards["cards"] if c["kind"] == summary_mod.OBSERVATION]
    open_ = [c for c in cards["cards"] if c["kind"] == summary_mod.UNRESOLVED]
    defects = [c for c in cards["cards"] if c["kind"] == summary_mod.DATA_QUALITY]
    accepted = [c for c in cards["cards"] if c["decision"] == "accepted"]

    p: list[str] = []
    if not cards["cards"]:
        p.append("The investigation raised no matter against the documents held for this case. "
                 "Nothing on the file supports a proposed adjustment, and no question has been "
                 "left open for the taxpayer to answer.")
        return "\n\n".join(p)

    head = (f"The investigation settled {t['observations']} matter"
            f"{'' if t['observations'] == 1 else 's'} against the documents on file")
    if t["at_stake"]:
        head += f", with {_sar(t['at_stake'])} at stake across them"
    head += "."
    if t["not_supported"]:
        head += (f" A further {t['not_supported']} hypothes"
                 f"{'is was' if t['not_supported'] == 1 else 'es were'} tested and not "
                 "supported by the evidence.")
    p.append(head)

    if obs:
        p.append("What was observed:\n" + "\n".join(
            f"• {c['title']}" + (f" ({_sar(c['amount'])})" if c["amount"] else "")
            + f" — {c['observed']}" for c in obs))
    if open_:
        p.append("Not settled on the evidence held:\n" + "\n".join(
            f"• {c['title']} — {c['observed']}" for c in open_))
    if defects:
        p.append("Defects in the records themselves:\n" + "\n".join(
            f"• {c['title']} — {c['observed']}" for c in defects))

    if accepted:
        p.append("Confirmed by the auditor, and carried into the audit report: "
                 + "; ".join(c["title"] for c in accepted) + ".")
    else:
        p.append("No matter above has yet been confirmed by the auditor, so the review is not "
                 "concluded and no adjustment is proposed. Each one is an observation to be "
                 "validated, not a determination.")

    p.append("[Assessment to be completed by the auditor: whether each matter above is accepted, "
             "the reason where it is not, and the position to be put to the taxpayer.]")
    return "\n\n".join(p)


# ------------------------------------------------------------------------------- persistence

def _row(db, case_id: str) -> CaseAssessment | None:
    return db.scalar(select(CaseAssessment).where(CaseAssessment.case_id == case_id))


def _view(row: CaseAssessment | None, draft: str, facts_block: str, meta: dict) -> dict:
    return {
        "text": row.text if row else draft,
        "draft": draft,
        "original": (row.original if row else "") or draft,
        "edited": bool(row and row.text.strip() and row.text.strip() != draft.strip()),
        "written_by": row.written_by if row else meta.get("source", "engine"),
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else "",
        "source": meta.get("source", ""),
        "verified": meta.get("verified", True),
        "facts": facts_block,
    }


def draft(db, case: AuditCase) -> tuple[str, str, dict]:
    """Draft the assessment from the investigation. Returns (text, facts, meta)."""
    from ..agents import zatca_service
    from ..llm.service import llm

    state = inv_service.state(db, case)
    cards = summary_mod.build(state, zatca=zatca_service.state(db, case))
    facts_block = facts(state, cards)
    result = llm.draft_assessment(facts=facts_block,
                                  fallback=lambda: fallback(state, cards))
    return result["text"], facts_block, result


def get(db, case: AuditCase) -> dict:
    """The stored assessment, or the drafted one when the auditor has not written yet."""
    text, facts_block, meta = draft(db, case)
    return _view(_row(db, case.case_id), text, facts_block, meta)


def save(db, case: AuditCase, text: str, *, written_by: str = "auditor") -> dict:
    """Store the auditor's text. An empty save reverts to the engine's draft.

    Same rule as the report fields and the letters: clearing a box restores what the engine
    wrote rather than blanking the section, because a blank assessment is not a position.
    """
    drafted, facts_block, meta = draft(db, case)
    row = _row(db, case.case_id)
    if not text.strip():
        if row:
            db.delete(row)
            db.commit()
        return _view(None, drafted, facts_block, meta)

    if row is None:
        row = CaseAssessment(case_id=case.case_id, original=drafted)
        db.add(row)
    elif not row.original:
        row.original = drafted
    row.text = text.strip()
    row.written_by = written_by
    db.commit()
    db.refresh(row)
    return _view(row, drafted, facts_block, meta)


def revise(db, case: AuditCase, instruction: str) -> dict:
    """Rewrite the assessment under the auditor's instruction, then store it.

    The instruction steers *language and emphasis* — "treat this as a timing difference", "drop
    that matter, the evidence is thin", "say it in plainer terms". It cannot introduce a figure:
    the same facts block and the same verifier apply to the rewrite as to the first draft, so an
    instruction demanding a number produces a rejected draft and the deterministic text, never a
    wrong figure wearing the engine's authority.
    """
    from ..llm.service import llm

    drafted, facts_block, meta = draft(db, case)
    row = _row(db, case.case_id)
    current = (row.text if row else "") or drafted

    result = llm.draft_assessment(facts=facts_block, fallback=lambda: current,
                                  current=current, instruction=instruction.strip())
    if result.get("mode") != "live":
        # Nothing was rewritten. Say so rather than storing the text unchanged and reporting a
        # revision that did not happen.
        view = _view(row, drafted, facts_block, meta)
        view["revised"] = False
        view["source"] = result.get("source", "")
        return view

    view = save(db, case, result["text"], written_by="ai-assisted")
    view["revised"] = True
    view["source"] = result["source"]
    view["verified"] = result["verified"]
    return view


__all__ = ["draft", "facts", "fallback", "get", "revise", "save"]
