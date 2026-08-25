"""What the profiler decided about each uploaded file, and what the auditor decided instead.

The profile itself is **derived, not stored** — it is a pure function of a document's extracted
content, so recomputing it on demand is cheaper than keeping it in step, and there is no stale
classification to reconcile. That is the same rule the lifecycle and the ZATCA comparison follow.

What has to be stored is the one thing that cannot be derived: **the auditor's correction.** A
classifier that cannot be overruled is worse than the filename matching it replaces, because a
filename at least behaves predictably. So an override is a row, it says who set it and why, and
every consumer reads the override in preference to the reading.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class DatasetOverride(Base):
    """The auditor's own reading of what a file is, where they disagree with the profiler.

    Keyed on `(case_id, filename)` rather than on the document row id: a taxpayer who re-sends a
    corrected file under the same name is answering the same question, and an override the
    auditor already made should survive that. A file they rename is a new question.
    """

    __tablename__ = "dataset_override"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    filename: Mapped[str] = mapped_column(String(300), index=True)

    #: The type the auditor says this is. Empty clears the override and restores the reading.
    dataset_type: Mapped[str] = mapped_column(String(40), default="")
    #: Sales, purchases, both — set alongside the type, or on its own where the type is right
    #: and only the side is wrong.
    workstream: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")

    set_by: Mapped[str] = mapped_column(String(60), default="auditor")
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    #: What the profiler had said, kept beside the correction. An override nobody can compare
    #: against the original reading is not reviewable — and a classifier that is being
    #: overruled often is a classifier to fix.
    original_type: Mapped[str] = mapped_column(String(40), default="")
    original_confidence: Mapped[str] = mapped_column(String(10), default="")
