"""Matching the taxpayer's listing against ZATCA's own invoice records.

**This is deterministic on purpose, and it is not an agent.** Comparing two invoice
populations is a closed problem — join on the reference, diff the fields, count what is on one
side and not the other. Handing it to a model would make it slower, unreproducible and
unauditable, and it would put a model in front of a figure, which the core invariant forbids.
What the model layer gets instead is what this module produces: structured mismatch records
that the fifth roster agent turns into hypotheses, settled by the same adjudicator as
everything else.

**The rules are declarative**, in the same spirit as `pipeline/rules.py`: a `ReconRule` names
the shape it applies to, a predicate, and how to describe itself. Adding a comparison means
appending one entry to `RULES` — the matcher, the API and the UI all follow from it. A rule may
be narrowed to one `side` the way a qualification rule is narrowed by `direction`, because
"present here and not there" is not the same finding in each direction: an invoice ZATCA holds
and the taxpayer omitted is potentially undisclosed output tax, while one the taxpayer lists
and ZATCA never received is a clearance failure, which is a different conversation.

**One side alone is not a comparison.** With no ZATCA dataset, or no taxpayer listing, every
row on the side that exists would match nothing — and reporting all of them as mismatches
would be a fabricated finding of the worst kind, complete with an amount. `compare()`
therefore refuses, and says which side is missing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

TOLERANCE = 1.0        # SAR — the same one riyal the rest of the engine works to
MAX_CITED = 8          # enough rows for an auditor to find the problem; not a data dump

BLOCKING = "blocking"
ADVISORY = "advisory"

LISTING = "listing"    # the taxpayer's own uploaded document
ZATCA = "zatca"        # the Authority's records

# What a mismatch is *about*. The category is what the UI groups by and what the agent reads;
# the code identifies the individual rule.
OMISSION = "omission"            # on one side and not the other
VALUE = "value"                  # matched, but the figures disagree
TIMING = "timing"                # matched, but the dates disagree
PARTY = "party"                  # matched, but the counterparty disagrees
DUPLICATE = "duplicate"          # the same reference more than once on one side
IDENTIFIER = "identifier"        # nothing to match on
SEQUENCE = "sequence"            # a break in an otherwise contiguous numbering


# ------------------------------------------------------------------------------ the records

@dataclass(frozen=True)
class InvoiceRecord:
    """One invoice, normalised so the two populations can be compared field by field."""

    ref: str                      # normalised, for matching only
    row: int                      # 1-based row in its source file, so a mismatch can be found
    side: str
    # What the taxpayer actually wrote. Matching ignores punctuation and case, but an auditor
    # reading a mismatch has to find the invoice in their own spreadsheet — and "INV004" is not
    # a string that occurs in a file full of "INV-004".
    display: str = ""
    date: date | None = None
    counterparty: str = ""
    counterparty_vat: str = ""
    net: float | None = None
    vat: float | None = None
    status: str = ""              # the e-invoice status, when the source carries one

    @property
    def cite(self) -> str:
        return f"row {self.row}" + (f" ({self.shown})" if self.ref else "")

    @property
    def shown(self) -> str:
        return self.display or self.ref


@dataclass(frozen=True)
class Pair:
    """One reference present on both sides."""

    ref: str
    listing: InvoiceRecord
    zatca: InvoiceRecord


@dataclass(frozen=True)
class Mismatch:
    code: str
    category: str
    severity: str
    detail: str
    ref: str = ""
    field: str = ""
    listing_value: str = ""
    zatca_value: str = ""
    citation: str = ""
    # SAR this mismatch puts in question. Only the rules that genuinely carry money set it, and
    # the agent sums by category — so a value difference and an omission are never added
    # together into a single number that describes neither.
    vat_at_stake: float = 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code, "category": self.category, "severity": self.severity,
            "detail": self.detail, "ref": self.ref, "field": self.field,
            "listing_value": self.listing_value, "zatca_value": self.zatca_value,
            "citation": self.citation, "vat_at_stake": round(self.vat_at_stake, 2),
        }


# ------------------------------------------------------------------------------ the rules

# Which collection a rule is evaluated over. `side` narrows the last three.
PAIR = "pair"                 # every reference on both sides
UNMATCHED = "unmatched"       # every record with no counterpart
GROUP = "group"               # every set of records sharing a reference on one side
ROW = "row"                   # every record, matched or not
POPULATION = "population"     # the whole of one side, at once


@dataclass(frozen=True)
class ReconRule:
    """One comparison, declared rather than coded into the matcher."""

    code: str
    scope: str
    category: str
    severity: str
    when: Callable[[Any], bool]
    describe: Callable[[Any], "Mismatch | list[Mismatch] | None"]
    side: str = ""              # "" = both sides, for the scopes where that means anything
    note: str = ""              # what this rule is for, shown in the UI beside its findings


def _n(v) -> str:
    return "—" if v is None else f"{v:,.2f}"


def _sequence_mismatch(gaps: list[str]) -> "Mismatch":
    more = f" and {len(gaps) - MAX_CITED} more" if len(gaps) > MAX_CITED else ""
    return Mismatch(
        code="ZR-12", category=SEQUENCE, severity=ADVISORY,
        detail=f"The listing's invoice numbering skips {len(gaps)} "
               f"value{'' if len(gaps) == 1 else 's'} "
               f"({', '.join(gaps[:MAX_CITED])}{more}). This may be cancelled documents, or "
               f"invoices not included in the listing.",
        citation="listing numbering")


def _vat_gap(p: Pair) -> float:
    if p.listing.vat is None or p.zatca.vat is None:
        return 0.0
    return round(p.zatca.vat - p.listing.vat, 2)


RULES: tuple[ReconRule, ...] = (
    # ---------------------------------------------------------------- on one side only
    ReconRule(
        code="ZR-01", scope=UNMATCHED, side=ZATCA, category=OMISSION, severity=BLOCKING,
        note="Invoices ZATCA holds that the taxpayer's listing does not contain.",
        when=lambda r: True,
        describe=lambda r: Mismatch(
            code="ZR-01", category=OMISSION, severity=BLOCKING, ref=r.ref,
            detail=f"Invoice {r.shown or '(unnumbered)'} is in ZATCA's records but not in the "
                   f"listing supplied.",
            zatca_value=_n(r.vat), citation=r.cite, vat_at_stake=r.vat or 0.0),
    ),
    ReconRule(
        code="ZR-02", scope=UNMATCHED, side=LISTING, category=OMISSION, severity=ADVISORY,
        note="Invoices the taxpayer lists that never reached ZATCA. A clearance question "
             "rather than an output-tax one — the supply is declared, but the Authority has "
             "no record of the document.",
        when=lambda r: True,
        describe=lambda r: Mismatch(
            code="ZR-02", category=OMISSION, severity=ADVISORY, ref=r.ref,
            detail=f"Invoice {r.shown or '(unnumbered)'} is in the listing supplied but not in "
                   f"ZATCA's records.",
            listing_value=_n(r.vat), citation=r.cite),
    ),
    # ---------------------------------------------------------------- matched, but disagreeing
    ReconRule(
        code="ZR-03", scope=PAIR, category=VALUE, severity=BLOCKING,
        note="The same invoice carrying a different VAT amount on each side.",
        when=lambda p: (p.listing.vat is not None and p.zatca.vat is not None
                        and abs(p.zatca.vat - p.listing.vat) > TOLERANCE),
        describe=lambda p: Mismatch(
            code="ZR-03", category=VALUE, severity=BLOCKING, ref=p.ref, field="vat_amount",
            detail=f"Invoice {p.listing.shown} is listed with VAT of SAR {_n(p.listing.vat)}; ZATCA's "
                   f"record shows SAR {_n(p.zatca.vat)}.",
            listing_value=_n(p.listing.vat), zatca_value=_n(p.zatca.vat),
            citation=f"listing {p.listing.cite} · ZATCA {p.zatca.cite}",
            vat_at_stake=_vat_gap(p)),
    ),
    ReconRule(
        code="ZR-04", scope=PAIR, category=VALUE, severity=BLOCKING,
        note="The same invoice carrying a different taxable amount on each side.",
        when=lambda p: (p.listing.net is not None and p.zatca.net is not None
                        and abs(p.zatca.net - p.listing.net) > TOLERANCE),
        describe=lambda p: Mismatch(
            code="ZR-04", category=VALUE, severity=BLOCKING, ref=p.ref, field="taxable_amount",
            detail=f"Invoice {p.listing.shown} is listed with a taxable amount of SAR "
                   f"{_n(p.listing.net)}; ZATCA's record shows SAR {_n(p.zatca.net)}.",
            listing_value=_n(p.listing.net), zatca_value=_n(p.zatca.net),
            citation=f"listing {p.listing.cite} · ZATCA {p.zatca.cite}"),
    ),
    ReconRule(
        code="ZR-05", scope=PAIR, category=TIMING, severity=ADVISORY,
        note="The same invoice dated differently on each side, within one month. A difference "
             "that crosses a month end is ZR-06's, and reporting it twice would make one "
             "disagreement look like two.",
        when=lambda p: (p.listing.date is not None and p.zatca.date is not None
                        and p.listing.date != p.zatca.date
                        and (p.listing.date.year, p.listing.date.month)
                        == (p.zatca.date.year, p.zatca.date.month)),
        describe=lambda p: Mismatch(
            code="ZR-05", category=TIMING, severity=ADVISORY, ref=p.ref, field="invoice_date",
            detail=f"Invoice {p.listing.shown} is listed as {p.listing.date:%d %b %Y}; ZATCA's record "
                   f"is dated {p.zatca.date:%d %b %Y} "
                   f"({abs((p.zatca.date - p.listing.date).days)} days apart).",
            listing_value=p.listing.date.isoformat(), zatca_value=p.zatca.date.isoformat(),
            citation=f"listing {p.listing.cite} · ZATCA {p.zatca.cite}"),
    ),
    ReconRule(
        code="ZR-06", scope=PAIR, category=TIMING, severity=BLOCKING,
        note="A date difference that crosses a month end, so the two sides put the same "
             "invoice in different return periods.",
        when=lambda p: (p.listing.date is not None and p.zatca.date is not None
                        and (p.listing.date.year, p.listing.date.month)
                        != (p.zatca.date.year, p.zatca.date.month)),
        describe=lambda p: Mismatch(
            code="ZR-06", category=TIMING, severity=BLOCKING, ref=p.ref, field="invoice_date",
            detail=f"Invoice {p.listing.shown} falls in {p.listing.date:%B %Y} on the listing and "
                   f"{p.zatca.date:%B %Y} in ZATCA's records — the two sides assign it to "
                   f"different return periods.",
            listing_value=p.listing.date.isoformat(), zatca_value=p.zatca.date.isoformat(),
            citation=f"listing {p.listing.cite} · ZATCA {p.zatca.cite}"),
    ),
    ReconRule(
        code="ZR-07", scope=PAIR, category=PARTY, severity=ADVISORY,
        note="The same invoice recorded against a different counterparty VAT number.",
        when=lambda p: (bool(p.listing.counterparty_vat) and bool(p.zatca.counterparty_vat)
                        and p.listing.counterparty_vat != p.zatca.counterparty_vat),
        describe=lambda p: Mismatch(
            code="ZR-07", category=PARTY, severity=ADVISORY, ref=p.ref,
            field="counterparty_vat_number",
            detail=f"Invoice {p.listing.shown} names VAT number {p.listing.counterparty_vat} on the "
                   f"listing and {p.zatca.counterparty_vat} in ZATCA's records.",
            listing_value=p.listing.counterparty_vat, zatca_value=p.zatca.counterparty_vat,
            citation=f"listing {p.listing.cite} · ZATCA {p.zatca.cite}"),
    ),
    # ---------------------------------------------------------------- within one side
    ReconRule(
        code="ZR-08", scope=GROUP, side=LISTING, category=DUPLICATE, severity=BLOCKING,
        note="The same invoice number appearing more than once in the taxpayer's listing. "
             "Either one supply is counted twice, or two supplies share a number — both are "
             "defects, and which one it is cannot be told from the number alone.",
        when=lambda g: len(g) > 1,
        describe=lambda g: Mismatch(
            code="ZR-08", category=DUPLICATE, severity=BLOCKING, ref=g[0].ref,
            detail=f"Invoice number {g[0].shown} appears {len(g)} times in the listing"
                   + (" with differing VAT amounts"
                      if len({r.vat for r in g}) > 1 else " with the same VAT amount")
                   + ".",
            listing_value=", ".join(_n(r.vat) for r in g[:MAX_CITED]),
            citation="listing " + ", ".join(f"row {r.row}" for r in g[:MAX_CITED]),
            vat_at_stake=(sum(r.vat or 0.0 for r in g[1:])
                          if len({r.vat for r in g}) == 1 else 0.0)),
    ),
    ReconRule(
        code="ZR-09", scope=GROUP, side=ZATCA, category=DUPLICATE, severity=ADVISORY,
        note="The same invoice number more than once in ZATCA's own records — a data "
             "question on our side, reported so it is not mistaken for a taxpayer defect.",
        when=lambda g: len(g) > 1,
        describe=lambda g: Mismatch(
            code="ZR-09", category=DUPLICATE, severity=ADVISORY, ref=g[0].ref,
            detail=f"Invoice number {g[0].shown} appears {len(g)} times in ZATCA's records.",
            zatca_value=", ".join(_n(r.vat) for r in g[:MAX_CITED]),
            citation="ZATCA " + ", ".join(f"row {r.row}" for r in g[:MAX_CITED])),
    ),
    ReconRule(
        code="ZR-10", scope=POPULATION, side=LISTING, category=IDENTIFIER, severity=BLOCKING,
        note="Rows with no invoice number. They cannot be matched in either direction, so "
             "they are reported as unmatchable rather than silently counted as agreeing.",
        when=lambda rows: any(not r.ref for r in rows),
        describe=lambda rows: Mismatch(
            code="ZR-10", category=IDENTIFIER, severity=BLOCKING,
            detail=f"{sum(1 for r in rows if not r.ref)} of {len(rows)} rows in the listing "
                   f"carry no invoice number and cannot be matched against ZATCA's records.",
            citation="listing " + ", ".join(f"row {r.row}" for r in rows
                                            if not r.ref)[:200]),
    ),
    ReconRule(
        code="ZR-11", scope=POPULATION, side=ZATCA, category=IDENTIFIER, severity=ADVISORY,
        note="The same, on ZATCA's side.",
        when=lambda rows: any(not r.ref for r in rows),
        describe=lambda rows: Mismatch(
            code="ZR-11", category=IDENTIFIER, severity=ADVISORY,
            detail=f"{sum(1 for r in rows if not r.ref)} of {len(rows)} rows in ZATCA's "
                   f"records carry no invoice number and cannot be matched.",
            citation="ZATCA " + ", ".join(f"row {r.row}" for r in rows if not r.ref)[:200]),
    ),
    ReconRule(
        code="ZR-12", scope=POPULATION, side=LISTING, category=SEQUENCE, severity=ADVISORY,
        note="A break in the listing's own numbering. Advisory and heavily preconditioned: "
             "invoice numbers are only sequential when the taxpayer's system makes them so, "
             "and a cancelled document is a legitimate gap. It fires only where the "
             "numbering is otherwise contiguous, and it asks rather than concludes.",
        when=lambda rows: _sequence_gaps(rows) != [],
        describe=lambda rows: _sequence_mismatch(_sequence_gaps(rows)),
    ),
)

RULE_BY_CODE = {r.code: r for r in RULES}


# ------------------------------------------------------------------------------ normalising

_REF_CLEAN = re.compile(r"[\s\-_/]+")
_SEQ = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)$")

# The columns each side may use. The taxpayer's listing goes through `extract.normalise`
# already, so these are canonical names; the ZATCA extract is read the same way, which is what
# lets one dataset be dropped in without a bespoke reader.
_REF_COLUMNS = ("invoice_number", "note_number", "reference")
_DATE_COLUMNS = ("invoice_date", "note_date", "posting_date", "date")
_NET_COLUMNS = ("taxable_amount", "amount", "gross_amount")
_VAT_COLUMNS = ("vat_amount",)
_PARTY_COLUMNS = ("customer_name", "supplier_name", "counterparty_name")
_PARTY_VAT_COLUMNS = ("customer_vat_number", "supplier_vat_number", "counterparty_vat")
_STATUS_COLUMNS = ("status", "clearance_status", "invoice_status")


def normalise_ref(v: Any) -> str:
    """'INV-1024 ' and 'inv1024' are the same invoice. Formatting is not a mismatch."""
    return _REF_CLEAN.sub("", str(v or "").strip()).upper()


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v or "").strip().replace(",", "").replace("SAR", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _pick(columns: list[str], names: tuple[str, ...]) -> int:
    for n in names:
        if n in columns:
            return columns.index(n)
    return -1


def records(content: dict, side: str) -> list[InvoiceRecord]:
    """Read one extracted file into comparable records. Never raises on a ragged row."""
    columns = list(content.get("columns") or [])
    rows = content.get("rows") or []
    i_ref = _pick(columns, _REF_COLUMNS)
    i_date = _pick(columns, _DATE_COLUMNS)
    i_net = _pick(columns, _NET_COLUMNS)
    i_vat = _pick(columns, _VAT_COLUMNS)
    i_party = _pick(columns, _PARTY_COLUMNS)
    i_pvat = _pick(columns, _PARTY_VAT_COLUMNS)
    i_status = _pick(columns, _STATUS_COLUMNS)

    def cell(row, i):
        return row[i] if 0 <= i < len(row) else None

    out = []
    for n, row in enumerate(rows, start=1):
        out.append(InvoiceRecord(
            ref=normalise_ref(cell(row, i_ref)), row=n, side=side,
            display=str(cell(row, i_ref) or "").strip(),
            date=_date(cell(row, i_date)),
            counterparty=str(cell(row, i_party) or "").strip(),
            counterparty_vat=str(cell(row, i_pvat) or "").strip(),
            net=_num(cell(row, i_net)), vat=_num(cell(row, i_vat)),
            status=str(cell(row, i_status) or "").strip().lower(),
        ))
    return out


def _sequence_gaps(rows: list[InvoiceRecord]) -> list[str]:
    """Missing values in an otherwise contiguous numbering, or [] when there isn't one.

    Deliberately hard to satisfy. Invoice numbers are contiguous only when the taxpayer's
    system makes them so, and a run of unrelated references would otherwise produce a long,
    confident and meaningless list of "missing" invoices.
    """
    # Parsed from what the taxpayer wrote, not from the normalised key: a missing invoice the
    # auditor cannot find in their own file by searching for it is not a useful thing to report,
    # so the prefix, the separator and the zero padding all have to survive.
    # A row with no reference at all is almost certainly one of the holes, and ZR-10 already
    # reports it. Saying "three numbers are missing from the sequence" beside "three rows carry
    # no number" makes one defect look like two, and sends the taxpayer chasing invoices that
    # are sitting in the file they already sent.
    if any(not r.ref for r in rows):
        return []

    parsed: dict[tuple[str, int], list[int]] = {}
    for r in rows:
        m = _SEQ.match(r.shown)
        if m:
            digits = m.group("num")
            parsed.setdefault((m.group("prefix"), len(digits)), []).append(int(digits))
    if not parsed:
        return []
    (prefix, width), nums = max(parsed.items(), key=lambda kv: len(kv[1]))
    if len(nums) < 5 or len(nums) < 0.8 * len(rows):
        return []                       # not a numbering scheme, just numbers
    span = max(nums) - min(nums) + 1
    if span > 3 * len(nums):
        return []                       # far too sparse to call the holes "gaps"
    have = set(nums)
    return [f"{prefix}{n:0{width}d}"
            for n in range(min(nums), max(nums) + 1) if n not in have]


# ------------------------------------------------------------------------------ the matcher

@dataclass
class Comparison:
    comparable: bool
    note: str = ""
    listing_count: int = 0
    zatca_count: int = 0
    matched_count: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)
    listing_name: str = ""
    zatca_name: str = ""

    def by_category(self, category: str) -> list[Mismatch]:
        return [m for m in self.mismatches if m.category == category]

    def by_code(self, code: str) -> list[Mismatch]:
        return [m for m in self.mismatches if m.code == code]

    def vat_at_stake(self, code: str) -> float:
        return round(sum(m.vat_at_stake for m in self.by_code(code)), 2)

    def to_dict(self) -> dict:
        cats: dict[str, dict] = {}
        for m in self.mismatches:
            c = cats.setdefault(m.category, {"category": m.category, "count": 0,
                                             "blocking": 0, "vat_at_stake": 0.0})
            c["count"] += 1
            c["blocking"] += 1 if m.severity == BLOCKING else 0
            c["vat_at_stake"] = round(c["vat_at_stake"] + m.vat_at_stake, 2)
        return {
            "comparable": self.comparable, "note": self.note,
            "listing_count": self.listing_count, "zatca_count": self.zatca_count,
            "matched_count": self.matched_count,
            "listing_name": self.listing_name, "zatca_name": self.zatca_name,
            "mismatches": [m.to_dict() for m in self.mismatches],
            "categories": sorted(cats.values(), key=lambda c: -c["count"]),
            "blocking": sum(1 for m in self.mismatches if m.severity == BLOCKING),
            "rules": [{"code": r.code, "category": r.category, "severity": r.severity,
                       "note": r.note} for r in RULES],
        }


def _grouped(rows: list[InvoiceRecord]) -> dict[str, list[InvoiceRecord]]:
    out: dict[str, list[InvoiceRecord]] = {}
    for r in rows:
        if r.ref:
            out.setdefault(r.ref, []).append(r)
    return out


def compare(*, listing: dict | None, zatca: dict | None,
            listing_name: str = "", zatca_name: str = "") -> Comparison:
    """Run every rule over the two populations.

    Both sides are required. With only one, every row on it would be "unmatched" — an
    invented finding carrying an invented amount, which is the single worst thing this module
    could produce. It says which side is missing instead.
    """
    # The missing side is named in the order an auditor can act on: with nothing loaded, the
    # dataset is the thing to supply, and telling them the *listing* is missing on a case that
    # has neither sends them to the wrong screen.
    if not (zatca and (zatca.get("rows") or [])):
        return Comparison(comparable=False, listing_name=listing_name, zatca_name=zatca_name,
                          listing_count=len((listing or {}).get("rows") or []),
                          note="No ZATCA invoice dataset has been supplied for this case. A "
                               "comparison needs both sides; with one, every record would "
                               "appear unmatched.")
    if not (listing and (listing.get("rows") or [])):
        return Comparison(comparable=False, zatca_name=zatca_name, listing_name=listing_name,
                          zatca_count=len(zatca.get("rows") or []),
                          note="The taxpayer has supplied no sales listing to compare these "
                               "records against. A comparison needs both sides; with one, "
                               "every record would appear unmatched.")

    left = records(listing, LISTING)
    right = records(zatca, ZATCA)
    lg, rg = _grouped(left), _grouped(right)
    shared = sorted(set(lg) & set(rg))

    # The first of each duplicate group represents it in the pairing; the duplication itself is
    # a finding in its own right (ZR-08/09) rather than something to silently pick between.
    pairs = [Pair(ref=ref, listing=lg[ref][0], zatca=rg[ref][0]) for ref in shared]
    unmatched = {
        LISTING: [r for r in left if r.ref and r.ref not in rg],
        ZATCA: [r for r in right if r.ref and r.ref not in lg],
    }
    groups = {LISTING: list(lg.values()), ZATCA: list(rg.values())}
    population = {LISTING: left, ZATCA: right}

    found: list[Mismatch] = []
    for rule in RULES:
        if rule.scope == PAIR:
            subjects: list = list(pairs)
        elif rule.scope == UNMATCHED:
            subjects = list(unmatched.get(rule.side, []))
        elif rule.scope == GROUP:
            subjects = list(groups.get(rule.side, []))
        elif rule.scope == ROW:
            subjects = list(population.get(rule.side, []))
        elif rule.scope == POPULATION:
            subjects = [population.get(rule.side, [])]
        else:                                   # pragma: no cover - guarded by test_zatca
            raise ValueError(f"unknown rule scope {rule.scope!r}")
        for subject in subjects:
            if not rule.when(subject):
                continue
            produced = rule.describe(subject)
            if produced is None:
                continue
            found.extend(produced if isinstance(produced, list) else [produced])

    return Comparison(
        comparable=True, listing_count=len(left), zatca_count=len(right),
        matched_count=len(pairs), mismatches=found,
        listing_name=listing_name, zatca_name=zatca_name)
