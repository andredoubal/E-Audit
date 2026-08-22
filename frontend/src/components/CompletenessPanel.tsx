import { useState } from "react";
import { type Assessment, type ItemState, type LoopState } from "../api";

const ORDER: ItemState[] = ["missing", "incomplete", "needs-review", "received"];

const PILL: Record<ItemState, string> = {
  missing: "pri-high",
  incomplete: "pri-high",
  "needs-review": "pri-medium",
  received: "pri-low",
};

/** What each word commits the auditor to, said once at the top rather than implied by a colour. */
const MEANS: Record<ItemState, string> = {
  missing: "Nothing has been supplied for this item.",
  incomplete: "It arrived, and a check it has to pass failed. This is what a chase letter is for.",
  "needs-review":
    "It arrived, and the checks cannot settle it. Your judgement, not a letter.",
  received: "It arrived and passes every check that can be run on it.",
};

/** Requested versus received, in four words rather than nine gap kinds across two severities.
 *
 *  The gap list below this panel is still the detail — this is the same rows answering the
 *  question an auditor actually asks, which is "what is still outstanding". Nothing here is
 *  stored: the states are derived from the current gaps every time, so a fixed gap changes the
 *  word with no state to reconcile. */
export default function CompletenessPanel({ loop }: { loop: LoopState | null }) {
  const [open, setOpen] = useState<ItemState | null>(null);

  const a: Assessment | undefined = loop?.assessment;
  if (!a || !a.items.length) return null;

  const shown = open ? a.items.filter((i) => i.state === open) : a.items;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Requested versus received</h2>
        <span className="muted">
          round {loop?.round} · {a.items.length} item{a.items.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="panel-body">
        <div className="statebar">
          {ORDER.map((s) => (
            <button
              key={s}
              className={"statechip " + PILL[s] + (open === s ? " on" : "")}
              onClick={() => setOpen(open === s ? null : s)}
              disabled={!a.summary[s]}
              title={MEANS[s]}
            >
              <b>{a.summary[s] ?? 0}</b>
              <span>
                {s === "needs-review"
                  ? "need review"
                  : s === "received"
                    ? "received"
                    : s}
              </span>
            </button>
          ))}
        </div>
        {open && <p className="detail-note" style={{ marginTop: 0 }}>{MEANS[open]}</p>}

        <div className="assesslist">
          {shown.map((i) => (
            <div className={"assessrow " + i.state} key={`${i.request_item_id}-${i.label}`}>
              <span className={"pill " + PILL[i.state]}>{i.state_label}</span>
              <div>
                <b>{i.label}</b>
                {i.reason && <p>{i.reason}</p>}
                {!!i.documents.length && i.documents.join(", ") !== i.label && (
                  <small className="mono">{i.documents.join(", ")}</small>
                )}
              </div>
            </div>
          ))}
        </div>

        <p className="detail-note">
          <b>Incomplete</b> is the taxpayer's to fix; <b>needs review</b> is yours to settle. The
          difference matters because a chase letter written from the second asks for something
          that was already sent.
        </p>
      </div>
    </div>
  );
}
