"""The case assistant — one conversation per case, available from every tab.

**Why one and not three.** An earlier design gave each module its own chat. That split a single
train of thought across three transcripts: "why is this listing over the return?" is a question
about the documents that arrived, the tests that were run, and the sentence that will be
written, and an auditor asking it should not have to pick a tab first or remember which panel
they asked in. At one-case scale there is no context-size argument for splitting, so the case is
the conversation.

**What survived from that design is the part that mattered: the actions are a closed set.** The
assistant does not "run analysis". It selects one of a fixed list of things this application can
already do, and a deterministic executor does it — the same pattern `calc_service` uses, and for
the same reason. An assistant that could run arbitrary work would be unauditable, and in a tax
authority that is not a trade worth making. Anything outside the set becomes `explain`, which
answers in words and changes nothing.

**No number in a reply comes from the model.** Every action returns engine-computed facts, and
the prose is checked by `verify_claims` before it is shown, exactly like every other drafted
sentence in this application. With no credentials the assistant still works: it answers from the
case deterministically and says plainly that it is not drafting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from ..models import AuditCase, CaseMessage, EventLog
from ..recon_engine import reconcile_case
from ..requests import service as req_service
from ..requests import threads as thread_service
from . import investigation_service as inv_service
from . import zatca_service
from .correspondence import draft_followup


# ------------------------------------------------------------------ the closed action set

@dataclass(frozen=True)
class Action:
    key: str
    label: str
    hint: str                       # what the auditor sees on the button
    needs: str = ""                 # the precondition, in words, when it is not met


ACTIONS: tuple[Action, ...] = (
    Action("explain", "Explain", "Answer from the case as it stands."),
    Action("status", "Where is this case?", "What has arrived, what is still outstanding."),
    Action("outstanding", "What is still missing?", "The gaps, and what the chase asks for.",
           needs="a round of correspondence with something requested"),
    Action("draft_chase", "Draft the chase", "Write the email for what is still outstanding.",
           needs="at least one outstanding item"),
    Action("run_investigation", "Re-run the investigation", "Re-test every hypothesis against "
           "the evidence now on file."),
    Action("findings", "What has been established?", "Accepted findings and what they come to."),
    Action("zatca", "Compare with ZATCA's records", "What the Authority's own invoices show.",
           needs="an invoice dataset loaded on this case"),
    Action("revise_assessment", "Revise the assessment",
           "Rewrite your assessment of the investigation the way you describe."),
)

ACTION_BY_KEY = {a.key: a for a in ACTIONS}

# Cues an auditor actually types. Deliberately a table and not a model call: choosing between
# seven known actions is not a judgement, and routing it through a model would add a way to get
# it wrong while making the same question answer differently on two runs.
_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("outstanding", ("missing", "outstanding", "still need", "not supplied", "gaps", "gap")),
    ("draft_chase", ("chase", "draft the email", "follow up", "follow-up", "write the email",
                     "remind")),
    ("run_investigation", ("re-run", "rerun", "run the investigation", "re-test", "retest",
                           "investigate again")),
    # Before `findings`, which claims "assess": "what has been established?" is a question about
    # the case, and "rewrite the assessment" is an instruction to change a document.
    ("revise_assessment", ("assessment", "treat this as", "treat it as", "rewrite it",
                           "reword", "redraft")),
    ("findings", ("finding", "established", "exposure", "accepted", "conclusion", "assess")),
    ("zatca", ("zatca", "authority's records", "invoice match", "unmatched", "reconcil")),
    ("status", ("where are we", "where is this", "status", "summary", "what has happened",
                "catch me up")),
)


def route(question: str) -> str:
    """Which action a question asks for. `explain` is the honest default, never a guess."""
    q = (question or "").lower()
    for key, cues in _CUES:
        if any(c in q for c in cues):
            return key
    return "explain"


# ------------------------------------------------------------------ the executor

@dataclass
class Answer:
    action: str
    text: str
    facts: dict = field(default_factory=dict)
    source: str = "deterministic"
    did: str = ""                   # what actually changed, when anything did


def _sar(v) -> str:
    return f"SAR {abs(float(v or 0)):,.0f}"


def _status(db, case: AuditCase) -> Answer:
    loop = req_service.state(db, case)
    a = loop.get("assessment") or {"summary": {}, "items": []}
    threads = thread_service.state(db, case.case_id)
    s = a["summary"]
    outstanding = sum(v for k, v in s.items() if k != "received")
    lines = [
        f"Round {max(len(threads['threads']), 1)} of correspondence on {case.case_id}.",
        f"{len(loop['documents'])} document(s) received; "
        f"{s.get('received', 0)} of {len(a['items'])} requested item(s) fully answered.",
    ]
    if outstanding:
        lines.append(f"{outstanding} item(s) still outstanding — "
                     + ", ".join(f"{i['label']} ({i['state_label'].lower()})"
                                 for i in a["items"] if i["state"] != "received"))
    else:
        lines.append("Nothing is outstanding on the current round.")
    return Answer("status", " ".join(lines),
                  facts={"outstanding": outstanding, "documents": len(loop["documents"])})


def _outstanding(db, case: AuditCase) -> Answer:
    a = (req_service.state(db, case).get("assessment") or {"items": []})
    rows = [i for i in a["items"] if i["state"] != "received"]
    if not rows:
        return Answer("outstanding",
                      "Nothing is outstanding — every requested item has been answered and "
                      "passes the checks that can be run on it.")
    parts = [f"{i['label']} — {i['state_label'].lower()}"
             + (f": {i['reason']}" if i["reason"] else "") for i in rows]
    return Answer("outstanding",
                  f"{len(rows)} item(s) still outstanding.\n\n" + "\n".join(f"• {p}" for p in parts),
                  facts={"count": len(rows)})


def _draft_chase(db, case: AuditCase) -> Answer:
    from ..models import GapFinding

    req = req_service.current_request(db, case.case_id)
    gaps = list(db.scalars(
        select(GapFinding).where(GapFinding.case_id == case.case_id,
                                 GapFinding.severity == "blocking")
        .order_by(GapFinding.id)).all()) if req is not None else []
    if not gaps:
        return Answer("draft_chase",
                      "There is nothing outstanding, so there is nothing to chase. A letter "
                      "asking for what has already arrived is worse than no letter.")
    draft = draft_followup(case, case.taxpayer, req, gaps)
    return Answer("draft_chase", draft.get("text", ""),
                  source=draft.get("source", "deterministic"),
                  did="drafted the chase for the outstanding items")


def _run_investigation(db, case: AuditCase) -> Answer:
    run = inv_service.run(db, case, trigger="auditor-requested",
                          note="asked for from the case assistant")
    state = inv_service.state(db, case)
    c = state["counts"]
    return Answer("run_investigation",
                  f"Re-ran the investigation. {c['total']} hypothes"
                  f"{'is' if c['total'] == 1 else 'es'} on the case, "
                  f"{c['decided']} already ruled on by you and {c['accepted']} accepted. "
                  f"Nothing is a finding until you accept it on the Investigation tab.",
                  facts={"run": run.seq, "changed": run.changed_count},
                  did=f"recorded investigation run {run.seq}")


def _findings(db, case: AuditCase) -> Answer:
    confirmed = inv_service.confirmed_findings(db, case)
    if not confirmed:
        state = inv_service.state(db, case)
        undecided = state["counts"]["total"] - state["counts"]["decided"]
        return Answer("findings",
                      "No finding has been established on this case. The engine's confirmed "
                      f"hypotheses are proposals, not conclusions — {undecided} of them are "
                      "still waiting on your decision.",
                      facts={"undecided": undecided})
    from .findings import exposure

    e = exposure(confirmed)
    lines = [f"{f.statement} — {_sar(f.amount)}" for f in confirmed]
    return Answer("findings",
                  f"{len(confirmed)} finding(s) you have accepted, coming to "
                  f"{_sar(e['total'])} of adjustment"
                  + (f" and {_sar(e['documentation_at_risk'])} of documentation risk"
                     if e["documentation_at_risk"] else "")
                  + ".\n\n" + "\n".join(f"• {ln}" for ln in lines),
                  facts=e)


def _zatca(db, case: AuditCase) -> Answer:
    c = zatca_service.comparison(db, case)
    if not c.comparable:
        return Answer("zatca", c.note)
    unmatched = c.by_code("ZR-01")
    values = c.by_code("ZR-03")
    bits = [f"{c.matched_count} invoice(s) appear in both the listing and ZATCA's records."]
    if unmatched:
        bits.append(f"{len(unmatched)} invoice(s) in ZATCA's records are not in the listing, "
                    f"carrying {_sar(c.vat_at_stake('ZR-01'))} of VAT.")
    if values:
        bits.append(f"{len(values)} matched invoice(s) carry a different VAT amount on each "
                    f"side.")
    if not unmatched and not values:
        bits.append("Nothing disagrees.")
    return Answer("zatca", " ".join(bits),
                  facts={"matched": c.matched_count, "unmatched": len(unmatched)})


def _revise_assessment(db, case: AuditCase, question: str) -> Answer:
    """Rewrite the auditor's assessment the way they just described it.

    The only action that changes a document the auditor owns, so it says plainly what it did and
    keeps the previous text recoverable. It cannot introduce a figure: the rewrite goes through
    the same engine-authored facts block and the same verifier as the first draft.
    """
    from . import assessment as assessment_service

    view = assessment_service.revise(db, case, question)
    if not view.get("revised"):
        return Answer("revise_assessment",
                      "I could not rewrite the assessment — no model is reachable, so the "
                      "assessment on the Investigation tab is the engine's own draft and yours "
                      "to edit directly. Nothing has been changed.",
                      source=view.get("source", "deterministic"))
    return Answer("revise_assessment",
                  "Rewritten. The assessment on the Investigation tab now reads:\n\n"
                  + view["text"]
                  + "\n\nIt is still yours — edit it there, or say what else to change.",
                  source=view.get("source", "claude"),
                  did="rewrote the auditor's assessment")


def _explain(db, case: AuditCase, question: str) -> Answer:
    """No action fits. Answer from the reconciliation rather than inventing a capability."""
    recon = reconcile_case(db, case.case_id, persist=False)
    return Answer(
        "explain",
        # `expected_vat` is the engine's key. Reading `expected` returned None, so the most-used
        # fallback answer told the auditor the records supported SAR 0 — beside a difference
        # that could not be derived from it.
        f"For {case.case_id}, the records on file support {_sar(recon.get('expected_vat'))} of "
        f"output VAT against {_sar(recon.get('declared'))} declared — a difference of "
        f"{_sar(recon.get('difference'))}, of which {_sar(recon.get('unexplained'))} is not yet "
        f"accounted for.\n\nI can only do a fixed set of things on a case: "
        + ", ".join(a.label.lower() for a in ACTIONS if a.key != "explain")
        + ". Ask for one of those, or work the tabs directly.",
        facts={k: recon.get(k)
               for k in ("declared", "expected_vat", "difference", "unexplained")})


_EXEC = {
    "status": _status,
    "outstanding": _outstanding,
    "draft_chase": _draft_chase,
    "run_investigation": _run_investigation,
    "findings": _findings,
    "zatca": _zatca,
}

# The two actions that read what the auditor actually typed, rather than only which action it
# was. Everything else is answered from the case and needs no words from the question.
_EXEC_WITH_QUESTION = {
    "explain": _explain,
    "revise_assessment": _revise_assessment,
}


# ------------------------------------------------------------------ the conversation

def history(db, case_id: str) -> list[CaseMessage]:
    return list(db.scalars(
        select(CaseMessage).where(CaseMessage.case_id == case_id)
        .order_by(CaseMessage.seq)).all())


def ask(db, case: AuditCase, question: str, *, action: str = "") -> dict:
    """One turn. The action is chosen, executed deterministically, and both are recorded."""
    question = (question or "").strip()
    if not question and not action:
        raise ValueError("nothing asked")

    key = action or route(question)
    if key not in ACTION_BY_KEY:
        key = "explain"

    seq = 1 + len(history(db, case.case_id))
    db.add(CaseMessage(case_id=case.case_id, seq=seq, role="auditor", content=question,
                       action_kind=key))

    fn = _EXEC.get(key)
    answer = (fn(db, case) if fn
              else _EXEC_WITH_QUESTION.get(key, _explain)(db, case, question))

    db.add(CaseMessage(case_id=case.case_id, seq=seq + 1, role="assistant",
                       content=answer.text, action_kind=answer.action,
                       action_payload=answer.facts, source=answer.source,
                       did=answer.did))
    if answer.did:
        db.add(EventLog(case_id=case.case_id, actor="auditor", action="assistant-action",
                        payload={"action": answer.action, "did": answer.did}))
    db.commit()
    return state(db, case.case_id)


def state(db, case_id: str) -> dict:
    return {
        "case_id": case_id,
        "messages": [
            {"seq": m.seq, "role": m.role, "content": m.content,
             "action": m.action_kind, "source": m.source, "did": m.did,
             "created_at": m.created_at.isoformat() if m.created_at else ""}
            for m in history(db, case_id)
        ],
        "actions": [{"key": a.key, "label": a.label, "hint": a.hint} for a in ACTIONS],
    }


def clear(db, case_id: str) -> dict:
    from sqlalchemy import delete

    db.execute(delete(CaseMessage).where(CaseMessage.case_id == case_id))
    db.commit()
    return state(db, case_id)


__all__ = ["ACTIONS", "ask", "clear", "route", "state"]
