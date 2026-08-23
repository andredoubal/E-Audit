"""The investigation as a handful of cards, not as a list of everything that ran.

An auditor opening Investigation is asking one question: *what did this find?* The panel that
answered it listed every hypothesis with its verdict, its confidence signals, its test
parameters, its citation and two decision controls — twelve of those is a page you scroll past
rather than a summary you read.

Three rules shape what a card is:

**One card per basis, never one per hypothesis.** A sales listing above the return is
simultaneously "higher than declared", "not disclosed", "does not correspond" and the
no-trial-balance variant — four statements, one test over one file. `findings.exposure()`
already counts each basis once for exactly this reason; the summary groups the same way, so the
excess is stated once with the alternative readings named beneath it rather than four times at
four cards.

**An observation is not a violation.** The card separates what was *measured* from what it
*may mean*: `observed` is the adjudicator's own sentence about the documents, `reading` is the
vocabulary statement this would become **if the auditor accepts it**. A difference between a
listing and a return is a fact; that it is undeclared output tax is a conclusion, and only the
auditor reaches it.

**Nothing here is phrased ad hoc.** The title is `Outcome.short`, the reading is
`Outcome.statement`, the observation is the engine's `explanation`. No sentence in a card is
written at this call site, and no figure is computed here — the amounts are read off the
adjudicated hypotheses.
"""
from __future__ import annotations

from .. import outcomes

# What the auditor is being told about the strength of the thing, in the epistemic sense rather
# than the monetary one. `unresolved` is a real answer: a test that could not be settled on the
# evidence held is not a weak finding, it is an open question.
OBSERVATION = "observation"      # a deterministic test settled it against the documents
UNRESOLVED = "unresolved"        # it could not be settled on what is on file
DATA_QUALITY = "data-quality"    # a defect in the records, with no amount claimed

_SETTLED = ("supported", "partially-supported")
_OPEN = ("inconclusive", "pending-info")

# ZATCA matcher categories that describe the *records* rather than the money. They raise no
# hypothesis — there is no amount to claim and nothing to put to the taxpayer as an adjustment —
# but an auditor still needs to know the matching could not see part of the file.
_RECORD_DEFECTS: dict[str, tuple[str, str]] = {
    "identifier": (
        "Invoices that cannot be matched",
        "Some records carry no invoice identifier the matching can use, so they are neither "
        "confirmed present in both sets nor reported as missing from either."),
    "duplicate": (
        "Repeated invoice numbers",
        "An invoice number appears more than once. Until it is resolved a single supply may be "
        "counted twice, or two supplies may be recorded as one."),
    "sequence": (
        "Break in the invoice numbering",
        "The invoice numbering has a gap. It may be nothing, and it may be a run of invoices "
        "that was never included."),
}


def _adjusts(code: str) -> bool:
    o = outcomes.BY_CODE.get(code or "")
    return bool(o) and o.effect != outcomes.DOCUMENTATION


def _lead(group: list[dict]) -> dict:
    """The hypothesis that speaks for the group.

    Settled before open, then the reading that carries an adjustment before the documentation
    reading of the same evidence. That order is the one `exposure()` already applies when it
    excludes documentation risk on evidence that is producing an adjustment: where one file
    supports both "the listing exceeds the return" and "the documents do not correspond", the
    excess is the finding and the correspondence defect is another way of saying it.
    """
    return sorted(group, key=lambda h: (h["status"] not in _SETTLED,
                                        not _adjusts(h.get("outcome_code") or ""),
                                        -abs(h["amount"])))[0]


def _clip(text: str, limit: int = 72) -> str:
    """A card title's worth of a sentence: the first clause, and no more than a line of it."""
    head = text.split(" — ")[0].split(", which")[0].strip().rstrip(".")
    if len(head) <= limit:
        return head
    cut = head[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _statement(code: str) -> str:
    o = outcomes.BY_CODE.get(code or "")
    return o.statement if o else ""


def _title(h: dict) -> str:
    o = outcomes.BY_CODE.get(h.get("outcome_code") or "")
    if o:
        return o.short
    # An agent may raise something the vocabulary has no entry for — a detector that reasons
    # about our own arithmetic, say. It still belongs in the summary; it just has no statement
    # to become, and the claim is the best label there is.
    return _clip(h.get("claim") or h["hypothesis_id"])


def _card(group: list[dict]) -> dict:
    head = _lead(group)
    kind = OBSERVATION if head["status"] in _SETTLED else UNRESOLVED
    # Every other reading of the same evidence, named but not counted. This is the whole reason
    # the grouping exists: four statements over one file is one matter, at one amount.
    alternatives = [
        s for s in dict.fromkeys(_statement(h.get("outcome_code") or "") for h in group)
        if s and s != _statement(head.get("outcome_code") or "")
    ]
    decisions = [h["decision"]["decision"] for h in group if h.get("decision")]
    return {
        "key": (head.get("detail") or {}).get("basis") or head["hypothesis_id"],
        "kind": kind,
        "title": _title(head),
        # The engine's own sentence about what it measured. Where the adjudicator had nothing to
        # say, the agent's observation is the next best thing — and it is still not a verdict.
        "observed": head.get("explanation") or head.get("why") or "",
        "reading": _statement(head.get("outcome_code") or ""),
        "alternatives": alternatives,
        "amount": max((abs(h["amount"]) for h in group), default=0.0),
        "confidence": (head.get("confidence") or {}).get("band", ""),
        "hypothesis_ids": [h["hypothesis_id"] for h in group],
        "agents": list(dict.fromkeys(h["agent"] for h in group)),
        "outcome_code": head.get("outcome_code") or "",
        "decision": decisions[0] if decisions else "",
        "needs_info": head.get("needs_info_note") or "",
    }


def _record_cards(zatca: dict | None) -> list[dict]:
    """Defects in the records themselves, from the ZATCA matcher.

    Only when a dataset is loaded and the two sides were actually compared — with one side there
    is no matching, so there is nothing to report and reporting it anyway would be an invented
    finding.
    """
    if not zatca or not zatca.get("comparable"):
        return []
    out = []
    for cat in zatca.get("categories", []):
        entry = _RECORD_DEFECTS.get(cat.get("category", ""))
        if not entry or not cat.get("count"):
            continue
        title, meaning = entry
        out.append({
            "key": f"zatca-records|{cat['category']}",
            "kind": DATA_QUALITY,
            "title": title,
            "observed": f"{cat['count']} affected in the comparison against "
                        f"{zatca.get('zatca_name') or 'the Authority’s records'}.",
            "reading": meaning,
            "alternatives": [],
            "amount": 0.0,
            "confidence": "",
            "hypothesis_ids": [],
            "agents": ["ZATCA Reconciliation"],
            "outcome_code": "",
            "decision": "",
            "needs_info": "",
        })
    return out


def build(state: dict, *, zatca: dict | None = None) -> dict:
    """The investigation summary: a few cards, and what they add up to.

    `state` is `investigation_service.state()`. `zatca` is the comparison state when a dataset is
    loaded, and `None` when it is not — the summary must read the same either way.
    """
    live = [h for h in state.get("hypotheses", []) if not h.get("stale")]
    refuted = [h for h in live if h["status"] == "refuted"]
    considered = [h for h in live if h["status"] in _SETTLED + _OPEN]

    groups: dict[str, list[dict]] = {}
    for h in considered:
        key = (h.get("detail") or {}).get("basis") or h["hypothesis_id"]
        groups.setdefault(key, []).append(h)

    cards = [_card(g) for g in groups.values()]
    cards += _record_cards(zatca)
    # Biggest first, and a card with no amount after every card that has one: an auditor works
    # down from the money, and a records defect is context for that rather than a rival to it.
    cards.sort(key=lambda c: (c["kind"] == DATA_QUALITY, -c["amount"], c["title"]))

    # One amount per basis, summed. Deliberately not called a proposed adjustment: nothing here
    # has been accepted, and several of these may turn out to be the same money seen twice or
    # explained away entirely.
    at_stake = sum(c["amount"] for c in cards)
    return {
        "cards": cards,
        "totals": {
            "at_stake": at_stake,
            "observations": len([c for c in cards if c["kind"] == OBSERVATION]),
            "unresolved": len([c for c in cards if c["kind"] == UNRESOLVED]),
            "record_defects": len([c for c in cards if c["kind"] == DATA_QUALITY]),
            "not_supported": len(refuted),
            "decided": len([c for c in cards if c["decision"]]),
        },
        "runs": len(state.get("runs", [])),
    }


__all__ = ["build", "OBSERVATION", "UNRESOLVED", "DATA_QUALITY"]
