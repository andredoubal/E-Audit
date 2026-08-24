"""What each uploaded file is, read from its contents and published with its reasoning.

Stage 0 of the investigation. Nothing downstream — which reconciliations are possible, which
regulatory controls are testable, what the funnel counts — can be decided until this has run,
and until it ran the application decided all of it from filenames.

Three rules shape it.

**A classification is a claim, so it carries its evidence.** Every profile states the dataset
type, a confidence, and the reason in words an auditor can check: *"rows carry a customer name
and a VAT amount, and no account code, so this reads as a sales register."* A classification the
auditor cannot interrogate is worse than the filename guess it replaces, because the filename
guess was at least predictable.

**Ambiguity is an answer.** A file that names both customers and suppliers, or carries none of
the roles a reconciliation needs, is `unknown` with the reason stated — never resolved by
precedence into whichever type happened to be checked first. `unknown` is correctable by the
auditor; a confident wrong answer is not, because nobody looks.

**Nothing is corrected silently.** Where a value has to be normalised to be read at all — a date
parsed out of text, a number parsed out of a formatted string — the original, the normalised
value, the transformation and the reason are all recorded. The reconciliation must be replayable
from the raw file, which it cannot be if the pipeline quietly repairs its inputs.

The filename is used for exactly one thing: as a **tie-break** between two types the contents
support equally well, recorded as such. It is never sufficient on its own, and it never
overrides what the columns say.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..agents.calculation import as_date, as_number
from . import roles as R

# ---------------------------------------------------------------- dataset types
SALES_REGISTER = "sales-register"
PURCHASE_REGISTER = "purchase-register"
CREDIT_NOTE_LISTING = "credit-note-listing"
EINVOICE_EXTRACT = "einvoice-extract"
GENERAL_LEDGER = "general-ledger"
TRIAL_BALANCE = "trial-balance"
BANK_STATEMENT = "bank-statement"
POS_REPORT = "pos-report"
CUSTOMS_RECORDS = "customs-records"
FIXED_ASSETS = "fixed-asset-register"
UNKNOWN = "unknown"

#: Which workstream a type belongs to. `both` means the file bears on either side and the
#: reconciliation planner decides per test; `unknown` means it bears on neither until someone
#: says otherwise.
WORKSTREAM: dict[str, str] = {
    SALES_REGISTER: "sales",
    PURCHASE_REGISTER: "purchases",
    CREDIT_NOTE_LISTING: "both",
    EINVOICE_EXTRACT: "both",
    GENERAL_LEDGER: "both",
    TRIAL_BALANCE: "both",
    BANK_STATEMENT: "both",
    POS_REPORT: "sales",
    CUSTOMS_RECORDS: "both",
    FIXED_ASSETS: "purchases",
    UNKNOWN: "unknown",
}

LABEL: dict[str, str] = {
    SALES_REGISTER: "Sales register",
    PURCHASE_REGISTER: "Purchases register",
    CREDIT_NOTE_LISTING: "Credit and debit note listing",
    EINVOICE_EXTRACT: "E-invoice extract",
    GENERAL_LEDGER: "General ledger",
    TRIAL_BALANCE: "Trial balance",
    BANK_STATEMENT: "Bank statement",
    POS_REPORT: "Point-of-sale report",
    CUSTOMS_RECORDS: "Customs records",
    FIXED_ASSETS: "Fixed asset register",
    UNKNOWN: "Not classified",
}

#: How *specific* a reading is. Where two readings are equally well supported by the contents
#: and one is a specialisation of the other — a credit-note listing is a sales-side document,
#: an e-invoice extract is a listing with clearance behind it — the specific one wins rather
#: than the pair being reported as an unresolvable tie.
_SPECIFICITY: dict[str, int] = {
    CREDIT_NOTE_LISTING: 3,
    EINVOICE_EXTRACT: 3,
    CUSTOMS_RECORDS: 3,
    POS_REPORT: 3,
    TRIAL_BALANCE: 2,
    GENERAL_LEDGER: 2,
    BANK_STATEMENT: 2,
    FIXED_ASSETS: 2,
    SALES_REGISTER: 1,
    PURCHASE_REGISTER: 1,
}

#: Filename fragments, used only to break a tie between equally-supported types.
_NAME_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SALES_REGISTER, ("sales", "revenue", "output", "sale")),
    (PURCHASE_REGISTER, ("purchase", "input", "expense", "procurement")),
    (CREDIT_NOTE_LISTING, ("credit", "debit_note", "cn_", "note")),
    (EINVOICE_EXTRACT, ("einvoice", "e-invoice", "fatoora", "zatca", "clearance")),
    (GENERAL_LEDGER, ("ledger", "gl_", "_gl", "journal")),
    (TRIAL_BALANCE, ("trial", "balance", "_tb", "tb_")),
    (BANK_STATEMENT, ("bank", "statement", "account_activity")),
    (POS_REPORT, ("pos", "point_of_sale", "till", "terminal")),
    (CUSTOMS_RECORDS, ("customs", "import", "export", "declaration", "bayan")),
    (FIXED_ASSETS, ("asset", "fixed_asset", "fa_register")),
)


# ---------------------------------------------------------------- transformations
@dataclass
class Transformation:
    """One value the pipeline had to change to read it, and why."""

    column: str
    row_number: int
    original: str
    normalised: str
    transformation: str
    reason: str

    def to_dict(self) -> dict:
        return {"column": self.column, "row_number": self.row_number,
                "original": self.original, "normalised": self.normalised,
                "transformation": self.transformation, "reason": self.reason}


# ---------------------------------------------------------------- quality
@dataclass
class QualityFlag:
    code: str
    detail: str
    count: int = 0
    column: str = ""
    severity: str = "advisory"          # advisory | blocking
    rows: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "count": self.count,
                "column": self.column, "severity": self.severity, "rows": self.rows[:25]}


_MAX_CITED_ROWS = 25


def _cell(row: list[Any], i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def quality(columns: list[str], rows: list[list[Any]], detected: list[R.Role],
            document_totals: dict | None = None,
            ) -> tuple[list[QualityFlag], list[Transformation]]:
    """Everything wrong with the file that can be established from the file itself.

    Reported, never repaired. A malformed date is a fact about the evidence, and an auditor
    asking the taxpayer for a corrected listing needs to be able to name the rows.
    """
    flags: list[QualityFlag] = []
    changes: list[Transformation] = []
    if not rows:
        return [QualityFlag("empty-dataset", "The file carries no data rows.",
                            severity="blocking")], []

    idx = {c: i for i, c in enumerate(columns)}

    # --- rows that are entirely blank
    blank = [n for n, r in enumerate(rows, start=1)
             if all(v is None or (isinstance(v, str) and not v.strip()) for v in r)]
    if blank:
        flags.append(QualityFlag("blank-rows", "Rows carrying no values at all.",
                                 count=len(blank), rows=blank[:_MAX_CITED_ROWS]))

    # --- per-role checks over the columns that matter
    for role_name in R.DATES:
        r = R.best(detected, role_name)
        if not r or r.column not in idx:
            continue
        i = idx[r.column]
        bad: list[int] = []
        for n, row in enumerate(rows, start=1):
            v = _cell(row, i)
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            parsed = as_date(v)
            if parsed is None:
                bad.append(n)
            elif not isinstance(v, date) and str(v).strip() != parsed.isoformat():
                changes.append(Transformation(
                    column=r.column, row_number=n, original=str(v).strip(),
                    normalised=parsed.isoformat(), transformation="parsed as a date",
                    reason="the value was not already an ISO date"))
        if bad:
            flags.append(QualityFlag(
                "malformed-date",
                f"Values in '{r.column}' that could not be read as a date.",
                count=len(bad), column=r.column, rows=bad[:_MAX_CITED_ROWS]))

    for role_name in R.MONETARY:
        r = R.best(detected, role_name)
        if not r or r.column not in idx:
            continue
        i = idx[r.column]
        bad, negatives = [], []
        for n, row in enumerate(rows, start=1):
            v = _cell(row, i)
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            parsed = as_number(v)
            if parsed is None:
                bad.append(n)
                continue
            if parsed < 0:
                negatives.append(n)
            if not isinstance(v, (int, float)) and str(v).strip() != str(parsed):
                changes.append(Transformation(
                    column=r.column, row_number=n, original=str(v).strip(),
                    normalised=f"{parsed}", transformation="parsed as a number",
                    reason="the value carried formatting a number cannot hold"))
        if bad:
            flags.append(QualityFlag(
                "malformed-number",
                f"Values in '{r.column}' that could not be read as a number.",
                count=len(bad), column=r.column, rows=bad[:_MAX_CITED_ROWS],
                severity="blocking" if role_name == R.VAT_AMOUNT else "advisory"))
        # A mixed-sign monetary column is a fact about the file's conventions, not an error.
        # It matters because comparing it against a same-signed column would be wrong, so the
        # reconciliation layer has to be told rather than left to discover it.
        if negatives and len(negatives) < len([r for r in rows if _cell(r, i) is not None]):
            flags.append(QualityFlag(
                "mixed-signs",
                f"'{r.column}' carries both positive and negative values, so the file uses "
                f"signs to carry meaning. Comparisons must normalise before they subtract.",
                count=len(negatives), column=r.column, rows=negatives[:_MAX_CITED_ROWS]))

    # --- blanks in a column a comparison depends on. Reported per role rather than per column
    #     name, because what matters is that the *reference* is missing, not that a column
    #     called `invoice_number` is. A row with no reference cannot be matched to anything.
    for role_name, why in ((R.REFERENCE, "cannot be matched against another dataset"),
                           (R.VAT_AMOUNT, "cannot be summed into a VAT total"),
                           (R.ISSUE_DATE, "cannot be placed in a tax period")):
        r = R.best(detected, role_name)
        if not r or r.column not in idx:
            continue
        i = idx[r.column]
        empty = [n for n, row in enumerate(rows, start=1)
                 if _cell(row, i) is None
                 or (isinstance(_cell(row, i), str) and not str(_cell(row, i)).strip())]
        if empty:
            flags.append(QualityFlag(
                f"blank-{role_name.replace('_', '-')}",
                f"Rows with no value in '{r.column}'. Each one {why}.",
                count=len(empty), column=r.column, rows=empty[:_MAX_CITED_ROWS],
                severity="blocking" if role_name == R.VAT_AMOUNT else "advisory"))

    # --- the file's own stated total against its own rows, where it states one
    for column, stated in (document_totals or {}).items():
        i = idx.get(column)
        if i is None:
            continue
        value = as_number(stated)
        if value is None:
            continue
        summed = sum(n for n in (as_number(_cell(row, i)) for row in rows) if n is not None)
        if abs(summed - value) > max(1.0, abs(value) * 0.005):
            flags.append(QualityFlag(
                "stated-total-does-not-foot",
                f"The file states a total of {value:,.2f} for '{column}', but its own rows sum "
                f"to {summed:,.2f} — a difference of {value - summed:,.2f}.",
                column=column, severity="advisory"))

    # --- repeated references. Deliberately NOT called duplicates: an invoice legitimately
    #     appears on several accounting lines, and classifying that as a duplicate is one of the
    #     specific errors this engine must not make.
    ref = R.best(detected, R.REFERENCE)
    if ref and ref.column in idx:
        i = idx[ref.column]
        seen: dict[str, list[int]] = {}
        for n, row in enumerate(rows, start=1):
            v = _cell(row, i)
            key = str(v).strip().upper() if v is not None and str(v).strip() else ""
            if key:
                seen.setdefault(key, []).append(n)
        repeated = {k: v for k, v in seen.items() if len(v) > 1}
        if repeated:
            rowlist = sorted({n for ns in repeated.values() for n in ns})
            flags.append(QualityFlag(
                "repeated-reference",
                f"{len(repeated)} reference(s) in '{ref.column}' appear on more than one row. "
                f"This may be line-level accounting for one document rather than duplication, "
                f"and is tested rather than assumed.",
                count=len(repeated), column=ref.column, rows=rowlist[:_MAX_CITED_ROWS]))

    # --- inconsistent VAT rates, where both a rate and the amounts are present
    rate = R.best(detected, R.VAT_RATE)
    if rate and rate.column in idx:
        i = idx[rate.column]
        values = {as_number(_cell(r, i)) for r in rows if as_number(_cell(r, i)) is not None}
        if len(values) > 1:
            shown = ", ".join(f"{v:g}" for v in sorted(values)[:8])
            flags.append(QualityFlag(
                "multiple-vat-rates",
                f"'{rate.column}' carries more than one rate ({shown}). The file mixes VAT "
                f"treatments, so a single-rate check over it would be wrong.",
                count=len(values), column=rate.column))

    # --- VAT that does not follow from net x rate, where all three are present
    net_r, vat_r = R.best(detected, R.NET_AMOUNT), R.best(detected, R.VAT_AMOUNT)
    if net_r and vat_r and rate and all(c.column in idx for c in (net_r, vat_r, rate)):
        ni, vi, ri = idx[net_r.column], idx[vat_r.column], idx[rate.column]
        off: list[int] = []
        for n, row in enumerate(rows, start=1):
            net, vat, pct = (as_number(_cell(row, ni)), as_number(_cell(row, vi)),
                             as_number(_cell(row, ri)))
            if net is None or vat is None or pct is None:
                continue
            expected = net * (pct / 100.0)
            if abs(expected - vat) > max(1.0, abs(expected) * 0.01):
                off.append(n)
        if off:
            flags.append(QualityFlag(
                "vat-not-consistent-with-rate",
                f"Rows where the VAT amount does not follow from the net amount at the stated "
                f"rate, beyond a 1% tolerance.",
                count=len(off), rows=off[:_MAX_CITED_ROWS]))

    return flags, changes


# ---------------------------------------------------------------- classification
@dataclass
class Classification:
    dataset_type: str
    workstream: str
    confidence: str                 # high | medium | low
    why: str
    alternatives: list[str] = field(default_factory=list)


def _has(detected: list[R.Role], *names: str) -> bool:
    present = {r.role for r in detected}
    return all(n in present for n in names)


def _any(detected: list[R.Role], *names: str) -> bool:
    present = {r.role for r in detected}
    return any(n in present for n in names)


def _name_hint(filename: str) -> str:
    low = (filename or "").lower()
    for kind, fragments in _NAME_HINTS:
        if any(f in low for f in fragments):
            return kind
    return ""


def classify(filename: str, columns: list[str], rows: list[list[Any]],
             detected: list[R.Role]) -> Classification:
    """What this file is, from what it contains. The filename only breaks ties."""
    if not rows:
        return Classification(UNKNOWN, "unknown", "low",
                              "the file carries no data rows to read")

    side, side_why = R.side_of(detected)
    has_vat = _any(detected, R.VAT_AMOUNT)
    has_ref = _any(detected, R.REFERENCE)
    has_dr_cr = _has(detected, R.DEBIT, R.CREDIT)
    has_account = _any(detected, R.ACCOUNT_CODE, R.ACCOUNT_NAME)
    has_balance = _any(detected, R.BALANCE)
    has_customs = _any(detected, R.CUSTOMS_DECLARATION)
    has_terminal = _any(detected, R.TERMINAL)
    has_status = _any(detected, R.STATUS)

    candidates: list[tuple[str, str, str]] = []      # (type, confidence, why)

    # An account structure is the strongest single signal there is: it says the file is an
    # accounting extract rather than a transaction listing, whatever else it carries.
    if has_account and has_dr_cr and not has_balance:
        candidates.append((GENERAL_LEDGER, "high",
                           "rows carry an account together with debit and credit columns"))
    if has_account and (has_balance or (has_dr_cr and not has_ref)):
        candidates.append((TRIAL_BALANCE, "high" if has_balance else "medium",
                           "rows carry accounts with balances rather than transactions"))

    if has_customs:
        candidates.append((CUSTOMS_RECORDS, "high",
                           "rows carry a customs declaration reference"))

    if has_terminal:
        candidates.append((POS_REPORT, "high",
                           "rows carry a terminal or till identifier"))

    if has_balance and not has_account and _any(detected, R.DESCRIPTION):
        candidates.append((BANK_STATEMENT, "medium",
                           "rows carry a running balance against dated descriptions, with no "
                           "account structure"))

    # A clearance status is what distinguishes the Authority's own extract from the taxpayer's
    # listing of the same invoices — the listing has no clearance behind it to report.
    if has_status and has_ref and has_vat:
        candidates.append((EINVOICE_EXTRACT, "high",
                           "rows carry invoices with a clearance status, which a taxpayer's own "
                           "listing does not have"))

    # Document-type or reference evidence dominated by notes.
    notes_share = _note_share(columns, rows, detected)
    if notes_share >= 0.6 and has_vat:
        candidates.append((CREDIT_NOTE_LISTING, "high" if notes_share >= 0.9 else "medium",
                           f"{notes_share:.0%} of rows are credit or debit notes"))

    # The transaction listings. The counterparty side is what separates them, and it is the
    # only thing that can — an amount column looks identical on either side.
    if has_vat and side == R.CUSTOMER:
        candidates.append((SALES_REGISTER, "high",
                           f"rows carry a VAT amount and {side_why}"))
    if has_vat and side == R.SUPPLIER:
        candidates.append((PURCHASE_REGISTER, "high",
                           f"rows carry a VAT amount and {side_why}"))

    # A file that names both a customer and a supplier is *contradictory*, not merely
    # under-described. The filename may fill a gap in what the contents say; it may never
    # resolve a disagreement inside them, because then the weakest signal on the case
    # overrules the strongest.
    contradictory = "ambiguous" in side_why

    if not candidates:
        if contradictory:
            return Classification(UNKNOWN, "unknown", "low", side_why)
        detail = ("rows carry a VAT amount but nothing identifies the counterparty, so the file "
                  "could be either a sales or a purchase listing"
                  if has_vat else
                  f"no combination of columns identifies this file — {side_why}")
        hint = _name_hint(filename)
        if hint:
            return Classification(
                hint, WORKSTREAM[hint], "low",
                f"{detail}. Classified from the filename alone, which is a weak signal — "
                f"confirm it before relying on the comparison.")
        return Classification(UNKNOWN, "unknown", "low", detail)

    # Where two readings are equally well supported and one is a *specialisation* of the other,
    # the specific one wins: a credit-note listing is a sales-side document, so those two are
    # not rivals and reporting them as an unresolvable tie would be pedantry.
    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (order[c[1]], -_SPECIFICITY.get(c[0], 0)))
    top = [c for c in candidates if c[1] == candidates[0][1]]
    if len(top) > 1:
        sharpest = max(_SPECIFICITY.get(c[0], 0) for c in top)
        if sum(1 for c in top if _SPECIFICITY.get(c[0], 0) == sharpest) == 1:
            top = [c for c in top if _SPECIFICITY.get(c[0], 0) == sharpest]

    if len(top) > 1:
        hint = _name_hint(filename)
        chosen = next((c for c in top if c[0] == hint), None)
        if chosen:
            others = ", ".join(LABEL[c[0]] for c in top if c[0] != chosen[0])
            return Classification(
                chosen[0], WORKSTREAM[chosen[0]], "medium",
                f"{chosen[2]}; the filename broke a tie against {others}",
                alternatives=[c[0] for c in top if c[0] != chosen[0]])
        others = ", ".join(LABEL[c[0]] for c in top[1:])
        return Classification(
            UNKNOWN, "unknown", "low",
            f"the contents support more than one reading equally — {LABEL[top[0][0]]} or "
            f"{others} — and the filename does not settle it",
            alternatives=[c[0] for c in top])

    kind, confidence, why = candidates[0]
    return Classification(kind, WORKSTREAM[kind], confidence, why,
                          alternatives=[c[0] for c in candidates[1:3]])


def _note_share(columns: list[str], rows: list[list[Any]], detected: list[R.Role]) -> float:
    """How much of the file is credit or debit notes, from whatever signal the file gives."""
    idx = {c: i for i, c in enumerate(columns)}
    doc = R.best(detected, R.DOCUMENT_TYPE)
    hits = 0
    if doc and doc.column in idx:
        i = idx[doc.column]
        for row in rows:
            if re.search(r"credit|debit|note|cn|dn", str(_cell(row, i) or ""), re.I):
                hits += 1
        return hits / len(rows) if rows else 0.0
    ref = R.best(detected, R.REFERENCE)
    if ref and ref.column in idx:
        i = idx[ref.column]
        for row in rows:
            if re.match(r"\s*(cn|dn|cr)[-_ ]", str(_cell(row, i) or ""), re.I):
                hits += 1
        return hits / len(rows) if rows else 0.0
    return 0.0


# ---------------------------------------------------------------- the profile
@dataclass
class Profile:
    filename: str
    file_format: str
    dataset_type: str
    dataset_label: str
    workstream: str
    confidence: str
    why: str
    alternatives: list[str]
    record_count: int
    column_count: int
    columns: list[str]
    roles: list[dict]
    unmapped_columns: list[str]
    date_min: str | None
    date_max: str | None
    date_role: str
    currencies: list[str]
    quality_flags: list[dict]
    transformations: list[dict]
    stated_totals: dict

    def to_dict(self) -> dict:
        return {
            "filename": self.filename, "file_format": self.file_format,
            "dataset_type": self.dataset_type, "dataset_label": self.dataset_label,
            "workstream": self.workstream, "confidence": self.confidence, "why": self.why,
            "alternatives": [LABEL.get(a, a) for a in self.alternatives],
            "record_count": self.record_count, "column_count": self.column_count,
            "columns": self.columns, "roles": self.roles,
            "unmapped_columns": self.unmapped_columns,
            "date_min": self.date_min, "date_max": self.date_max, "date_role": self.date_role,
            "currencies": self.currencies,
            "quality_flags": self.quality_flags, "transformations": self.transformations,
            "stated_totals": self.stated_totals,
        }


def _date_span(columns: list[str], rows: list[list[Any]],
               detected: list[R.Role]) -> tuple[str | None, str | None, str]:
    """The period the file covers, from the most authoritative date role it carries."""
    idx = {c: i for i, c in enumerate(columns)}
    for role_name in (R.ISSUE_DATE, R.SUPPLY_DATE, R.POSTING_DATE, R.PAYMENT_DATE):
        r = R.best(detected, role_name)
        if not r or r.column not in idx:
            continue
        i = idx[r.column]
        found = [d for d in (as_date(_cell(row, i)) for row in rows) if d is not None]
        if found:
            return min(found).isoformat(), max(found).isoformat(), role_name
    return None, None, ""


def _currencies(columns: list[str], rows: list[list[Any]],
                detected: list[R.Role]) -> list[str]:
    idx = {c: i for i, c in enumerate(columns)}
    r = R.best(detected, R.CURRENCY)
    if not r or r.column not in idx:
        return []
    i = idx[r.column]
    seen = {str(_cell(row, i)).strip().upper() for row in rows
            if _cell(row, i) is not None and str(_cell(row, i)).strip()}
    return sorted(seen)[:12]


def build(document: dict) -> Profile:
    """Profile one extracted document. `document` is a `ReceivedDocument.content` payload."""
    filename = document.get("filename") or ""
    content = document.get("content") if "content" in document else document
    columns = list(content.get("columns") or [])
    rows = list(content.get("rows") or [])

    detected = R.detect(columns, rows)
    cls = classify(filename, columns, rows, detected)
    flags, changes = quality(columns, rows, detected,
                             content.get("stated_totals") or {})
    date_min, date_max, date_role = _date_span(columns, rows, detected)

    mapped = {r.column for r in detected}
    return Profile(
        filename=filename,
        file_format=content.get("format") or "",
        dataset_type=cls.dataset_type,
        dataset_label=LABEL.get(cls.dataset_type, cls.dataset_type),
        workstream=cls.workstream,
        confidence=cls.confidence,
        why=cls.why,
        alternatives=cls.alternatives,
        record_count=len(rows),
        column_count=len(columns),
        columns=columns,
        roles=[r.to_dict() for r in detected],
        unmapped_columns=[c for c in columns if c not in mapped],
        date_min=date_min, date_max=date_max, date_role=date_role,
        currencies=_currencies(columns, rows, detected),
        quality_flags=[f.to_dict() for f in flags],
        transformations=[t.to_dict() for t in changes[:200]],
        stated_totals=content.get("stated_totals") or {},
    )
