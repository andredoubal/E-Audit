import { useState } from "react";
import type { AuditorDecisionView, DecisionKind } from "../api";

/** The auditor's ruling on one hypothesis. The AI proposed it; this is where a person decides.
 *
 *  Only `accepted` reaches the report. The rest are recorded rather than discarded, because
 *  what was ruled out and why is as much a part of the audit file as what was upheld — and
 *  because an auditor reopening the case in a month needs to see the question was answered. */
const OPTIONS: { key: DecisionKind; label: string; hint: string }[] = [
  { key: "accepted", label: "Accept", hint: "Confirm as a finding — this reaches the report" },
  { key: "rejected", label: "Reject", hint: "Not supported; kept on file with your reason" },
  { key: "needs-more-investigation", label: "Investigate further", hint: "Not settled yet" },
  { key: "needs-more-info", label: "Need taxpayer info", hint: "Cannot be resolved from what is on file" },
  { key: "irrelevant", label: "Not relevant", hint: "Out of scope for this audit" },
];

const DECIDED_CLASS: Record<DecisionKind, string> = {
  accepted: "pri-low",
  rejected: "status",
  "needs-more-investigation": "pri-medium",
  "needs-more-info": "pri-medium",
  irrelevant: "status",
};

export default function DecisionControls({
  decision,
  busy,
  onDecide,
}: {
  decision: AuditorDecisionView | null;
  busy: boolean;
  onDecide: (d: DecisionKind, comment: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<DecisionKind | null>(null);
  const [comment, setComment] = useState("");

  const submit = () => {
    if (!picked) return;
    onDecide(picked, comment.trim());
    setOpen(false);
    setPicked(null);
    setComment("");
  };

  if (decision && !open) {
    const label = OPTIONS.find((o) => o.key === decision.decision)?.label ?? decision.decision;
    return (
      <div className="decision">
        <span className={"pill " + DECIDED_CLASS[decision.decision]}>{label} by the auditor</span>
        {decision.needs_reconfirmation && (
          <div className="callout warn" style={{ margin: "8px 0 0" }}>
            <b>Re-confirm this.</b> The verdict moved after you decided — your ruling was made
            against <code>{decision.decided_on_status}</code>.
          </div>
        )}
        {decision.comment && <div className="sub decision-note">“{decision.comment}”</div>}
        <button className="linklike" onClick={() => setOpen(true)} disabled={busy}>
          change
        </button>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="decision">
        <button className="btn-ghost" onClick={() => setOpen(true)} disabled={busy}>
          Record your decision
        </button>
      </div>
    );
  }

  return (
    <div className="decision open">
      <div className="decision-opts">
        {OPTIONS.map((o) => (
          <button
            key={o.key}
            className={"btn-ghost" + (picked === o.key ? " confirm" : "")}
            title={o.hint}
            onClick={() => setPicked(o.key)}
          >
            {o.label}
          </button>
        ))}
      </div>
      {picked && <div className="sub">{OPTIONS.find((o) => o.key === picked)?.hint}</div>}
      <input
        className="decision-comment"
        placeholder="Your reasoning (recorded on the case file)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <div className="resp-actions">
        <button className="btn" onClick={submit} disabled={!picked || busy}>
          {busy ? "Saving…" : "Save decision"}
        </button>
        <button className="linklike" onClick={() => setOpen(false)} disabled={busy}>
          cancel
        </button>
      </div>
    </div>
  );
}
