"""Build the taxpayer's (deficient) response as a real spreadsheet.

The auditors' example was a sales analysis with eight named columns, answered with something
that omits columns, leaves mandatory fields blank and covers the wrong period. Seeding a
hand-written dict of "extracted" content would demonstrate the checker against its own
assumptions; generating an actual .xlsx and running the real extractor over it demonstrates the
path a real response takes.

The file is deliberately imperfect in five different ways at once, because that is what arrives:

* two requested columns are simply absent (customer VAT number, description);
* the columns that are present use the taxpayer's own names ("Invoice No.", "Net Amount"),
  which are correct information under a spelling the request did not use;
* the invoice number is blank on three rows;
* the rows stop a month short of the period requested;
* the total row states a figure one row larger than the rows beneath it.

Only the first, third, fourth and fifth are gaps. The second must NOT be — reporting a column
missing because the taxpayer called it something reasonable would destroy trust faster than
missing it entirely.
"""
from __future__ import annotations

import io
from datetime import date, timedelta

SALES_HEADERS = ("Invoice Date", "Invoice No.", "Customer", "Net Amount", "Rate", "VAT")

ROW_VAT = 119_000.0
ROW_BASE = 793_333.33
N_ROWS = 22
BLANK_INVOICE_ROWS = (7, 13, 18)          # 1-based, as the checker cites them
OVERSTATED_BY = ROW_VAT                   # the total claims one row that is not listed

CUSTOMERS = (
    "Gulf Retail Partners", "Coastal Distribution Est.", "Northern Supply Co.",
    "Central Markets LLC", "Peninsula Wholesale", "Eastern Trading House",
)


def sales_analysis_rows() -> list[list]:
    """22 rows spanning 6 January to 27 February — a month short of a Q1 request."""
    start = date(2025, 1, 6)
    rows: list[list] = []
    for i in range(1, N_ROWS + 1):
        d = start + timedelta(days=(i - 1) * 2 + (i // 6))
        number = "" if i in BLANK_INVOICE_ROWS else f"INV-2025-{1000 + i}"
        rows.append([d.isoformat(), number, CUSTOMERS[i % len(CUSTOMERS)],
                     ROW_BASE, "15%", ROW_VAT])
    return rows


def stated_total() -> float:
    return round(N_ROWS * ROW_VAT + OVERSTATED_BY, 2)


def sales_analysis_xlsx() -> bytes:
    """The response as the taxpayer would actually send it."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Sales Analysis — Q1 2025"])          # a title row above the header, as they do
    ws.append([])
    ws.append(list(SALES_HEADERS))
    for row in sales_analysis_rows():
        ws.append(row)
    ws.append(["Total", "", "", "", "", stated_total()])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------- ZATCA's own invoice records

# What the Authority holds for the same taxpayer and period. Built from the same rows the
# listing is built from, so the two genuinely agree where they should — a demo dataset that
# disagreed everywhere would prove nothing about the matcher except that it can count.
#
# Three deliberate differences, each one a case the auditors described:
#
#   * three March invoices ZATCA cleared that the listing never reaches. The listing stops in
#     February, which the completeness check already reports as a coverage gap — this is the
#     evidence of what is in the gap, which is the whole point of holding both sides.
#   * one invoice recorded with a different VAT amount on each side.
#   * the rows the taxpayer left unnumbered simply cannot be matched, and are reported as such
#     rather than being quietly counted as agreeing.
ZATCA_HEADERS = ("Invoice Date", "Invoice Number", "Customer Name", "Customer VAT Number",
                 "Taxable Amount", "VAT Amount", "Status")

VALUE_MISMATCH_ROW = 5              # 1-based, as it appears in the listing
VALUE_MISMATCH_VAT = 131_000.0      # SAR 12,000 above what the taxpayer listed
UNLISTED_INVOICES = 3               # cleared in March, after the listing stops
CUSTOMER_VAT = "3000000000000{:02d}"


def zatca_invoice_rows() -> list[list]:
    """The taxpayer's own invoices as ZATCA holds them, plus the ones they did not list."""
    listed = sales_analysis_rows()
    rows: list[list] = []
    for i, row in enumerate(listed, start=1):
        invoice_date, number, customer, base, _rate, vat = row
        if not number:
            continue                  # nothing to match on; the listing's defect, not ours
        rows.append([invoice_date, number, customer,
                     CUSTOMER_VAT.format(i % 90 + 3), base,
                     VALUE_MISMATCH_VAT if i == VALUE_MISMATCH_ROW else vat, "cleared"])

    last = date.fromisoformat(listed[-1][0])
    for n in range(1, UNLISTED_INVOICES + 1):
        rows.append([(last + timedelta(days=n * 9)).isoformat(),
                     f"INV-2025-{1000 + N_ROWS + n}",
                     CUSTOMERS[n % len(CUSTOMERS)], CUSTOMER_VAT.format(n + 40),
                     ROW_BASE, ROW_VAT, "cleared"])
    return rows


def zatca_invoices_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"
    ws.append(list(ZATCA_HEADERS))
    for row in zatca_invoice_rows():
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------- customs declarations
#: The Authority's own import and export declaration extracts, in the columns its templates
#: carry. Arabic headers, because that is what an auditor is handed — and because reading them
#: is the point: a declaration file the profiler cannot classify evidences nothing.
IMPORT_HEADERS = ("اسم المستورد/المصدّر", "الرقم المبدئي للبيان", "رقم البيان", "دولة المقصد",
                  "وصف الصنف في الفاتورة", "الوزن القائم بالكيلو", "الوزن الصافي بالكيلو",
                  "القيمة بالريال")
EXPORT_HEADERS = ("اسم المستورد/المصدّر", "الرقم المبدئي للبيان", "رقم البيان", "التاريخ-هجري",
                  "تاريخ البيان - ميلادي", "وصف الصنف في الفاتورة", "كمية الفاتورة",
                  "عملة الفاتورة", "الوزن القائم بالكيلو", "الوزن الصافي بالكيلو",
                  "القيمة بالريال")

#: Imports total SAR 2,240,000 against SAR 2,000,000 declared — the shape of an import the
#: return does not carry. Customs states a value and no tax, so this can only ever be compared
#: against the box's base.
_IMPORT_VALUES = (620_000, 480_000, 355_000, 290_000, 245_000, 250_000)
#: Exports total SAR 1,380,000 against SAR 1,500,000 declared: the taxpayer claimed more
#: zero-rated export than the declarations evidence, which runs the other way.
_EXPORT_VALUES = (430_000, 360_000, 295_000, 180_000, 115_000)


def customs_imports_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Import"
    ws.append(list(IMPORT_HEADERS))
    for n, value in enumerate(_IMPORT_VALUES, 1):
        ws.append(["Al-Faisaliah Trading Co.", f"{9000 + n}", f"IMP-2025-{100 + n}",
                   "SA", "Trading stock", 12_400 + n * 90, 11_800 + n * 85, value])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def customs_exports_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(list(EXPORT_HEADERS))
    for n, value in enumerate(_EXPORT_VALUES, 1):
        ws.append(["Al-Faisaliah Trading Co.", f"{7000 + n}", f"EXP-2025-{200 + n}",
                   f"1446-0{n}-15", f"2025-0{min(n, 3)}-{10 + n}", "Trading stock",
                   240 + n * 15, "SAR", 9_100 + n * 70, 8_650 + n * 66, value])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- trial balance
#: Two header rows with merged group cells, exactly as the Authority's template writes them —
#: a group label spanning a pair of columns and the pair's own labels beneath it. Written this
#: way on purpose: read as a single header row, every `دائن` column is dropped and the credit
#: side of every account silently goes missing.
_TB_GROUPS = ("الرصيد الافتتاحي", "الحركة", "الرصيد النهائي")
_TB_ACCOUNTS = (
    ("1010", "النقد وما في حكمه", 1_450_000, 0, 3_200_000, 2_980_000, 1_670_000, 0),
    ("1210", "الذمم المدينة", 2_100_000, 0, 6_400_000, 5_900_000, 2_600_000, 0),
    ("2110", "الذمم الدائنة", 0, 890_000, 1_240_000, 1_610_000, 0, 1_260_000),
    ("2140", "ضريبة القيمة المضافة المستحقة", 0, 310_000, 1_850_000, 2_640_000, 0, 1_100_000),
    # The sales account: SAR 17,600,000 credited against a register totalling 17,453,333.26.
    ("4010", "المبيعات", 0, 0, 0, 17_600_000, 0, 17_600_000),
    ("5010", "تكلفة المبيعات", 0, 0, 11_240_000, 0, 11_240_000, 0),
)


def trial_balance_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "TB"

    ws.append(["ميزان المراجعة"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)

    ws.cell(row=2, column=1, value="الرقم")
    ws.cell(row=2, column=2, value="الاسم")
    for n, group in enumerate(_TB_GROUPS):
        col = 3 + n * 2
        ws.cell(row=2, column=col, value=group)
        ws.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 1)
        ws.cell(row=3, column=col, value="مدين")
        ws.cell(row=3, column=col + 1, value="دائن")
    for col in (1, 2):
        ws.merge_cells(start_row=2, start_column=col, end_row=3, end_column=col)

    for account in _TB_ACCOUNTS:
        ws.append(list(account))
    for col in range(1, 9):
        ws.column_dimensions[get_column_letter(col)].width = 22

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
