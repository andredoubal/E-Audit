"""What the auditor wrote themselves: report fields they filled in, and letters they edited."""
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
