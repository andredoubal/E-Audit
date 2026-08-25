"""The ZATCA dataset on a case: hold it, and compare it against the taxpayer's listing.

Thin by design. `pipeline/reconciliation.py` is a pure function of two extracted files and knows
nothing about the database; this module is the only place that reads rows and writes them, so
the matcher stays trivially testable and there is exactly one assembly of the comparison for the
API, the agents and the UI to share.

**One dataset per case.** A second upload replaces the first rather than accumulating: two
versions of the Authority's own records for one period is not a state an auditor should have to
resolve, and "which of these is current" is precisely the ambiguity the correspondence threads
exist to avoid elsewhere. The replaced file is not kept, because unlike a taxpayer's document it
is not evidence about the taxpayer — it is our own extract, and we can produce it again.

**The comparison is derived, never stored.** It is a pure function of two files that already
live on the case, so recomputing costs nothing and there is no stale mismatch to reconcile when
either side changes. `casefile/` makes the same choice about the lifecycle for the same reason.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select

from ..models import AuditCase, EventLog, ZatcaDataset
from ..pipeline import reconciliation as zr
from ..pipeline.source import pick_listing
from ..requests import extract as extractor
from ..requests import service as req_service


def dataset(db, case_id: str) -> ZatcaDataset | None:
    return db.scalar(select(ZatcaDataset).where(ZatcaDataset.case_id == case_id)
                     .order_by(ZatcaDataset.id.desc()))


def record(db, case: AuditCase, *, filename: str, data: bytes | None = None,
           structure: dict | None = None, source: str = "upload") -> ZatcaDataset:
    """Store the Authority's extract for this case, replacing any earlier one."""
    if structure is not None:
        content = extractor.from_structure(structure)
    else:
        content = extractor.extract(filename, data or b"")

    db.execute(delete(ZatcaDataset).where(ZatcaDataset.case_id == case.case_id))
    row = ZatcaDataset(
        case_id=case.case_id, filename=filename, file_format=content.get("format", ""),
        uploaded_at=date.today(), source=source, content=content,
        extraction_note=content.get("note", ""))
    db.add(row)
    db.flush()
    db.add(EventLog(case_id=case.case_id, actor="auditor", action="zatca-dataset-loaded",
                    payload={"filename": filename, "rows": content.get("row_count", 0)}))
    db.commit()
    db.refresh(row)
    return row


def remove(db, case_id: str) -> int:
    n = db.execute(delete(ZatcaDataset).where(ZatcaDataset.case_id == case_id)).rowcount or 0
    if n:
        db.add(EventLog(case_id=case_id, actor="auditor", action="zatca-dataset-removed",
                        payload={}))
    db.commit()
    return n


def _listing(db, case_id: str) -> dict | None:
    """The taxpayer's sales listing, chosen exactly as the qualification pipeline chooses it.

    Reusing `pick_listing` rather than re-deriving it matters: a comparison run against a
    different document from the one the expected figure was computed from would produce two
    findings about two populations while appearing to describe one.
    """
    docs = [{"id": d.id, "filename": d.filename,
             "columns": (d.content or {}).get("columns", []),
             "rows": (d.content or {}).get("rows", [])}
            for d in req_service.documents(db, case_id)]
    return pick_listing(docs, "sale")


def comparison(db, case: AuditCase) -> zr.Comparison:
    """Match the two populations as they stand right now."""
    listing = _listing(db, case.case_id)
    held = dataset(db, case.case_id)
    return zr.compare(
        listing=listing,
        zatca=(held.content if held else None),
        listing_name=(listing or {}).get("filename", ""),
        zatca_name=(held.filename if held else ""))


def state(db, case: AuditCase) -> dict:
    """Everything the UI needs: what is loaded, and what comparing it produced."""
    held = dataset(db, case.case_id)
    out = comparison(db, case).to_dict()
    out["dataset"] = None if held is None else {
        "id": held.id, "filename": held.filename, "format": held.file_format,
        "source": held.source,
        "uploaded_at": held.uploaded_at.isoformat() if held.uploaded_at else "",
        "row_count": (held.content or {}).get("row_count", 0),
        "columns": (held.content or {}).get("columns", []),
        "note": held.extraction_note,
    }
    return out


def context_entry(db, case: AuditCase) -> dict:
    """The comparison as the agents see it — the same dict, assembled once."""
    return comparison(db, case).to_dict()
