"""The sales listing against what was actually posted to the accounts.

This is the comparison the auditor's own request letter asks for — *"a reconciliation of the
sales reported in the VAT returns to the general ledger"* — and until the trial balance could be
read it was defined and never runnable.

**A trial balance is not a population, and its total means nothing.** Summing every account on
it adds cash to receivables to sales to cost of sales, and produces a figure belonging to no
question anyone asked. So the comparison has to select: the revenue accounts, and the movement
posted to them in the period. That selection is the whole of the judgement here, which is why it
is made on stated evidence — the account's own code and its own name — and published with the
result, so an auditor can see which accounts were taken and reject the reading if it is wrong.

**Revenue is credited.** A sale increases revenue, and in double entry that is a credit, so the
period's sales are the credit movement on those accounts net of any debit posted back to them.
Reading the closing balance instead would carry the opening position in with it and report the
year to date rather than the period.

**Nothing is inferred when nothing identifies an account.** A chart of accounts that names
neither in a way this can read produces "could not be compared" and names what is missing,
rather than a number computed from whichever rows happened to look plausible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..evidence import roles as R
from . import status as S
from . import tolerance as T

#: Account names that identify revenue, in both languages the templates use.
_REVENUE_WORDS = ("مبيعات", "إيرادات", "ايرادات", "sales", "revenue", "turnover", "income")

#: Words that put an account on the other side of the profit and loss, checked *before* the
#: revenue words and overriding them.
#:
#: "تكلفة المبيعات" — cost of sales — contains "مبيعات", so a plain revenue-word match claimed
#: it and netted an expense against the revenue it sits beside: the demo trial balance reported
#: SAR 6,360,000 of sales where the accounts posted 17,600,000. An expense account named after
#: the revenue it relates to is the ordinary case in any chart of accounts, not an edge one.
_EXPENSE_WORDS = ("تكلفة", "مصروف", "مصاريف", "مشتريات", "cost", "expense", "purchase")

#: The revenue range in a conventional chart of accounts. A weaker signal than the name — plenty
#: of charts do not follow it — so it only ever *adds* an account the name already missed, and
#: never overrides a name that says something else.
_REVENUE_PREFIX = "4"


@dataclass
class Account:
    code: str
    name: str
    debit: float
    credit: float
    why: str

    @property
    def movement(self) -> float:
        """What was posted to the account in the period, in the direction revenue runs."""
        return round(self.credit - self.debit, 2)

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "debit": self.debit,
                "credit": self.credit, "movement": self.movement, "why": self.why}


@dataclass
class LedgerComparison:
    """What the accounts say the period's sales were, against the other two sources."""

    runnable: bool = False
    blocked_by: list[str] = field(default_factory=list)
    source_file: str = ""
    accounts: list[Account] = field(default_factory=list)
    ledger_revenue: float | None = None
    register_net: float | None = None
    register_file: str = ""
    declared_base: float | None = None
    vs_register: float | None = None
    vs_declared: float | None = None
    status: str = S.INSUFFICIENT
    observation: str = ""

    def to_dict(self) -> dict:
        return {
            "runnable": self.runnable, "blocked_by": self.blocked_by,
            "source_file": self.source_file, "register_file": self.register_file,
            "accounts": [a.to_dict() for a in self.accounts],
            "ledger_revenue": self.ledger_revenue,
            "register_net": self.register_net, "declared_base": self.declared_base,
            "vs_register": self.vs_register, "vs_declared": self.vs_declared,
            "status": self.status, "status_label": S.LABEL[self.status],
            "attention": S.ATTENTION[self.status],
            "observation": self.observation,
        }


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _revenue_accounts(profile: dict, rows: list[list[Any]]) -> tuple[list[Account], list[str]]:
    """The revenue accounts, and what could not be read if there are none."""
    columns = profile.get("columns") or []
    idx = {c: i for i, c in enumerate(columns)}
    detected = [R.Role(role=r["role"], column=r["column"], side=r.get("side", ""),
                       confidence=r.get("confidence", "low"), why=r.get("why", ""))
                for r in profile.get("roles") or []]

    def col(role_name: str) -> int | None:
        r = R.best(detected, role_name)
        return idx.get(r.column) if r and r.column in idx else None

    i_code, i_name = col(R.ACCOUNT_CODE), col(R.DESCRIPTION)
    i_debit, i_credit = col(R.DEBIT), col(R.CREDIT)

    missing = []
    if i_code is None and i_name is None:
        missing.append("the file carries neither an account code nor an account name, so no "
                       "account can be identified as revenue")
    if i_credit is None:
        missing.append("the file carries no credit column, and revenue is credited")
    if missing:
        return [], missing

    out: list[Account] = []
    for row in rows:
        code = str(row[i_code]).strip() if i_code is not None and i_code < len(row) else ""
        name = str(row[i_name]).strip() if i_name is not None and i_name < len(row) else ""
        lowered = name.lower()
        expense = next((w for w in _EXPENSE_WORDS if w in lowered), "")
        if expense:
            continue
        by_name = next((w for w in _REVENUE_WORDS if w in lowered), "")
        by_code = bool(code) and code.startswith(_REVENUE_PREFIX)
        if not by_name and not by_code:
            continue
        why = (f"the account is named {name!r}" if by_name
               else f"the account code {code} is in the revenue range")
        out.append(Account(
            code=code, name=name,
            debit=_num(row[i_debit]) if i_debit is not None and i_debit < len(row) else 0.0,
            credit=_num(row[i_credit]) if i_credit is not None and i_credit < len(row) else 0.0,
            why=why))

    if not out:
        missing.append("no account on the trial balance could be identified as revenue, by "
                       "either its name or its code")
    return out, missing


def compare(profile: dict | None, rows: list[list[Any]],
            *, register_net: float | None, register_file: str,
            declared_base: float | None,
            tol: T.Tolerance | None = None) -> LedgerComparison:
    """The revenue posted to the accounts, against the listing and against the return."""
    c = LedgerComparison()
    tol = tol or T.DECLARED

    if profile is None:
        c.blocked_by.append("no trial balance or general ledger has been filed on the case")
        c.observation = ("The sales listing could not be compared to the accounts: "
                         + c.blocked_by[0] + ".")
        S.assert_neutral(c.observation, where="ledger")
        return c

    c.source_file = profile.get("filename", "")
    c.accounts, missing = _revenue_accounts(profile, rows)
    if missing:
        c.blocked_by = missing
        c.observation = (f"{c.source_file} could not be compared to the sales listing: "
                         + "; ".join(missing) + ".")
        S.assert_neutral(c.observation, where="ledger")
        return c

    c.runnable = True
    c.ledger_revenue = round(sum(a.movement for a in c.accounts), 2)
    c.register_net, c.register_file = register_net, register_file
    c.declared_base = declared_base
    if register_net is not None:
        c.vs_register = round(c.ledger_revenue - register_net, 2)
    if declared_base is not None:
        c.vs_declared = round(c.ledger_revenue - declared_base, 2)

    # Judged on the widest of the comparisons that could be made: agreeing with the listing
    # while disagreeing with the return is still a difference an auditor has to account for.
    diffs = [d for d in (c.vs_register, c.vs_declared) if d is not None]
    if not diffs:
        c.status = S.INSUFFICIENT
    else:
        larger = max(abs(v) for v in
                     (c.ledger_revenue, register_net or 0.0, declared_base or 0.0))
        widest = max(diffs, key=abs)
        c.status = (S.RECONCILED if tol.within(widest, larger=larger, rows=len(c.accounts))
                    else S.VARIANCE)

    names = ", ".join(f"{a.code} {a.name}".strip() for a in c.accounts)
    parts = [f"{len(c.accounts)} revenue account(s) ({names}) carry SAR "
             f"{abs(c.ledger_revenue):,.2f} of movement for the period"]
    if c.vs_register is not None:
        parts.append(f"the sales listing totals SAR {abs(register_net or 0):,.2f}, a difference "
                     f"of SAR {abs(c.vs_register):,.2f}")
    if c.vs_declared is not None:
        parts.append(f"the return declares SAR {abs(declared_base or 0):,.2f}, a difference of "
                     f"SAR {abs(c.vs_declared):,.2f}")
    c.observation = "; ".join(parts) + "."
    S.assert_neutral(c.observation, where="ledger")
    return c
