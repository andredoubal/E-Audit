"""What the auditor wrote themselves: report fields they filled in, and letters they edited.

The report and the verdict letter are **drafts a person signs**, not machine output that
happens to be displayed. Two consequences the rest of the application does not have to handle:

* **`[for the auditor to complete]` is an instruction.** The template asks for rulings, for
  penalties, for a meeting date — judgements the tool has no business making and, until this
  existed, no way for anyone to supply. A report that names the gap and then offers no way to
  close it is a form you cannot fill in.
* **Nothing here is a computed number.** These rows hold the auditor's own words, so the core
  invariant is untouched: the engine still computes every figure, and Claude still writes only
  language it is checked on. What is new is a third author, and the file records which one
  wrote each line.

**An edit never destroys what it replaced.** `original` keeps the value the engine or the
template produced, so an auditor can see what the tool said before they overrode it and can put
it back. A report where "no finding was established" had been quietly replaced, with no way to
tell it had been, would be worse than one with no editing at all.

Both tables are keyed naturally — `(case_id, field_key)` and `(case_id, kind)` — so saving twice
updates one row rather than accumulating a history nobody reads. They live in `core` because
they are case facts: acts of a person, not derived state a re-run may legitimately change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

CORE = "core"

# The letters a case can carry a saved draft of. A closed set: an edit is stored against the
# draft it replaces, so a kind nothing generates would be an edit of nothing.
LETTER_VERDICT = "verdict"
LETTER_FOLLOWUP = "follow-up"
LETTER_KINDS = (LETTER_VERDICT, LETTER_FOLLOWUP)


class ReportFieldEdit(Base):
    """One field of the audit report, as the auditor wrote it.

    `field_key` is `"<section title>::<field label>"` rather than the label alone — labels are
    unique today but the template is the client's and may not stay that way, and a collision
    would silently write one section's value into another's.
    """
    __tablename__ = "report_field_edit"
    __table_args__ = (UniqueConstraint("case_id", "field_key", name="uq_report_field_edit"),
                      {"schema": CORE})

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    field_key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text, default="")
    # What the report said before the auditor touched it, so the override is visible and
    # reversible. Empty when the field was a gap the auditor filled rather than a value they
    # replaced.
    original: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[str] = mapped_column(String(60), default="auditor")
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LetterDraft(Base):
    """A letter as the auditor edited it, kept against the generated draft it replaces.

    Not a `CorrespondenceMessage`: that table is the trail of what was actually said, and a
    draft nobody has sent yet is not part of the correspondence. Filing it there would make the
    case file claim a letter went out when it is still being written.
    """
    __tablename__ = "letter_draft"
    __table_args__ = (UniqueConstraint("case_id", "kind", name="uq_letter_draft"),
                      {"schema": CORE})

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    # The generated text this was edited from. Keeping it is what makes "restore the draft"
    # possible, and what lets the UI say the letter is no longer what the engine wrote.
    original: Mapped[str] = mapped_column(Text, default="")
    edited_by: Mapped[str] = mapped_column(String(60), default="auditor")
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
