"""Which column plays which part, decided from the column's own contents.

A reconciliation cannot be planned until the engine knows where the VAT amount is, where the
date is, and whether the counterparty is a customer or a supplier. Header names get you most of
the way — `extract.normalise()` already folds forty-odd spellings onto canonical names — but
they are not enough on their own:

* a taxpayer's export may head a column `Column7`, `Amt3`, or nothing at all;
* the same word means different things in different files (`amount` is net here, gross there);
* and a header that *looks* right can sit above values that are not (a `vat_amount` column of
  dates is a defect worth reporting, not a role to accept).

So a role is assigned from two independent signals and the weaker one is never allowed to
decide alone:

    name   what the header says it is, through the canonical alias table
    shape  what the values actually are — parseable as dates, numerics with two decimals,
           a small set of percentages, high-cardinality references, registration numbers

Agreement gives high confidence. A name with no supporting shape, or a shape with no name,
gives low confidence and says so. **Nothing is assigned silently**: every role carries the
evidence that produced it, and the auditor sees it.

The role vocabulary is deliberately about *accounting meaning* rather than about VAT boxes.
`counterparty_name` is one role whose `side` says customer or supplier; that single distinction
is what tells a sales register from a purchase register on any case, in any file, whatever it
is called.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..agents.calculation import as_date, as_number

# ---------------------------------------------------------------- the vocabulary

REFERENCE = "reference"                 # invoice / document / voucher number
COUNTERPARTY_NAME = "counterparty_name"
COUNTERPARTY_TAX_ID = "counterparty_tax_id"
ISSUE_DATE = "issue_date"
SUPPLY_DATE = "supply_date"
PAYMENT_DATE = "payment_date"
POSTING_DATE = "posting_date"
NET_AMOUNT = "net_amount"
VAT_AMOUNT = "vat_amount"
GROSS_AMOUNT = "gross_amount"
VAT_RATE = "vat_rate"
VAT_TREATMENT = "vat_treatment"         # S / Z / E / O, or the file's own words
DOCUMENT_TYPE = "document_type"         # invoice / credit note / debit note
DEBIT = "debit"
CREDIT = "credit"
ACCOUNT_CODE = "account_code"
ACCOUNT_NAME = "account_name"
BALANCE = "balance"
CUSTOMS_DECLARATION = "customs_declaration"
CURRENCY = "currency"
DESCRIPTION = "description"
QUANTITY = "quantity"
TERMINAL = "terminal"
STATUS = "status"

#: Roles a monetary reconciliation cannot proceed without knowing about.
MONETARY = (NET_AMOUNT, VAT_AMOUNT, GROSS_AMOUNT, DEBIT, CREDIT, BALANCE)
DATES = (ISSUE_DATE, SUPPLY_DATE, PAYMENT_DATE, POSTING_DATE)

CUSTOMER = "customer"
SUPPLIER = "supplier"

# --------------------------------------------------------- name evidence
# Canonical names `extract.normalise()` already produces, mapped to the role they play. Where a
# canonical name also fixes which side of a transaction the file describes, that travels with it.
_BY_CANONICAL: dict[str, tuple[str, str]] = {
    "invoice_number": (REFERENCE, ""),
    "note_number": (REFERENCE, ""),
    "reference": (REFERENCE, ""),
    "customer_name": (COUNTERPARTY_NAME, CUSTOMER),
    "supplier_name": (COUNTERPARTY_NAME, SUPPLIER),
    "customer_vat_number": (COUNTERPARTY_TAX_ID, CUSTOMER),
    "supplier_vat_number": (COUNTERPARTY_TAX_ID, SUPPLIER),
    "invoice_date": (ISSUE_DATE, ""),
    "note_date": (ISSUE_DATE, ""),
    "date": (ISSUE_DATE, ""),
    "acquisition_date": (ISSUE_DATE, ""),
    "delivery_date": (SUPPLY_DATE, ""),
    "supply_date": (SUPPLY_DATE, ""),
    "payment_date": (PAYMENT_DATE, ""),
    "posting_date": (POSTING_DATE, ""),
    "taxable_amount": (NET_AMOUNT, ""),
    "cost": (NET_AMOUNT, ""),
    "vat_amount": (VAT_AMOUNT, ""),
    "vat_claimed": (VAT_AMOUNT, ""),
    "gross_amount": (GROSS_AMOUNT, ""),
    "amount": (GROSS_AMOUNT, ""),
    "vat_rate": (VAT_RATE, ""),
    "note_type": (DOCUMENT_TYPE, ""),
    "debit": (DEBIT, ""),
    "credit": (CREDIT, ""),
    "account_code": (ACCOUNT_CODE, ""),
    "account_name": (ACCOUNT_NAME, ""),
    "description": (DESCRIPTION, ""),
    "quantity": (QUANTITY, ""),
    "terminal_id": (TERMINAL, ""),
    "status": (STATUS, ""),
}

# Fragments matched against a header that the alias table did not recognise. Ordered: the first
# match wins, so the more specific patterns come first.
_BY_FRAGMENT: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (COUNTERPARTY_TAX_ID, ("customer_vat", "customer_trn", "buyer_tin", "customer_tin",
                           "customer_tax", "buyer_tax", "customer_tax_id"), CUSTOMER),
    (COUNTERPARTY_TAX_ID, ("supplier_vat", "vendor_vat", "supplier_tin", "seller_tin",
                           "supplier_tax", "vendor_tax", "seller_tax"), SUPPLIER),
    (COUNTERPARTY_TAX_ID, ("vat_registration", "tax_identification", "tax_id", "tax_no",
                           "tax_number", "trn", "tin"), ""),
    (COUNTERPARTY_NAME, ("customer", "buyer", "client", "debtor"), CUSTOMER),
    (COUNTERPARTY_NAME, ("supplier", "vendor", "seller", "creditor", "payee"), SUPPLIER),
    (CUSTOMS_DECLARATION, ("customs", "declaration", "bayan", "sad_number", "import_decl"), ""),
    (VAT_TREATMENT, ("vat_treatment", "tax_treatment", "supply_type", "category", "vat_code",
                     "tax_code", "rate_type"), ""),
    (DOCUMENT_TYPE, ("document_type", "doc_type", "transaction_type", "entry_type"), ""),
    (VAT_RATE, ("rate", "percent", "pct"), ""),
    # These two sit *above* the VAT rule and the plain net/gross rules, and they have to.
    # The table is first-match-wins, and "amount_excl_vat" and "total_incl_vat" both contain
    # "vat": on a real taxpayer register that read the taxable base and the gross as VAT, and
    # the engine then totalled all three amount columns together. On a two-line fixture it
    # reported SAR 345,000 of output VAT against a truth of 45,000, with no taxable base at
    # all — an eightfold overstatement that nothing downstream could have detected, because by
    # then the reading had already been made. The specific compound cues are matched before the
    # greedy ones; "total_vat" still reaches VAT_AMOUNT, because it carries neither
    # "excl"/"incl" nor a bare "net"/"gross".
    (NET_AMOUNT, ("excl_vat", "excluding_vat", "exclusive_of_vat", "before_vat", "net_of_vat",
                  "amount_excl", "ex_vat"), ""),
    (GROSS_AMOUNT, ("incl_vat", "including_vat", "inclusive_of_vat", "amount_incl",
                    "with_vat"), ""),
    (VAT_AMOUNT, ("vat", "tax_amount", "output_tax", "input_tax"), ""),
    (NET_AMOUNT, ("net", "taxable"), ""),
    (GROSS_AMOUNT, ("gross", "total"), ""),
    (BALANCE, ("balance", "running_total", "closing"), ""),
    (CURRENCY, ("currency", "ccy"), ""),
    (SUPPLY_DATE, ("delivery", "supply"), ""),
    (PAYMENT_DATE, ("payment", "paid", "settlement", "value_date"), ""),
    (POSTING_DATE, ("posting", "posted", "gl_date", "journal_date"), ""),
    (ISSUE_DATE, ("date",), ""),
    (REFERENCE, ("invoice", "voucher", "document_no", "ref", "uuid", "number"), ""),
    (DESCRIPTION, ("description", "narration", "particulars", "details", "memo"), ""),
    (TERMINAL, ("terminal", "till", "register_id", "device"), ""),
    (STATUS, ("status", "state", "clearance"), ""),
)


# --------------------------------------------------------- shape evidence
@dataclass
class Shape:
    """What a column's values actually are, independent of what it is called."""

    filled: int = 0
    total: int = 0
    dates: int = 0
    numerics: int = 0
    negatives: int = 0
    two_dp: int = 0
    distinct: int = 0
    pct_range: int = 0          # numeric and within 0..100
    long_digits: int = 0        # 9+ digit strings — registration numbers, declarations
    texty: int = 0

    @property
    def fill_rate(self) -> float:
        return self.filled / self.total if self.total else 0.0

    def rate(self, n: int) -> float:
        return n / self.filled if self.filled else 0.0

    @property
    def uniqueness(self) -> float:
        return self.distinct / self.filled if self.filled else 0.0

    def looks_like(self) -> str:
        """One word for what this column holds. `unknown` is a real answer."""
        if not self.filled:
            return "empty"
        if self.rate(self.dates) >= 0.8:
            return "date"
        if self.rate(self.long_digits) >= 0.8:
            return "identifier"
        if self.rate(self.numerics) >= 0.8:
            if self.rate(self.pct_range) >= 0.9 and self.distinct <= 8:
                return "rate"
            return "amount"
        if self.uniqueness >= 0.85:
            return "reference"
        return "text"


def measure(values: list[Any]) -> Shape:
    """Read one column's values. No value is altered — this only looks."""
    s = Shape(total=len(values))
    seen: Counter = Counter()
    for v in values:
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        s.filled += 1
        seen[str(v).strip()] += 1
        text = str(v).strip()
        n = as_number(v)
        if n is not None:
            s.numerics += 1
            if n < 0:
                s.negatives += 1
            if 0 <= n <= 100:
                s.pct_range += 1
            if re.search(r"\.\d{2}$", text):
                s.two_dp += 1
            # A long run of digits is an identifier, not a quantity, however it parses.
            if re.fullmatch(r"\d{9,}", text.replace(" ", "")):
                s.long_digits += 1
        elif as_date(v) is not None:
            s.dates += 1
        else:
            s.texty += 1
        # A date that also parses as a number (an Excel serial) is still a date.
        if n is None and as_date(v) is not None:
            pass
    s.distinct = len(seen)
    return s


# --------------------------------------------------------- the assignment
@dataclass
class Role:
    role: str
    column: str
    side: str = ""                  # customer | supplier | "" — only for counterparty roles
    confidence: str = "low"         # high | medium | low
    why: str = ""
    shape: str = ""

    def to_dict(self) -> dict:
        return {"role": self.role, "column": self.column, "side": self.side,
                "confidence": self.confidence, "why": self.why, "shape": self.shape}


#: Which shapes corroborate which roles. A role whose shape disagrees is downgraded, never
#: dropped — the header is evidence too, and a mismatch is worth showing the auditor.
_EXPECTED_SHAPE: dict[str, tuple[str, ...]] = {
    REFERENCE: ("reference", "identifier", "text"),
    COUNTERPARTY_NAME: ("text", "reference"),
    COUNTERPARTY_TAX_ID: ("identifier", "reference", "amount"),
    ISSUE_DATE: ("date",), SUPPLY_DATE: ("date",),
    PAYMENT_DATE: ("date",), POSTING_DATE: ("date",),
    NET_AMOUNT: ("amount",), VAT_AMOUNT: ("amount",), GROSS_AMOUNT: ("amount",),
    DEBIT: ("amount",), CREDIT: ("amount",), BALANCE: ("amount",),
    VAT_RATE: ("rate", "amount"),
    VAT_TREATMENT: ("text", "reference"),
    DOCUMENT_TYPE: ("text", "reference"),
    ACCOUNT_CODE: ("reference", "identifier", "amount", "text"),
    ACCOUNT_NAME: ("text",),
    CUSTOMS_DECLARATION: ("reference", "identifier", "text"),
    CURRENCY: ("text",),
    DESCRIPTION: ("text",),
    QUANTITY: ("amount",),
    TERMINAL: ("reference", "text", "identifier"),
    STATUS: ("text",),
}


def _from_name(column: str) -> tuple[str, str, str]:
    """(role, side, why) for a column name, or ("", "", "") if the name says nothing."""
    canon = (column or "").strip().lower()
    if canon in _BY_CANONICAL:
        role, side = _BY_CANONICAL[canon]
        return role, side, f"the column is named '{column}'"
    for role, fragments, side in _BY_FRAGMENT:
        for f in fragments:
            if f in canon:
                return role, side, f"the column name contains '{f}'"
    return "", "", ""


#: Below this many rows, "every value is distinct" says nothing — a three-row file has three
#: distinct customer names, three distinct descriptions and three distinct anything else. Shape
#: inference that rests on uniqueness needs enough rows for uniqueness to mean something.
_MIN_ROWS_FOR_UNIQUENESS = 6


def _from_shape(shape: Shape) -> tuple[str, str]:
    """A role inferable from values alone, for a header that says nothing."""
    kind = shape.looks_like()
    if kind == "date":
        return ISSUE_DATE, "the values are dates and no header explained them"
    if kind == "identifier":
        return COUNTERPARTY_TAX_ID, "the values are long digit strings, which read as an identifier"
    if kind == "reference" and shape.filled >= _MIN_ROWS_FOR_UNIQUENESS:
        return REFERENCE, "the values are near-unique across enough rows to read as a reference"
    return "", ""


def detect(columns: list[str], rows: list[list[Any]]) -> list[Role]:
    """Assign a role to every column it can, with the evidence that produced it.

    A column may be given no role at all. That is a result, not a failure: an unrecognised
    column is reported so the auditor can see what the engine is not using, which is a great
    deal more useful than a wrong guess acted on silently.
    """
    out: list[Role] = []
    for i, col in enumerate(columns):
        values = [r[i] if i < len(r) else None for r in rows]
        shape = measure(values)
        kind = shape.looks_like()

        role, side, why = _from_name(col)
        if role:
            expected = _EXPECTED_SHAPE.get(role, ())
            if not shape.filled:
                confidence, note = "low", f"{why}, but every value is blank"
            elif kind in expected:
                confidence, note = "high", f"{why}, and the values are {kind}s"
            else:
                confidence, note = "low", (f"{why}, but the values are {kind}s rather than "
                                           f"{' or '.join(expected) or 'the expected shape'}")
            out.append(Role(role=role, column=col, side=side, confidence=confidence,
                            why=note, shape=kind))
            continue

        inferred, note = _from_shape(shape)
        if inferred:
            out.append(Role(role=inferred, column=col, confidence="low",
                            why=note, shape=kind))
    return out


def best(roles: list[Role], role: str) -> Role | None:
    """The strongest column for a role. Ties keep the first, which is the leftmost column."""
    order = {"high": 0, "medium": 1, "low": 2}
    ranked = sorted((r for r in roles if r.role == role), key=lambda r: order[r.confidence])
    return ranked[0] if ranked else None


def column_for(roles: list[Role], role: str) -> str:
    r = best(roles, role)
    return r.column if r else ""


def side_of(roles: list[Role]) -> tuple[str, str]:
    """Whose transactions these are — ('customer'|'supplier'|'', why).

    The single most load-bearing question a profile answers, because it is what separates a
    sales register from a purchase register without reference to the filename. A file naming
    both sides is left undecided rather than resolved by precedence: that is a genuinely
    ambiguous file and saying so is the honest answer.
    """
    sides = {r.side for r in roles if r.side}
    if sides == {CUSTOMER}:
        cols = [r.column for r in roles if r.side == CUSTOMER]
        return CUSTOMER, f"the file identifies counterparties as customers ({', '.join(cols)})"
    if sides == {SUPPLIER}:
        cols = [r.column for r in roles if r.side == SUPPLIER]
        return SUPPLIER, f"the file identifies counterparties as suppliers ({', '.join(cols)})"
    if len(sides) > 1:
        return "", "the file names both customers and suppliers, so the side is ambiguous"
    return "", "no column identifies the counterparty as a customer or a supplier"
