"""The auditor's verdict on one thing the application worked out."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

CORE = "core"

APPROVED = "approved"
CHALLENGED = "challenged"
VERDICTS = (APPROVED, CHALLENGED)

# What can be reviewed. A closed set: a review is stored against something the application
# actually produces, so a kind nothing renders would be a review of nothing.
KIND_COMPLETENESS = "completeness-item"      # one row of the documents-received analysis
KIND_ZATCA = "zatca-mismatch"                # one disagreement with the Authority's own records
KINDS = (KIND_COMPLETENESS, KIND_ZATCA)


class ItemReview(Base):
    """One approve-or-challenge, against one thing the application concluded."""
    __tablename__ = "item_review"
    __table_args__ = (UniqueConstraint("case_id", "item_kind", "item_key",
                                       name="uq_item_review"),
                      {"schema": CORE})

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    item_kind: Mapped[str] = mapped_column(String(30))
    # Stable within its kind — the catalog key of a request item, the rule code and reference of
    # a mismatch. Deliberately not a row id: these are recomputed on every request, so an id
    # would point at nothing by the time the auditor came back to it.
    item_key: Mapped[str] = mapped_column(String(160))
    verdict: Mapped[str] = mapped_column(String(20))
    # Required on a challenge. "The auditor disagreed" with no reason is not something anyone
    # can act on later, least of all the auditor themselves.
    note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(60), default="auditor")
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
