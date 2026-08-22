"""Threads: the correspondence history, and the loop back from the investigation.

The rule that shapes this module: **one thread is open at a time, and closed threads
accumulate**. A case can therefore show its whole history — the opening request, the chase, the
round that came out of something the investigation found — without ever leaving "which
conversation does this upload belong to" ambiguous. A document filed against the wrong request
is a completeness check answering the wrong question, which is worse than not having the check.

The piece that matters most here is `open_for_hypothesis`. An investigation that cannot settle a
hypothesis on the evidence held is not finished and should not pretend to be: it should say what
it needs. That call is what turns "insufficient evidence" into a question addressed to the
taxpayer, with the hypothesis recorded on the thread so the investigation can notice when the
answer arrives.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import (
    AuditCase, CorrespondenceMessage, CorrespondenceThread, EventLog, InformationRequest,
    PersistedHypothesis, ReceivedDocument,
)
from ..models.correspondence import (
    BY_AI_DRAFTED, BY_AUDITOR, BY_TAXPAYER, DIRECTION_IN, DIRECTION_OUT, ORIGIN_CLARIFICATION,
    ORIGIN_INITIAL, ORIGIN_INVESTIGATION, STATUS_CLOSED, STATUS_OPEN,
)
from ..models.investigation import STATUS_PENDING_INFO


def threads(db, case_id: str) -> list[CorrespondenceThread]:
    return list(db.scalars(
        select(CorrespondenceThread).where(CorrespondenceThread.case_id == case_id)
        .order_by(CorrespondenceThread.seq)).all())


def open_thread(db, case_id: str) -> CorrespondenceThread | None:
    """The one thread currently accepting documents, if any."""
    return db.scalars(
        select(CorrespondenceThread).where(CorrespondenceThread.case_id == case_id,
                                           CorrespondenceThread.status == STATUS_OPEN)
        .order_by(CorrespondenceThread.seq.desc())).first()


def start(db, case_id: str, *, subject: str, origin: str = ORIGIN_INITIAL,
          hypothesis_id: str = "") -> CorrespondenceThread:
    """Open a thread, closing whatever was open before it.

    Closing rather than refusing: an auditor who needs to ask a new question should not have to
    tidy up the last one first, and the previous thread is not lost — it moves into the history
    with everything that happened on it.
    """
    previous = open_thread(db, case_id)
    if previous is not None:
        previous.status = STATUS_CLOSED
        previous.closed_at = datetime.now(timezone.utc)

    seq = 1 + len(threads(db, case_id))
    row = CorrespondenceThread(
        case_id=case_id, seq=seq, subject=subject.strip() or f"Enquiry {seq}",
        status=STATUS_OPEN, origin=origin, origin_hypothesis_id=hypothesis_id)
    db.add(row)
    db.flush()
    db.add(EventLog(case_id=case_id, actor="auditor", action="thread-opened",
                    payload={"seq": seq, "origin": origin, "hypothesis_id": hypothesis_id}))
    return row


def add_message(db, thread: CorrespondenceThread, *, direction: str, body: str,
                subject: str = "", sender: str = "", recipient: str = "",
                drafted_by: str = BY_AUDITOR, audit_stage: str = "",
                request_id: int | None = None) -> CorrespondenceMessage:
    seq = 1 + len(list(thread.messages or []))
    msg = CorrespondenceMessage(
        case_id=thread.case_id, thread_id=thread.id, seq=seq, direction=direction,
        sender=sender or ("ZATCA" if direction == DIRECTION_OUT else "Taxpayer"),
        recipient=recipient or ("Taxpayer" if direction == DIRECTION_OUT else "ZATCA"),
        subject=subject or thread.subject, body=body, drafted_by=drafted_by,
        in_reply_to_seq=seq - 1 if seq > 1 else None,
        audit_stage=audit_stage, request_id=request_id)
    db.add(msg)
    db.flush()
    return msg


def open_for_hypothesis(db, case: AuditCase, hypothesis_id: str, *, note: str = "",
                        draft: str = "") -> CorrespondenceThread:
    """The loop: an investigation that needs more evidence goes back to the taxpayer.

    The hypothesis is marked `pending-info` and linked to the thread. Neither half is
    decoration: the status stops it being read as a settled verdict when it is really an
    unanswered question, and the link is how the investigation later notices that the answer
    has arrived and offers to re-test *this* hypothesis rather than simply re-running
    everything.
    """
    h = db.scalar(select(PersistedHypothesis).where(
        PersistedHypothesis.case_id == case.case_id,
        PersistedHypothesis.hypothesis_id == hypothesis_id))
    if h is None:
        raise LookupError(f"{hypothesis_id} is not on this case")

    subject = f"Further information — {case.case_id}"
    thread = start(db, case.case_id, subject=subject, origin=ORIGIN_INVESTIGATION,
                   hypothesis_id=hypothesis_id)
    if draft:
        add_message(db, thread, direction=DIRECTION_OUT, body=draft, subject=subject,
                    drafted_by=BY_AI_DRAFTED, audit_stage="investigation")

    h.status = STATUS_PENDING_INFO
    h.needs_info_note = note.strip()
    h.linked_thread_id = thread.id
    db.add(EventLog(case_id=case.case_id, actor="auditor", action="information-requested",
                    payload={"hypothesis_id": hypothesis_id, "thread": thread.seq,
                             "note": note[:200]}))
    db.commit()
    db.refresh(thread)
    return thread


def record_reply(db, case_id: str, *, body: str, subject: str = "") -> CorrespondenceMessage:
    """What the taxpayer wrote back, in their own words.

    Kept verbatim and marked as theirs. A taxpayer's account of their own records is evidence
    of what they say, not of what is true, and the trail has to keep the two apart.
    """
    thread = open_thread(db, case_id)
    if thread is None:
        thread = start(db, case_id, subject=subject or "Taxpayer correspondence",
                       origin=ORIGIN_CLARIFICATION)
    msg = add_message(db, thread, direction=DIRECTION_IN, body=body, subject=subject,
                      drafted_by=BY_TAXPAYER, audit_stage="correspondence")
    db.add(EventLog(case_id=case_id, actor="taxpayer", action="reply-recorded",
                    payload={"thread": thread.seq, "seq": msg.seq}))
    db.commit()
    return msg


def retestable(db, case_id: str) -> list[dict]:
    """Hypotheses waiting on the taxpayer whose thread has since received something.

    The question this answers is "has the thing we asked for arrived?", so it compares against
    documents on the thread rather than against the case as a whole — a file uploaded for a
    different enquiry is not an answer to this one.
    """
    out: list[dict] = []
    waiting = db.scalars(select(PersistedHypothesis).where(
        PersistedHypothesis.case_id == case_id,
        PersistedHypothesis.status == STATUS_PENDING_INFO)).all()
    for h in waiting:
        if not h.linked_thread_id:
            continue
        docs = db.scalars(select(ReceivedDocument).where(
            ReceivedDocument.case_id == case_id,
            ReceivedDocument.thread_id == h.linked_thread_id)).all()
        if docs:
            out.append({"hypothesis_id": h.hypothesis_id, "claim": h.claim,
                        "documents": [d.filename for d in docs],
                        "note": h.needs_info_note})
    return out


_ATTACHED = re.compile(
    r"\b(attach(ed|ing|ment|ments)?|enclos(ed|ing|ure|ures)?|herewith|please find)\b", re.I)


def missing_attachments(db, case_id: str) -> list[dict]:
    """The taxpayer's reply says they attached something, and nothing arrived on that thread.

    Worth a deterministic check because it is a *silent* failure: an email whose attachment was
    stripped or forgotten reads, in the trail, exactly like an answered request. The auditor
    waits, the taxpayer believes they have replied, and the round quietly costs weeks. All this
    claims is that the words and the files disagree — which of the two is wrong is not for a
    regex to say.
    """
    out: list[dict] = []
    for t in threads(db, case_id):
        docs = db.scalars(select(ReceivedDocument).where(
            ReceivedDocument.case_id == case_id,
            ReceivedDocument.thread_id == t.id)).all()
        if docs:
            continue
        for m in (t.messages or []):
            if m.direction == DIRECTION_IN and _ATTACHED.search(m.body or ""):
                out.append({"thread_id": t.id, "thread_seq": t.seq, "message_seq": m.seq,
                            "detail": "The reply refers to an attachment, but no document has "
                                      "been filed against this enquiry."})
                break
    return out


def state(db, case_id: str) -> dict:
    """The whole trail, oldest first — what was asked, what came back, and why each thread began."""
    rows = threads(db, case_id)
    docs = db.scalars(select(ReceivedDocument)
                      .where(ReceivedDocument.case_id == case_id)).all()
    by_thread: dict[int, list] = {}
    for d in docs:
        by_thread.setdefault(d.thread_id or 0, []).append(d)

    def one(t: CorrespondenceThread) -> dict:
        return {
            "id": t.id, "seq": t.seq, "subject": t.subject, "status": t.status,
            "origin": t.origin, "origin_hypothesis_id": t.origin_hypothesis_id,
            "opened_at": t.opened_at.isoformat() if t.opened_at else "",
            "closed_at": t.closed_at.isoformat() if t.closed_at else "",
            "messages": [{
                "seq": m.seq, "direction": m.direction, "sender": m.sender,
                "recipient": m.recipient, "subject": m.subject, "body": m.body,
                "drafted_by": m.drafted_by, "audit_stage": m.audit_stage,
                "in_reply_to_seq": m.in_reply_to_seq,
                "sent_at": m.sent_at.isoformat() if m.sent_at else "",
                "created_at": m.created_at.isoformat() if m.created_at else "",
            } for m in (t.messages or [])],
            "documents": [{"id": d.id, "filename": d.filename, "file_format": d.file_format,
                           "rows": len((d.content or {}).get("rows") or []),
                           "columns": len((d.content or {}).get("columns") or [])}
                          for d in by_thread.get(t.id, [])],
        }

    return {
        "case_id": case_id,
        "threads": [one(t) for t in rows],
        "open_thread_id": (open_thread(db, case_id) or CorrespondenceThread(id=0)).id or None,
        "retestable": retestable(db, case_id),
        "missing_attachments": missing_attachments(db, case_id),
        # documents that arrived before threads existed, or outside any enquiry
        "unfiled_documents": [{"id": d.id, "filename": d.filename}
                              for d in by_thread.get(0, [])],
    }
