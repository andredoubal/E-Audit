"""The correspondence trail: every exchange with the taxpayer, in order, with what came with it.

Until now a case had one linear sequence of `InformationRequest` rounds and exactly one letter
body per round — the request. Follow-ups and verdicts were drafted on demand and never stored,
so re-opening a case showed a freshly generated letter rather than the one that was actually
sent. There was no record of what the taxpayer wrote back, and no way to say that this round of
questions came out of something the investigation found.

Two objects fix that:

* **`CorrespondenceThread`** groups the rounds, documents and letters that belong to one line of
  enquiry. `origin_hypothesis_id` is the load-bearing field: it records that a thread exists
  *because* a hypothesis needed evidence, which is what lets the investigation notice when the
  answer arrives and offer to re-test.
* **`CorrespondenceMessage`** is the trail itself — outbound and inbound, dated, attributed, and
  marked with whether a person wrote it or a model drafted it.

**One thread is open at a time; closed ones accumulate.** Arbitrary parallel threads would make
"which conversation does this upload belong to" ambiguous for no audit benefit, and the answer
has to be unambiguous — a document filed against the wrong request is a completeness check
answering the wrong question. Unlimited *closed* threads still give the full history the work
needs.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import String, Integer, Date, DateTime, JSON, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

CORE = "core"

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"

# Why this thread exists. `investigation-request` is the one that matters: it means an agent
# could not settle a hypothesis on the evidence held, and the auditor went back to the taxpayer.
ORIGIN_INITIAL = "initial"
ORIGIN_INVESTIGATION = "investigation-request"
ORIGIN_CLARIFICATION = "clarification"

DIRECTION_OUT = "outbound"
DIRECTION_IN = "inbound"

# Who actually wrote it. An auditor defending a letter needs to know whether they wrote it or
# edited a draft, and a taxpayer's own words must never be confused with a generated summary.
BY_AUDITOR = "auditor"
BY_AI_ASSISTED = "ai-assisted"
BY_AI_DRAFTED = "ai-drafted"
BY_TAXPAYER = "taxpayer"


class CorrespondenceThread(Base):
    """One line of enquiry with the taxpayer, from the question to the answer."""
    __tablename__ = "correspondence_thread"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)          # 1-based, per case
    subject: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN)
    origin: Mapped[str] = mapped_column(String(30), default=ORIGIN_INITIAL)
    # the hypothesis that could not be settled without this — the Investigation -> Correspondence
    # link, and what the investigation watches to know new evidence has landed for it
    origin_hypothesis_id: Mapped[str] = mapped_column(String(30), default="")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["CorrespondenceMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan",
        order_by="CorrespondenceMessage.seq")


class CorrespondenceMessage(Base):
    """One message in a thread — what was said, by whom, and what came with it."""
    __tablename__ = "correspondence_message"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey(f"{CORE}.correspondence_thread.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    direction: Mapped[str] = mapped_column(String(12), default=DIRECTION_OUT)
    sender: Mapped[str] = mapped_column(String(160), default="")
    recipient: Mapped[str] = mapped_column(String(160), default="")
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # auditor | ai-assisted | ai-drafted | taxpayer — a letter the auditor wrote and one they
    # approved from a draft are different things, and the file should say which
    drafted_by: Mapped[str] = mapped_column(String(20), default=BY_AUDITOR)
    in_reply_to_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # which stage of the audit this belongs to, for reading the trail back later
    audit_stage: Mapped[str] = mapped_column(String(30), default="")
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CORE}.information_request.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    thread: Mapped[CorrespondenceThread] = relationship(back_populates="messages")


class CaseMessage(Base):
    """One turn of the case assistant — the auditor's question, or its answer.

    There is **one conversation per case**, not one per module. An auditor's question about a
    case spans what arrived, what the tests said and what will be written; splitting the
    transcript three ways would make them pick a tab before they could ask, and remember which
    panel they asked in.

    `action_kind` is the entry from the assistant's closed set that this turn selected, and
    `action_payload` the engine-computed facts the answer was built from. Storing both is what
    makes an answer checkable after the fact: not merely that the assistant said something, but
    which of the application's own capabilities it ran and what that returned. `did` is set only
    when the turn actually changed something on the case, so a reader can tell an answer apart
    from an action.
    """
    __tablename__ = "case_message"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(12))              # auditor | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    action_kind: Mapped[str] = mapped_column(String(30), default="")
    action_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(24), default="deterministic")
    did: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
