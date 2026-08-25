"""The regulatory control framework, and the asymmetry it exists to make reachable.

    Reconciled  ≠  compliant.
    Unreconciled ≠ non-compliant.

Until this landed, every regulatory citation in the application hung off a confirmed
hypothesis, so a case whose numbers agreed produced no regulatory analysis at all. The first
test below is the one that matters most: a comparison that reconciles to the riyal, and a
control that raises a concern anyway.

Every fixture is synthetic. None is the demo case.
"""
from __future__ import annotations

import pytest

from app.evidence import profile as prof
from app.recon import engine, planner, registry as reg, status as S
from app.regulatory import applicability, checks as CK, controls as C, facts as F

SALES_COLS = ["invoice_date", "invoice_number", "customer_name", "customer_vat_number",
              "taxable_amount", "vat_rate", "vat_amount"]
PURCH_COLS = ["invoice_date", "invoice_number", "supplier_name", "description",
              "taxable_amount", "vat_amount"]


def profiled(filename: str, columns: list[str], rows: list[list]) -> dict:
    return prof.build({"filename": filename,
                       "content": {"format": "csv", "columns": columns, "rows": rows}}).to_dict()


def screen(files: dict[str, tuple[list[str], list[list]]],
           declared: dict[str, float] | None = None, workstream: str = "") -> dict:
    profiles = [profiled(name, cols, rows) for name, (cols, rows) in files.items()]
    rows_by_file = {name: rows for name, (_, rows) in files.items()}
    return applicability.assess(profiles, rows_by_file, declared or {}, workstream=workstream)


def control(result: dict, control_id: str) -> dict:
    return next(c for c in result["controls"] if c["control_id"] == control_id)


# ============================================================ the asymmetry
def test_a_case_that_reconciles_exactly_can_still_raise_a_regulatory_concern():
    """The cell that was structurally unreachable before this framework existed.

    The register totals precisely what the return declares — there is no variance of any size
    to investigate — and Article 53 still has something to say, because the rows do not carry
    every particular the provision requires.
    """
    rows = [["2025-01-14", "INV-1", "Buyer A", "300000000000003", 100000, 15, 15000],
            ["2025-02-03", "", "Buyer B", "300000000000003", 100000, 15, 15000]]
    files = {"reg.csv": (SALES_COLS, rows)}

    # 1 · the numbers agree, to the riyal
    profiles = [profiled("reg.csv", SALES_COLS, rows)]
    plan = planner.plan_one(reg.BY_ID["sales-register-vs-return"], profiles,
                            return_on_file=True)
    recon = engine.run(plan, profiles={"reg.csv": profiles[0]}, rows_by_file={"reg.csv": rows},
                       declared={"standard_rate_sales": 30000.0},
                       period_from=__import__("datetime").date(2025, 1, 1),
                       period_to=__import__("datetime").date(2025, 3, 31))
    assert recon.status == S.RECONCILED
    assert recon.variance == 0.0

    # 2 · and a control raises a concern regardless
    result = screen(files, {"standard_rate_sales": 30000.0})
    invoice_content = control(result, "RC-SAL-INV-01")
    assert invoice_content["status"] == C.CONCERN
    assert invoice_content["citation"]["label"] == "Article 53"
    assert invoice_content["outcome"]["rows"] == [2], "the row with no invoice number"


def test_a_case_that_does_not_reconcile_is_not_thereby_non_compliant():
    """The mirror. A variance brings nothing into scope on its own — scope comes from the
    evidence and the return, never from the size of a difference."""
    rows = [["2025-01-14", "INV-1", "Buyer A", "300000000000003", 1000000, 15, 150000]]
    result = screen({"reg.csv": (SALES_COLS, rows)}, {"standard_rate_sales": 1.0})

    invoice_content = control(result, "RC-SAL-INV-01")
    assert invoice_content["status"] == C.TESTED, \
        "a large variance does not make a well-formed invoice ill-formed"
    assert "no issue" in invoice_content["status_label"].lower()


# ============================================================ scope screening
def test_a_control_out_of_scope_says_which_circumstance_is_absent():
    """Not 'not applicable' as a shrug — the auditor needs to know what would change it."""
    result = screen({"reg.csv": (SALES_COLS,
                                 [["2025-01-14", "INV-1", "B", "3", 100, 15, 15]])})
    exempt = control(result, "RC-PUR-PROP-01")
    assert exempt["status"] == C.NOT_APPLICABLE
    assert "no exempt supplies appear in the evidence" in exempt["scope_reason"]


def test_a_zero_rated_supply_brings_the_export_evidence_control_into_scope():
    """Scope follows the evidence, so a case with zero-rated lines gets a control a wholly
    standard-rated case correctly never sees."""
    rows = [["2025-01-14", "INV-1", "Buyer A", "300000000000003", 100000, 0, 0],
            ["2025-02-03", "INV-2", "Buyer B", "300000000000003", 100000, 15, 15000]]
    result = screen({"reg.csv": (SALES_COLS, rows)})

    exports = control(result, "RC-SAL-ZR-01")
    assert exports["status"] != C.NOT_APPLICABLE
    assert "zero-rated" in exports["scope_reason"]
    assert result["facts"]["vat_treatments"] == ["standard", "zero-rated"]


def test_a_control_can_come_into_scope_from_the_return_with_no_dataset_at_all():
    """The purest form of regulation-driven screening: input VAT was claimed, so the
    deduction provisions are in scope — and the absence of a register is the finding-shaped
    thing, not a reason to stay silent."""
    result = screen({}, {"standard_rate_purchase": 150000.0})
    deduction = control(result, "RC-PUR-DED-01")
    assert deduction["status"] == C.NO_EVIDENCE
    assert "relevant box" in deduction["scope_reason"]
    assert "purchase register" in deduction["missing_evidence"]


# ============================================================ testability
def test_a_control_in_scope_with_no_evidence_says_what_it_needs():
    rows = [["2025-01-14", "INV-1", "Buyer A", "300000000000003", 100000, 15, 15000]]
    result = screen({"reg.csv": (SALES_COLS, rows)})
    timing = control(result, "RC-SAL-DOS-01")
    assert timing["status"] == C.NO_EVIDENCE
    assert "supply date" in timing["missing_evidence"]


def test_a_provision_that_needs_a_person_says_so_rather_than_guessing():
    """A control whose article carries exceptions this engine does not model cannot be settled
    by matching words in a description, and reporting that is the honest answer."""
    rows = [["2025-01-09", "PI-1", "Vendor A", "Office refreshments", 4000, 600]]
    result = screen({"p.csv": (PURCH_COLS, rows)}, {"standard_rate_purchase": 600.0})

    blocked = control(result, "RC-PUR-BLK-01")
    assert blocked["status"] == C.POTENTIAL
    assert blocked["testability"] == C.AI_ASSISTED
    assert "put to the auditor rather than answered" in blocked["detail"]


# ============================================================ citations
def test_every_citation_is_retrieved_and_carries_the_articles_own_words():
    result = screen({"reg.csv": (SALES_COLS,
                                 [["2025-01-14", "INV-1", "B", "3", 100, 15, 15]])},
                    {"standard_rate_purchase": 1.0})
    for c in result["controls"]:
        cite = c["citation"]
        assert cite["state"] in ("found", "needs-validation"), c["control_id"]
        assert cite["label"].startswith("Article ")
        assert cite["text"], "a citation with no text is a paraphrase nobody can check"


def test_a_superseded_article_is_never_quoted_as_the_current_rule():
    """31 of the 79 articles are shown in wording that predates the current Arabic. Article 50
    — the blocked-input provision — is one of them, and an assessment resting on it says so."""
    rows = [["2025-01-09", "PI-1", "Vendor A", "Entertainment", 4000, 600]]
    result = screen({"p.csv": (PURCH_COLS, rows)}, {"standard_rate_purchase": 600.0})

    blocked = control(result, "RC-PUR-BLK-01")
    assert blocked["citation"]["state"] == "needs-validation"
    assert blocked["citation"]["english_current"] is False
    assert blocked["citation"]["last_amended_year"] == 2024
    assert "superseded" in blocked["citation"]["note"]


def test_a_control_citing_an_article_outside_the_corpus_refuses_to_load():
    """There is no path by which a provision can be invented, because nothing composes one."""
    fake = {"control_id": "RC-X", "title": "x", "article": 999, "requirement": "x",
            "testability": "deterministic", "check": "needs_review"}
    with pytest.raises(C.ControlError, match="not in the corpus"):
        C._parse(fake, {1, 2, 3})


# ============================================================ honesty about coverage
def test_the_control_set_publishes_how_little_of_the_corpus_it_reaches():
    """Ten controls over seventy-nine articles is a start, not coverage, and a screening tool
    that does not say so is claiming more than it has."""
    cov = C.coverage()
    assert cov["review_status"] == "draft-unreviewed"
    assert cov["articles_uncovered"] > cov["articles_covered"]
    assert cov["review_note"], "the draft has to say on its face that it is a draft"


def test_the_assessment_carries_the_draft_status_to_every_consumer():
    result = screen({"reg.csv": (SALES_COLS,
                                 [["2025-01-14", "INV-1", "B", "3", 100, 15, 15]])})
    assert result["review_status"] == "draft-unreviewed"
    assert "NOT reviewed legal analysis" in result["review_note"]


# ============================================================ the checks themselves
def test_a_defect_in_a_listing_is_a_question_about_the_invoice_not_a_finding_against_it():
    """The listing is the taxpayer's account of what was issued. Inferring that the invoice
    itself lacked a particular is a step the evidence does not support."""
    rows = [["2025-01-14", "", "Buyer A", "300000000000003", 100000, 15, 15000]]
    result = screen({"reg.csv": (SALES_COLS, rows)})
    detail = control(result, "RC-SAL-INV-01")["detail"]
    assert "question about those documents" in detail
    assert "rather than evidence that the invoices themselves lacked" in detail


def test_a_conditionally_required_particular_is_advisory_not_a_defect():
    """A customer VAT number is required where the customer is a taxable person. Missing it is
    a question, and may be perfectly correct for a supply to a consumer."""
    rows = [["2025-01-14", "INV-1", "Buyer A", "", 100000, 15, 15000]]
    result = screen({"reg.csv": (SALES_COLS, rows)})
    detail = control(result, "RC-SAL-INV-01")["detail"]
    assert "Every required particular is present" in detail
    assert "may be correct where those circumstances do not arise" in detail


def test_holding_the_evidence_is_not_the_same_as_the_evidence_being_adequate():
    rows = [["2025-01-14", "INV-1", "Buyer A", "300000000000003", 100000, 0, 0]]
    customs = (["date", "customs_declaration_no", "supplier_name", "vat_amount"],
               [["2025-01-20", "SAD-1", "Overseas Co", 0]])
    result = screen({"reg.csv": (SALES_COLS, rows), "c.csv": customs})
    exports = control(result, "RC-SAL-ZR-01")
    assert exports["status"] == C.TESTED
    assert "is a question this cannot reach" in exports["outcome"]["detail"]


def test_records_readable_reports_a_blocking_defect_as_a_concern():
    rows = [["2025-01-14", "INV-1", "Buyer A", "300000000000003", 100000, 15, None]]
    result = screen({"reg.csv": (SALES_COLS, rows)})
    records = control(result, "RC-SAL-REC-01")
    assert records["status"] == C.CONCERN
    assert "cannot be read well enough" in records["detail"]


# ============================================================ workstream scoping
def test_a_workstream_gets_its_own_controls_and_the_shared_ones():
    result = screen({"reg.csv": (SALES_COLS,
                                 [["2025-01-14", "INV-1", "B", "3", 100, 15, 15]])},
                    workstream="sales")
    applies = {c["applies_to"] for c in result["controls"]}
    assert applies <= {"sales", "both"}
    assert any(c["control_id"] == "RC-SAL-REC-01" for c in result["controls"]), \
        "a control that applies to both belongs in each workstream"
