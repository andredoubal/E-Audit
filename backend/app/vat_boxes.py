"""The VAT return's own boxes, and what — if anything — evidences each one.

The return the Authority actually issues carries **fifteen** declarable boxes plus four computed
lines, not the four this PoC first modelled. That matters beyond completeness: a reconciliation
is only as good as the box it compares against, and folding a 5% supply into the 15% box, or an
import under reverse charge into ordinary purchases, compares two things the return itself keeps
apart.

The load-bearing field here is **`evidenced_by`**. Several boxes have no counterpart in anything
the taxpayer or the Authority can hand over:

- **Sales through the Etimad platform** and **sales to citizens** are distinguished by *who the
  customer is and what was supplied*, and a sales register carrying an invoice number, a date, a
  counterparty and three amounts cannot say either.
- **Exempt supplies** are indistinguishable from zero-rated ones on the record side: both carry
  no VAT, and only a treatment column the registers do not have would separate them.
- **Imports under the reverse-charge mechanism** are services. They clear no customs post, so
  there is no declaration to match, and no other file evidences them.

A box like that is **declared-only**, and the dashboard says so. The alternative — comparing it
against whatever records happen to be lying around, or against nothing and calling the result
zero — manufactures a variance the size of the declaration out of a dataset the case does not
have. That is the same rule the pairings already follow: one side is not a comparison.
"""
from __future__ import annotations

from dataclasses import dataclass

SALE = "sale"
PURCHASE = "purchase"
CALC = "calc"

#: How a box's record side is established.
RECORDS = "records"              # the register and the e-invoice extract, at this rate
CUSTOMS_IMPORT = "customs-import"
CUSTOMS_EXPORT = "customs-export"
NOTHING = "nothing"              # declared only — nothing on the case can evidence it
COMPUTED = "computed"            # a total or carry-forward, not a population of documents


@dataclass(frozen=True)
class Box:
    """One line of the return, with the Authority's own wording beside ours."""

    code: str
    label: str
    label_ar: str
    direction: str
    #: The rate the box declares, where it declares one. `None` means the box is not rate-scoped.
    rate: int | None
    #: S / Z / E / O, the ZATCA VAT category. Empty where the box spans more than one.
    category: str
    evidenced_by: str
    #: Why nothing evidences it, when nothing does. Shown on the screen rather than left blank.
    why_unevidenced: str = ""
    #: A computed line rather than a declaration of supplies.
    computed: bool = False

    @property
    def declared_only(self) -> bool:
        return self.evidenced_by == NOTHING

    def to_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "label_ar": self.label_ar,
                "direction": self.direction, "rate": self.rate, "category": self.category,
                "evidenced_by": self.evidenced_by, "why_unevidenced": self.why_unevidenced,
                "declared_only": self.declared_only, "computed": self.computed}


#: The return, in its own order. The first four codes predate this module and keep their names —
#: `standard_rate_sales` has always been the 15% box — so nothing that already reads them breaks.
BOXES: tuple[Box, ...] = (
    # ---------------------------------------------------------------- sales
    Box("standard_rate_sales", "Standard-rated sales (15%)",
        "المبيعات الخاضعة للنسبة الأساسية (15%)", SALE, 15, "S", RECORDS),
    Box("etimad_sales", "Sales through the Etimad platform — government entities (15%)",
        "المبيعات المتعلقة بمنصة اعتماد (جهات حكومية) (15%)", SALE, 15, "S", NOTHING,
        "A supply is in this box because of who the customer is and how it was procured. The "
        "sales register carries an invoice number, a date, a counterparty and three amounts, "
        "and none of those says a supply went through the platform."),
    Box("standard_rate_sales_5", "Standard-rated sales (5%)",
        "المبيعات الخاضعة للنسبة الأساسية (5%)", SALE, 5, "S", RECORDS),
    Box("citizen_sales", "Sales to citizens — private healthcare and private education",
        "المبيعات للمواطنين (الخدمات الصحية الخاصة/التعليم الأهلي الخاص)", SALE, 15, "S",
        NOTHING,
        "This box turns on the customer being a citizen and the supply being private "
        "healthcare or private education. Nothing in the records on file establishes either."),
    Box("zero_rated_sales", "Domestic zero-rated sales",
        "المبيعات المحلية الخاضعة للنسبة الصفرية", SALE, 0, "Z", RECORDS),
    Box("exports", "Exports", "الصادرات", SALE, 0, "Z", CUSTOMS_EXPORT),
    Box("exempt_sales", "Exempt sales", "المبيعات المعفاة", SALE, None, "E", NOTHING,
        "An exempt supply and a zero-rated one look identical in a register: both carry no VAT. "
        "Only a treatment column would separate them, and these registers have none."),

    # ---------------------------------------------------------------- purchases
    Box("standard_rate_purchase", "Standard-rated purchases (15%)",
        "المشتريات الخاضعة للنسبة الأساسية (15%)", PURCHASE, 15, "S", RECORDS),
    Box("standard_rate_purchase_5", "Standard-rated purchases (5%)",
        "المشتريات الخاضعة للنسبة الأساسية (5%)", PURCHASE, 5, "S", RECORDS),
    Box("import_customs_15", "Imports — VAT paid at customs (15%)",
        "الاستيرادات الخاضعة لضريبة القيمة المضافة بالنسبة الأساسية و التي تدفع في الجمارك (15%)",
        PURCHASE, 15, "S", CUSTOMS_IMPORT),
    Box("import_customs_5", "Imports — VAT paid at customs (5%)",
        "الاستيرادات الخاضعة لضريبة القيمة المضافة بالنسبة الأساسية و التي تدفع في الجمارك (5%)",
        PURCHASE, 5, "S", CUSTOMS_IMPORT),
    Box("import_reverse_charge_15", "Imports under the reverse-charge mechanism (15%)",
        "الاستيرادات الخاضعة لضريبة القيمة المضافة التي تُطبق عليها آلية الاحتساب العكسي (15%)",
        PURCHASE, 15, "S", NOTHING,
        "Reverse-charge imports are services. They clear no customs post, so there is no "
        "declaration to match them against, and no other file on the case evidences them."),
    Box("import_reverse_charge_5", "Imports under the reverse-charge mechanism (5%)",
        "الاستيرادات الخاضعة لضريبة القيمة المضافة التي تُطبق عليها آلية الاحتساب العكسي (5%)",
        PURCHASE, 5, "S", NOTHING,
        "Reverse-charge imports are services. They clear no customs post, so there is no "
        "declaration to match them against, and no other file on the case evidences them."),
    Box("zero_rated_purchase", "Zero-rated purchases",
        "المشتريات الخاضعة للنسبة الصفرية", PURCHASE, 0, "Z", RECORDS),
    Box("exempt_purchase", "Exempt purchases", "المشتريات المعفاة", PURCHASE, None, "E", NOTHING,
        "As on the sales side, an exempt purchase and a zero-rated one are indistinguishable "
        "without a treatment column the register does not carry."),

    # ---------------------------------------------------------------- computed lines
    Box("total_vat_due", "Total VAT due for the current period",
        "إجمالي ضريبة القيمة المضافة المستحقة عن الفترة الضريبية الحالية", CALC, None, "",
        COMPUTED, computed=True),
    Box("prior_period_corrections", "Corrections from previous periods (within ±SAR 5,000)",
        "تصحيحات من الفترات السابقة (بين ± 5000.00 ريال)", CALC, None, "", COMPUTED,
        computed=True),
    Box("vat_carried_forward", "VAT carried forward from previous period(s)",
        "ضريبة القيمة المضافة التي تم ترحيلها من الفترة / الفترات السابقة", CALC, None, "",
        COMPUTED, computed=True),
    Box("net_vat_due", "Net VAT due (or refundable)",
        "صافي الضريبة المستحقة (أو المستردة)", CALC, None, "", COMPUTED, computed=True),
)

BY_CODE: dict[str, Box] = {b.code: b for b in BOXES}


def for_direction(direction: str, *, computed: bool = False) -> list[Box]:
    """The boxes on one side of the return, in the return's own order."""
    return [b for b in BOXES if b.direction == direction and b.computed == computed]


def for_workstream(workstream: str) -> list[Box]:
    return for_direction(SALE if workstream == "sales" else PURCHASE)


def records_box(direction: str, treatment: str, rate: float | None) -> Box | None:
    """Which box a record belongs in, from its treatment and the rate it was charged at.

    Only boxes evidenced by the records themselves can be reached this way. A record cannot
    place itself in the Etimad box or the exempt box — the register does not carry what those
    turn on — so nothing is ever routed there by inference, which is the whole point.
    """
    from .canonical.model import STANDARD, ZERO_RATED

    if treatment == STANDARD:
        want = 5 if rate is not None and abs(rate - 5) < 0.01 else 15
    elif treatment == ZERO_RATED:
        want = 0
    else:
        return None
    return next((b for b in BOXES
                 if b.direction == direction and b.evidenced_by == RECORDS and b.rate == want),
                None)
