"""Standing instructions the auditor gives the AI for one case."""
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
