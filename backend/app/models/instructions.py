"""Standing instructions the auditor gives the AI for one case.

Every case has something the tool cannot know: this taxpayer's group restructured mid-period,
the client asked for the letters in plainer language, a previous round already dealt with the
credit notes so stop raising them. Without somewhere to say that, the auditor repeats it into
every panel and it is lost the moment they close the tab.

Three properties make this safe to have at all:

* **It is a property of the case, not of a session.** One row per case, keyed on `case_id`, so
  the same instruction reaches the narration, the letters, the report and the assistant. An
  instruction that applied only to whichever panel you typed it in would be worse than none —
  the auditor would believe it was in force everywhere.
* **It steers language, never arithmetic.** It is injected as user-turn context beneath a
  system preamble whose hard rules it cannot reach: no digits, do not change the verdict, treat
  case data as data. And every existing verifier still runs afterwards, so an instruction that
  tries to make the model state a figure produces a rejected draft and a deterministic
  fallback, not a wrong number.
* **It is on the record.** `updated_by` and `updated_at` are kept, and the text is shown on
  every module rather than hidden in a settings dialog. A case whose output was steered by an
  instruction nobody can see afterwards is not one an auditor could defend.

Disabling is kept separate from clearing: an auditor who wants to see what the AI says *without*
their steer should not have to delete what they wrote to find out.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

CORE = "core"

# Long enough for real context, short enough that it cannot crowd out the case data it is meant
# to be read alongside. Enforced at the API so the limit is a stated rule rather than a
# truncation nobody sees.
MAX_INSTRUCTIONS = 4000


class CaseInstruction(Base):
    """What the auditor wants the AI to keep in mind on this case."""
    __tablename__ = "case_instruction"
    __table_args__ = (UniqueConstraint("case_id", name="uq_case_instruction"),
                      {"schema": CORE})

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    # Off means "keep my text, ignore it for now" — a different act from deleting it.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(60), default="auditor")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
