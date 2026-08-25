"""Adjudicating the two ZATCA tests.

Both read the comparison the deterministic matcher already produced — they do no matching of
their own. That division is the point: `pipeline/reconciliation.py` decides *what disagrees*
and this file decides *what that is worth*, so a change to the matching rules cannot quietly
change an amount, and a change here cannot quietly change what counts as a mismatch.

The two tests carry **different bases**, because they are about different money:

* `zatca-unmatched` — invoices the Authority holds that the listing does not contain. Their VAT
  is additional to everything the listing totals, so it cannot be the same riyals as
  `listing-vs-declared`, which compares the listing against the box.
* `zatca-value-mismatch` — invoices on both sides carrying different figures. The amount is the
  net of the differences, which is neither of the two totals.

Keeping them apart is what stops `findings.exposure()` counting one excess twice, and it is why
the agent proposes two hypotheses rather than one with a combined figure.
"""
from __future__ import annotations

from .contracts import Adjudication, Hypothesis

MAX_CITED = 6


def _is_are(n: int) -> str:
    """These sentences reach a report and a taxpayer letter. "1 invoices carry" reads as a
    machine wrote it and nobody checked, which is exactly the impression to avoid."""
    return "is" if n == 1 else "are"


def _comparison(ctx) -> dict | None:
    c = getattr(ctx, "zatca", None)
    return c if (c and c.get("comparable")) else None


def _unavailable(h: Hypothesis, ctx) -> Adjudication | None:
    """Insufficient evidence is a real verdict here, and the commonest one."""
    c = getattr(ctx, "zatca", None)
    if not c:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            explanation="No ZATCA invoice dataset is loaded for this case, so the taxpayer's "
                        "listing has nothing to be compared against.")
    if not c.get("comparable"):
        return Adjudication(hypothesis_id=h.id, status="insufficient-evidence",
                            explanation=c.get("note", "The two populations cannot be compared."))
    return None


def _cited(mismatches: list[dict]) -> list[str]:
    return [m["detail"] for m in mismatches[:MAX_CITED]]


def zatca_unmatched(h: Hypothesis, ctx) -> Adjudication:
    """VAT on invoices ZATCA holds and the taxpayer's listing does not."""
    stop = _unavailable(h, ctx)
    if stop is not None:
        return stop
    c = _comparison(ctx)
    found = [m for m in c["mismatches"] if m["code"] == "ZR-01"]
    if not found:
        return Adjudication(
            hypothesis_id=h.id, status="refuted",
            detail={"basis": "zatca-unmatched", "matched": c["matched_count"],
                    "rows_matched": c["matched_count"]},
            explanation=f"Every one of the {c['zatca_count']} invoices in ZATCA's records for "
                        f"this period appears in the listing supplied.")

    amount = round(sum(m["vat_at_stake"] for m in found), 2)
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=amount,
        detail={"basis": "zatca-unmatched", "rows_matched": len(found),
                "rows": c["zatca_count"], "matched": c["matched_count"],
                "examples": _cited(found),
                "refs": [m["ref"] for m in found[:MAX_CITED]]},
        explanation=(
            f"{len(found)} of the {c['zatca_count']} invoices in ZATCA's records for this "
            f"period {_is_are(len(found))} not in the listing supplied, carrying VAT of SAR "
            f"{amount:,.2f}. The listing therefore cannot be a complete record of the period's "
            f"sales."))


def zatca_value_mismatch(h: Hypothesis, ctx) -> Adjudication:
    """The net VAT difference on invoices both sides hold but record differently."""
    stop = _unavailable(h, ctx)
    if stop is not None:
        return stop
    c = _comparison(ctx)
    found = [m for m in c["mismatches"] if m["code"] == "ZR-03"]
    if not found:
        return Adjudication(
            hypothesis_id=h.id, status="refuted",
            detail={"basis": "zatca-values", "rows_matched": c["matched_count"]},
            explanation=f"The {c['matched_count']} invoices present in both populations carry "
                        f"the same VAT amount in each.")

    # Netted, not summed absolute: an invoice understated by 100 and another overstated by 100
    # leave the period's output tax unchanged, and reporting SAR 200 would describe a difference
    # that does not exist. The individual disagreements are still listed — they are a records
    # defect whether or not they net to anything.
    net = round(sum(m["vat_at_stake"] for m in found), 2)
    gross = round(sum(abs(m["vat_at_stake"]) for m in found), 2)
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=net,
        detail={"basis": "zatca-values", "rows_matched": len(found),
                "rows": c["matched_count"], "gross": gross, "examples": _cited(found),
                "refs": [m["ref"] for m in found[:MAX_CITED]]},
        explanation=(
            f"{len(found)} of the {c['matched_count']} invoices present in both the listing and "
            f"ZATCA's records {_is_are(len(found))} recorded with a different VAT amount in "
            f"each, differing by SAR {gross:,.2f} in total and SAR {net:,.2f} on balance. The "
            f"documents supplied do not correspond to the Authority's own record of the same "
            f"invoices."))


TESTS = {
    "zatca-unmatched": zatca_unmatched,
    "zatca-value-mismatch": zatca_value_mismatch,
}
