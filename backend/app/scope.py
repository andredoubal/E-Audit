"""The PoC's scope fence — what this demo reconciles, and what it deliberately does not.

A VAT return is not the taxpayer's sales listing restated. It is the tax-point-adjusted
population *plus* populations that appear in no listing at all (imports, reverse charge,
exempt supplies), *plus* adjustments, prior-period corrections and timing movements.

This PoC works one slice of that picture and is explicit about the rest. Each exclusion is
tagged with the reason code that would carry it, so the gap is a stated design boundary with a
named home in the taxonomy — not an oversight.

The population is whatever the taxpayer sent. Planning is out of scope, so there is no
risk-engine feed and no pre-computed reconciliation; the e-invoice tables remain only as the
fallback for a case with no upload, which is why the exclusions below are still phrased against
what an e-invoice feed would and would not carry.
"""
from __future__ import annotations

from .rule_taxonomy import REASON_CODES

HEADLINE = (
    "This demo starts when the taxpayer's documents arrive. It checks them against the "
    "request that was sent, then reconciles the standard-rated sales and purchase boxes for "
    "a single quarter from the records supplied. Everything below the line is a real part of "
    "the problem that this PoC does not attempt."
)

IN_SCOPE: tuple[dict[str, str], ...] = (
    {"item": "Was the response what we asked for",
     "detail": "The email the auditor sent becomes a checkable spec; the spreadsheets are "
               "tested against it for missing items, missing columns, blank mandatory fields, "
               "period coverage and totals that do not foot."},
    {"item": "Standard-rated sales (output VAT)",
     "detail": "Summed from the lines of the taxpayer's own listing that qualify for this box "
               "and this period. The e-invoice feed is the fallback where nothing was sent."},
    {"item": "Standard-rated purchases (input VAT)",
     "detail": "The same, on the purchase side — the documents on which this taxpayer is "
               "the buyer."},
    {"item": "Four agents over the records received",
     "detail": "Regulations, Data Entry, Calculation and Evidence & Coverage each propose what "
               "is worth testing; a deterministic adjudicator settles every one."},
    {"item": "One tax period, one return version",
     "detail": "2025 Q1, the return currently on file. No amendment history, no rolling "
               "re-reconciliation as later documents arrive."},
    {"item": "Four wired qualification rules",
     "detail": "Credit notes on both boxes (COR-01, COR-02) and tax-point straddle timing on "
               "both boxes (OUT-07, INP-09), plus auditor-confirmed taxpayer evidence."},
    {"item": "Materiality and prioritisation",
     "detail": "What is left unexplained banded against max(SAR 1,000, 0.5% of the box); cases "
               "ranked by exposure, deadline, history and quick-win."},
    {"item": "Imports of goods",
     "detail": "Not auto-reconstructed — there is no live customs feed. Counted only when the "
               "taxpayer's customs declaration is on file and the auditor reviews and confirms "
               "the SAR amount, exactly like any other taxpayer evidence."},
    {"item": "Reverse charge on imported services",
     "detail": "Not auto-reconstructed — there is no live AP feed. Counted only when supporting "
               "documentation (an AP ledger line, a self-billed invoice) is on file and the "
               "auditor confirms the amount. The RCM-01…10 rulebook family remains an unwired "
               "reference for the automated version this stands in for."},
    {"item": "Prior-period corrections (Box 14)",
     "detail": "The return's own stated Box-14 figure is accepted as a legitimate adjustment "
               "once the auditor reviews and confirms it. The engine does not independently "
               "verify which prior period, or which amended return version, it belongs to — "
               "see the assumptions register for what a full version-chain solution would need."},
    {"item": "Rounding and currency effects",
     "detail": "Per-invoice rounding amounts, where the listing or e-invoice feed carries them, "
               "are summed over the qualifying lines and closed against the residual "
               "automatically — no auditor confirmation needed, since this is fully computable "
               "from data already in hand rather than a judgement call."},
    {"item": "Zero-rated domestic sales", "detail":
     "A second reconciliation box, qualified and summed the same way as standard-rated sales "
     "but scoped to category Z / rate 0%, compared against the return's own declared "
     "zero-rated box. No coded tax-point or adjustment rules are wired for it yet — a first, "
     "honest declared-vs-reconstructed comparison, not the full standard-rated pipeline."},
)

OUT_OF_SCOPE: tuple[dict[str, str], ...] = (
    {"item": "Exempt and outside-scope supplies", "reason_code": "S01",
     "note": "Only the standard-rated and zero-rated categories are reconstructed. Exempt (E) "
             "and outside-scope (O) lines are excluded, and their boxes are seeded but never "
             "reconciled."},
    {"item": "VAT groups and branch identities", "reason_code": "S06",
     "note": "One taxpayer, one VAT number. No group representative, branch invoice sequences "
             "or membership changes."},
    {"item": "Cash-accounting taxpayers", "reason_code": "T05",
     "note": "Every demo taxpayer is on the accrual basis, so payment-date timing never moves "
             "a supply between periods."},
    {"item": "Full version-chain reconciliation of amended returns", "reason_code": "T08",
     "note": "The engine accepts the return's own stated Box-14 correction once the auditor "
             "confirms it (see in-scope), but does not automatically select the correct "
             "amended Data_Version, decompose Box-14 per error, or detect double-relief or an "
             "unsupported reversal — see the Word solution overview for the full design."},
    {"item": "Bad-debt relief", "reason_code": "A03",
     "note": "Output-tax adjustments after the original invoice period are out of scope."},
    {"item": "Partial exemption and blocked input", "reason_code": "A02",
     "note": "Full recovery is assumed on every purchase invoice."},
    {"item": "Summary invoices and B2C aggregation", "reason_code": "D02",
     "note": "Reconciliation is document-level only. No daily, store or POS batch tier, so "
             "high-volume simplified-invoice taxpayers are not represented."},
    {"item": "Automated import/reverse-charge reconstruction", "reason_code": "S04",
     "note": "There is no live customs or AP feed, so imports and reverse-charge are counted "
             "only via auditor-confirmed evidence (see in-scope), not reconstructed from a "
             "feed the way standard-rated sales/purchases are. The RCM-01…10 family remains "
             "an unwired reference for what the automated version would test."},
    {"item": "Buyer-side supplier matching", "reason_code": "R08",
     "note": "Input VAT is not cross-checked against the supplier's own outward e-invoices, "
             "which is where an over-claim would really be proven."},
    {"item": "Late arrivals and rolling reconciliation", "reason_code": "T03",
     "note": "A single closed-period pass. Documents cleared after the return was filed do not "
             "reopen the comparison."},
)

TAX_POINT_NOTE = (
    "Tax point is approximated by the invoice issue date, with delivery date used only for the "
    "period-straddle test (see the assumptions register). A true tax-point rule — earliest of "
    "payment, invoice or contractual due date, with special cases for continuous supply — is "
    "the first thing production would need."
)


def scope_card() -> dict:
    """The scope fence as data, so the README, the API and the UI cannot drift apart."""
    return {
        "headline": HEADLINE,
        "in_scope": list(IN_SCOPE),
        "out_of_scope": [
            {**row, "reason_label": REASON_CODES.get(row["reason_code"], ("", ""))[1]}
            for row in OUT_OF_SCOPE
        ],
        "tax_point_note": TAX_POINT_NOTE,
    }
