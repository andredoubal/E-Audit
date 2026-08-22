"""The fifth agent, and the two tests that settle it.

The agent's whole discipline is in what it does *not* do. It does no matching — that is closed
arithmetic in `pipeline/reconciliation.py` — and it states no figure, exactly like the other
four. What it contributes is the judgement the matcher cannot make: that a population of
unmatched invoices is worth putting to the taxpayer as undisclosed sales, and that disagreeing
figures on matched invoices are worth putting as a records defect.

The property tested hardest is the one that would corrupt the assessment silently: the two
hypotheses must rest on **different bases**, because invoices absent from the listing are money
additional to everything the listing totals, while a value difference is a movement within it.
Share a basis with `listing-vs-declared` and the same riyals get assessed twice.
"""
import pytest

from app.agents.adjudicator import CaseContext, adjudicate
from app.agents.findings import exposure, from_investigation
from app.agents.roster import zatca_reconciliation
from app.pipeline import reconciliation as zr

COLUMNS = ["invoice_number", "invoice_date", "customer_name", "customer_vat_number",
           "taxable_amount", "vat_amount"]


def file(*specs) -> dict:
    return {"columns": list(COLUMNS),
            "rows": [[ref, d, "Buyer Co", "300000000000003", net, vat]
                     for ref, d, net, vat in specs]}


BASE = (("INV-001", "2025-01-10", 1000.0, 150.0),
        ("INV-002", "2025-01-20", 2000.0, 300.0),
        ("INV-003", "2025-02-05", 3000.0, 450.0))

RECON = {"declared": 900.0, "expected": 900.0, "difference": 0.0, "unexplained": 0.0,
         "materiality": 100.0, "population_source": "document",
         "purchase": {"declared": 0.0, "expected": 0.0, "difference": 0.0,
                      "unexplained": 0.0, "materiality": 100.0}}


def ctx_for(listing, zatca) -> CaseContext:
    comparison = zr.compare(listing=listing, zatca=zatca,
                            listing_name="Sales.xlsx", zatca_name="ZATCA.xlsx")
    return CaseContext(recon=dict(RECON), documents=[], zatca=comparison.to_dict())


def settled(ctx):
    """Every hypothesis the agent raises, adjudicated. {id: (hypothesis, adjudication)}."""
    return {h.id: (h, adjudicate(h, ctx)) for h in zatca_reconciliation(ctx)}


# --------------------------------------------------------------- silence
def test_the_agent_says_nothing_without_a_dataset():
    """Silence is correct: a hypothesis that can only return insufficient evidence is noise."""
    ctx = CaseContext(recon=dict(RECON), zatca=None)
    assert zatca_reconciliation(ctx) == []


def test_the_agent_says_nothing_when_only_one_side_is_present():
    ctx = ctx_for(file(*BASE), None)
    assert ctx.zatca["comparable"] is False
    assert zatca_reconciliation(ctx) == []


def test_the_agent_says_nothing_when_the_two_populations_agree():
    assert zatca_reconciliation(ctx_for(file(*BASE), file(*BASE))) == []


# --------------------------------------------------------------- unmatched invoices
def test_invoices_zatca_holds_and_the_listing_omits_become_a_hypothesis():
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    ctx = ctx_for(file(*BASE), file(*extra))
    h, a = settled(ctx)["ZR-01"]

    assert h.outcome_code == "SAL-UNDISCLOSED"
    assert h.agent == "ZATCA Reconciliation"
    assert a.status == "confirmed"
    assert a.amount == 1200.0, "the VAT the adjudicator computed, not anything the agent said"


def test_the_agent_states_no_figure_of_its_own():
    """The contract every agent obeys: language only, and a typed question."""
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    for h in zatca_reconciliation(ctx_for(file(*BASE), file(*extra))):
        assert not any(ch.isdigit() for ch in h.claim), \
            f"{h.id} put a figure in its claim: {h.claim}"


def test_the_trigger_is_recorded_beside_the_claim():
    """An auditor defends a finding to a taxpayer; "an agent proposed it" is not a defence."""
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    h = zatca_reconciliation(ctx_for(file(*BASE), file(*extra)))[0]
    assert "ZATCA" in h.why and "1 of" in h.why
    # these sentences reach a report; "1 invoices have" reads as unread machine output
    assert "1 of the 4 invoices in ZATCA's records for this period has" in h.why


def test_no_unmatched_invoices_refutes_rather_than_going_quiet():
    """The good outcome for the taxpayer is still a verdict, and belongs on the file."""
    ctx = ctx_for(file(*BASE), file(*BASE))
    from app.agents.contracts import Hypothesis, TestSpec
    h = Hypothesis(id="ZR-01", agent="ZATCA Reconciliation", claim="x",
                   test=TestSpec(kind="zatca-unmatched", box="output"))
    a = adjudicate(h, ctx)
    assert a.status == "refuted"
    assert a.amount == 0.0


# --------------------------------------------------------------- value mismatches
def test_differing_vat_on_a_matched_invoice_becomes_its_own_hypothesis():
    changed = (("INV-001", "2025-01-10", 1000.0, 190.0),) + BASE[1:]
    ctx = ctx_for(file(*BASE), file(*changed))
    h, a = settled(ctx)["ZR-02"]

    assert h.outcome_code == "SAL-MISMATCH"
    assert a.status == "confirmed"
    assert a.amount == 40.0
    assert "1 of the 3 invoices present in both the listing and ZATCA's records is" \
        in a.explanation, "the explanation is written for a report, not for a log"


def test_offsetting_differences_net_to_what_the_period_actually_owes():
    """One invoice understated by 100 and another overstated by 100 leave output tax
    unchanged. Reporting SAR 200 would describe a difference that does not exist."""
    changed = (("INV-001", "2025-01-10", 1000.0, 250.0),
               ("INV-002", "2025-01-20", 2000.0, 200.0)) + BASE[2:]
    _, a = settled(ctx_for(file(*BASE), file(*changed)))["ZR-02"]

    assert a.amount == 0.0
    assert a.detail["gross"] == 200.0, "the individual disagreements are still on the record"
    assert a.detail["rows_matched"] == 2


# --------------------------------------------------------------- the money is not double-counted
def test_the_two_hypotheses_rest_on_different_evidence():
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    changed = extra[:1] + (("INV-002", "2025-01-20", 2000.0, 340.0),) + extra[2:]
    out = settled(ctx_for(file(*BASE), file(*changed)))

    bases = {a.detail["basis"] for _, a in out.values()}
    assert len(bases) == 2, "an omitted invoice and a restated one are not the same riyals"


def test_the_zatca_basis_is_not_the_listings_basis():
    """`listing-vs-declared` compares the listing against the box. An invoice absent from the
    listing is additional to it, so sharing a basis would drop one of the two amounts."""
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    _, a = settled(ctx_for(file(*BASE), file(*extra)))["ZR-01"]
    assert a.detail["basis"] == "zatca-unmatched"
    assert "excess" not in a.detail["basis"]


def test_both_findings_reach_the_vocabulary_and_are_counted_once_each():
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    changed = extra[:1] + (("INV-002", "2025-01-20", 2000.0, 340.0),) + extra[2:]
    ctx = ctx_for(file(*BASE), file(*changed))
    hyps = zatca_reconciliation(ctx)
    adjs = [adjudicate(h, ctx) for h in hyps]

    found = from_investigation(hyps, adjs)
    assert {f.code for f in found} == {"SAL-UNDISCLOSED", "SAL-MISMATCH"}
    for f in found:
        assert not any(ch.isdigit() for ch in f.statement), \
            "the vocabulary carries no digits — the amount travels beside it"

    e = exposure(found)
    # An invoice ZATCA holds and the listing omits is output tax to assess. Invoices whose
    # figures disagree are a records defect — real, and not an amount until someone decides
    # what follows from it. Adding the two would put SAR 1,240 in a letter as though it were
    # all assessable.
    assert e["increases_output"] == pytest.approx(1200.0)
    assert e["documentation_at_risk"] == pytest.approx(40.0)
    assert e["total"] == pytest.approx(1200.0)
    assert e["distinct_bases"] == 2


# --------------------------------------------------------------- the ids stay stable
def test_the_hypothesis_ids_are_stable_so_a_re_run_merges():
    """`(case_id, hypothesis_id)` is the merge key. Minting fresh ids would duplicate rows."""
    extra = BASE + (("INV-004", "2025-03-01", 8000.0, 1200.0),)
    first = [h.id for h in zatca_reconciliation(ctx_for(file(*BASE), file(*extra)))]
    second = [h.id for h in zatca_reconciliation(ctx_for(file(*BASE), file(*extra)))]
    assert first == second == ["ZR-01"]
