"""Recover the request spec from a whole chain, not from one pasted message."""
from __future__ import annotations

from dataclasses import replace

from .from_email import ParsedItem, ParsedRequest, parse_email


def _key_of(m) -> tuple:
    """Chain order: when it was sent, falling back to the order it was filed in."""
    return (str(getattr(m, "sent_at", "") or ""), int(getattr(m, "seq", 0) or 0))


def from_messages(messages) -> tuple[ParsedRequest, list[dict], str]:
    """The merged spec, and what each outbound message contributed to it.

    The second return value is the audit trail for the parse. An auditor confirming a spec built
    from five emails has to be able to see *which* email asked for the trial balance — "the
    system read it somewhere in the chain" is not something they can check.
    """
    out = ParsedRequest()
    per_message: list[dict] = []
    by_key: dict[str, ParsedItem] = {}
    columns: dict[str, list[str]] = {}
    unmatched: list[str] = []
    period_from = period_to = None
    period_note = ""

    ordered = sorted(messages, key=_key_of)
    for m in ordered:
        outbound = getattr(m, "direction", "outbound") == "outbound"
        body = getattr(m, "body", "") or ""
        seq = getattr(m, "seq", 0)
        if not outbound:
            per_message.append({"seq": seq, "direction": "inbound", "subject":
                                getattr(m, "subject", ""), "items": [],
                                "note": "the taxpayer's own message — read for the record, "
                                        "not for what was asked for"})
            continue

        one = parse_email(body)
        added: list[str] = []
        for item in one.items:
            existing = by_key.get(item.key)
            if existing is None:
                by_key[item.key] = item
                added.append(item.key)
            else:
                # Asked again. Keep the first cue; take any column the later message adds.
                merged = tuple(dict.fromkeys(existing.required_columns + item.required_columns))
                by_key[item.key] = replace(existing, required_columns=merged)

        for key, cols in one.columns_stated.items():
            have = columns.setdefault(key, [])
            have.extend(c for c in cols if c not in have)

        for u in one.unmatched:
            if u not in unmatched:
                unmatched.append(u)

        if one.period_from:
            if period_from is None:
                period_from, period_to = one.period_from, one.period_to
            elif (one.period_from, one.period_to) != (period_from, period_to):
                period_note = (f"message {seq} names {one.period_from} to {one.period_to}, "
                               f"which is not the period read from the earlier message "
                               f"({period_from} to {period_to}) — confirm which applies")
        if one.due_phrase:
            out.due_phrase = one.due_phrase        # a later chase replaces the earlier deadline

        per_message.append({
            "seq": seq, "direction": "outbound",
            "subject": getattr(m, "subject", ""),
            "items": added,
            "note": "" if added else "nothing here that was not already asked for",
        })

    # Columns named anywhere in the chain apply to the merged item, whichever message named them.
    for key, cols in columns.items():
        item = by_key.get(key)
        if item is not None:
            merged = tuple(dict.fromkeys(tuple(cols) + item.required_columns))
            by_key[key] = replace(item, required_columns=merged)

    out.items = list(by_key.values())
    out.columns_stated = {k: tuple(v) for k, v in columns.items()}
    out.unmatched = unmatched
    out.period_from, out.period_to = period_from, period_to
    return out, per_message, period_note


def read(messages) -> dict:
    """The API shape: the merged proposal, plus what each message in the chain contributed."""
    parsed, per_message, period_note = from_messages(messages)
    d = parsed.to_dict()
    d["messages_read"] = per_message
    d["outbound_read"] = sum(1 for m in per_message if m["direction"] == "outbound")
    d["inbound_skipped"] = sum(1 for m in per_message if m["direction"] == "inbound")
    d["period_note"] = period_note
    return d
