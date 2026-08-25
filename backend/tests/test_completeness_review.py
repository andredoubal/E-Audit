"""The completeness review beyond "a file exists".

Four capabilities, each of which exists because of a specific way the previous check was wrong:

- **Every worksheet is read**, not just the first. A cover sheet in front of the data used to
  make a supplied file look unsupplied.
- **A present-but-empty column is said out loud.** "The supplier VAT number is there" is true and
  useless when it is populated on four rows out of ninety.
- **The gaps are presented in four words an auditor uses** — Received / Missing / Incomplete /
  Needs auditor review — and the last two are kept apart, because one is the taxpayer's defect
  and the other is the checker admitting it cannot decide.
- **A reply that claims an attachment with no file behind it** is a silent failure that otherwise
  reads, in the trail, exactly like an answered request.

No database and no model: the checker is still a pure function over items and documents.
"""
from datetime import date
from types import SimpleNamespace

import io

from app.requests.completeness import (
    ADVISORY, INCOMPLETE, MISSING, NEEDS_REVIEW, RECEIVED, assessment, check,
)
from app.requests.extract import extract, normalise
from app.requests.catalog import ITEM_BY_KEY, SALES_COLUMNS

PERIOD_FROM, PERIOD_TO = date(2025, 1, 1), date(2025, 3, 31)


def item(key="sales-analysis", *, id=1, status="outstanding", **over):
    c = ITEM_BY_KEY[key]
    fields = {
        "id": id, "label": c.label, "kind": c.kind, "status": status,
        "required_columns": list(c.required_columns),
        "mandatory_columns": list(c.mandatory_columns),
        "expected_format": c.expected_format, "footed_by": list(c.footed_by),
        "period_from": PERIOD_FROM, "period_to": PERIOD_TO,
    }
    fields.update(over)
    return SimpleNamespace(**fields)


def doc(*, id=1, item_id=1, columns=None, rows=None, sheets=None, filename="response.xlsx"):
    cols = [normalise(c) for c in (columns if columns is not None else SALES_COLUMNS)]
    return SimpleNamespace(
        id=id, request_item_id=item_id, filename=filename, file_format="xlsx",
        received_at=PERIOD_TO,
        content={"format": "xlsx", "columns": cols, "rows": rows or [], "stated_totals": {},
                 "raw_headers": list(columns or SALES_COLUMNS), "sheets": sheets or [],
                 "period_from": "2025-01-05", "period_to": "2025-03-28", "note": ""},
    )


def run(items, docs):
    return check(case_id="CASE-TEST", round_=1, items=items, documents=docs,
                 period_from=PERIOD_FROM, period_to=PERIOD_TO)


def kinds(report):
    return sorted(g.kind for g in report.gaps)


def workbook(sheets: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, grid in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in grid:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SALES_GRID = [list(SALES_COLUMNS)] + [
    ["2025-01-10", "INV-1", "Buyer", "300000000000003", "Goods", 1000.0, "15%", 150.0],
    ["2025-02-11", "INV-2", "Buyer", "300000000000003", "Goods", 2000.0, "15%", 300.0],
]


# --------------------------------------------------------------- every sheet is read
def test_the_data_sheet_is_found_even_when_it_is_not_the_first():
    data = workbook({"Cover": [["Prepared by", "Finance"], ["Date", "2025-04-02"]],
                     "Sales Detail": SALES_GRID})
    out = extract("response.xlsx", data)

    assert out["sheet"] == "Sales Detail", \
        "reading only the first sheet would report a supplied file as unsupplied"
    assert "invoice_number" in out["columns"]
    assert out["row_count"] == 2


def test_every_worksheet_is_recorded_even_the_ones_not_analysed():
    data = workbook({"Cover": [["Prepared by", "Finance"]], "Sales Detail": SALES_GRID})
    out = extract("response.xlsx", data)

    names = {s["name"] for s in out["sheets"]}
    assert names == {"Cover", "Sales Detail"}
    assert [s["name"] for s in out["sheets"] if s["primary"]] == ["Sales Detail"]


def test_a_single_sheet_workbook_is_unchanged_by_any_of_this():
    out = extract("response.xlsx", workbook({"Sheet1": SALES_GRID}))
    assert out["columns"][:2] == ["invoice_date", "invoice_number"]
    assert out["row_count"] == 2
    assert out["sheet"] == "Sheet1"


def test_columns_on_another_tab_are_named_rather_than_simply_reported_missing():
    """The most annoying way to be wrong: chasing a file the taxpayer already sent."""
    sheets = [{"name": "Summary", "columns": ["item", "amount"], "row_count": 3,
               "primary": True},
              {"name": "Detail", "columns": list(SALES_COLUMNS), "row_count": 90,
               "primary": False}]
    r = run([item()], [doc(columns=["item", "amount"], sheets=sheets)])

    other = [g for g in r.gaps if g.kind == "other-worksheet"]
    assert other, "the checker should say where the columns actually are"
    assert "Detail" in other[0].detail
    assert other[0].severity == ADVISORY, \
        "the analysis still cannot read them — but this is a hint, not a second accusation"


def test_nothing_is_said_about_other_worksheets_when_the_right_one_was_read():
    sheets = [{"name": "Detail", "columns": list(SALES_COLUMNS), "row_count": 2,
               "primary": True},
              {"name": "Cover", "columns": ["prepared_by"], "row_count": 1, "primary": False}]
    assert "other-worksheet" not in kinds(run([item()], [doc(sheets=sheets)]))


# --------------------------------------------------------------- present but empty
def _rows_with_sparse_customer_vat(n=20, filled=2):
    rows = []
    for i in range(n):
        rows.append(["2025-01-10", f"INV-{i}", "Buyer",
                     "300000000000003" if i < filled else "",
                     "Goods", 1000.0, "15%", 150.0])
    return rows


def test_a_column_that_is_there_but_mostly_empty_is_advisory():
    r = run([item()], [doc(rows=_rows_with_sparse_customer_vat())])
    sparse = [g for g in r.gaps if g.kind == "sparse-column"]

    assert sparse, "a column populated on 2 rows of 20 is present without being usable"
    assert "Customer VAT number" in sparse[0].detail
    assert sparse[0].severity == ADVISORY, "nobody asked for every row to be populated"


def test_a_mandatory_column_is_not_reported_twice():
    """Blank mandatory fields are already a blocking gap — saying it again as advisory is noise."""
    rows = [["2025-01-10", "INV-1", "Buyer", "300000000000003", "Goods", 1000.0, "15%", None]
            for _ in range(12)]
    r = run([item()], [doc(rows=rows)])

    assert "empty-mandatory-field" in kinds(r)
    assert [g for g in r.gaps if g.kind == "sparse-column"
            and "VAT amount" in g.detail] == []


def test_a_short_file_is_not_judged_on_density():
    """Two of three rows blank is not a pattern, and a letter about it would be embarrassing."""
    rows = [["2025-01-10", "INV-1", "Buyer", "300000000000003", "Goods", 1000.0, "15%", 150.0],
            ["2025-01-11", "INV-2", "Buyer", "", "Goods", 1000.0, "15%", 150.0],
            ["2025-01-12", "INV-3", "Buyer", "", "Goods", 1000.0, "15%", 150.0]]
    assert "sparse-column" not in kinds(run([item()], [doc(rows=rows)]))


# --------------------------------------------------------------- the four words
def gap(kind, *, severity="blocking", item_id=1, source="deterministic", detail="x"):
    return SimpleNamespace(kind=kind, severity=severity, request_item_id=item_id,
                           source=source, detail=detail)


def test_an_item_with_nothing_against_it_is_received():
    a = assessment([item()], [doc()], [])
    assert a["items"][0]["state"] == RECEIVED
    assert a["summary"][RECEIVED] == 1


def test_an_item_with_nothing_supplied_is_missing():
    a = assessment([item()], [], [gap("missing-item")])
    assert a["items"][0]["state"] == MISSING


def test_a_supplied_file_that_fails_a_check_is_incomplete_not_missing():
    a = assessment([item()], [doc()], [gap("missing-column")])
    assert a["items"][0]["state"] == INCOMPLETE, \
        "the taxpayer answered — badly. Telling them nothing arrived would be wrong."


def test_a_judgement_the_checker_cannot_settle_is_for_the_auditor():
    """Incomplete and needs-review are different things, and a chase letter follows only one."""
    for kind in ("wrong-document", "other-worksheet"):
        a = assessment([item()], [doc()], [gap(kind)])
        assert a["items"][0]["state"] == NEEDS_REVIEW, kind


def test_a_model_proposed_gap_is_always_the_auditors_call():
    a = assessment([item()], [doc()], [gap("too-vague", severity="advisory", source="claude")])
    assert a["items"][0]["state"] == NEEDS_REVIEW


def test_the_worst_thing_said_about_an_item_is_the_one_shown():
    a = assessment([item()], [doc()],
                   [gap("wrong-period", severity="advisory"), gap("missing-column")])
    assert a["items"][0]["state"] == INCOMPLETE
    assert a["items"][0]["blocking"] == 1
    assert a["items"][0]["advisory"] == 1


def test_a_waived_item_is_not_presented_as_outstanding():
    a = assessment([item(status="waived")], [], [gap("missing-item")])
    assert a["items"] == []


def test_a_file_answering_nothing_on_the_request_is_the_auditors_call():
    a = assessment([], [doc(item_id=None, filename="bank.xlsx")], [])
    assert a["items"][0]["state"] == NEEDS_REVIEW
    assert a["items"][0]["label"] == "bank.xlsx"


def test_the_states_are_derived_not_stored():
    """A fixed gap changes the word with no state to reconcile — the whole point of deriving it."""
    before = assessment([item()], [doc()], [gap("missing-column")])
    after = assessment([item()], [doc()], [])
    assert (before["items"][0]["state"], after["items"][0]["state"]) == (INCOMPLETE, RECEIVED)
