import { useCallback, useEffect, useState } from "react";
import AuditorAssessment from "./AuditorAssessment";
import ModuleHandoff from "./ModuleHandoff";

const sar = (n: number) =>
  "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

interface Hypothesis {
  hypothesis_id: string;
  agent: string;
  claim: string;
  why: string;
  outcome_code: string;
  status: string;
  amount: number;
  explanation: string;
  confidence: { score: number; band: string };
  regulatory?: { state: string; label: string; establishes: string };
  decision: { decision: string; comment: string; decided_at: string;
              needs_reconfirmation: boolean } | null;
}

interface AuditorFinding {
  seq: number;
  statement: string;
  outcome_code: string;
  amount: number;
  note: string;
  basis: string;
}

// ------------------------------------------------------------------ the auditor's own findings
/** A finding the auditor wrote, with no agent hypothesis behind it.
 *
 *  The roster covers what it has tests for. An auditor who sees something no test reaches must
 *  still be able to put it on the file — and it has to stay distinguishable in the report from
 *  anything a model proposed, which is why it is its own row rather than a synthetic hypothesis
 *  wearing an agent's name. */
function OwnFinding({ f, onSave, onRemove, busy }: {
  f: AuditorFinding;
  onSave: (seq: number, patch: Partial<AuditorFinding>) => void;
  onRemove: (seq: number) => void;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [statement, setStatement] = useState(f.statement);
  const [amount, setAmount] = useState(String(f.amount || ""));
  const [note, setNote] = useState(f.note);

  useEffect(() => {
    setStatement(f.statement);
    setAmount(String(f.amount || ""));
    setNote(f.note);
  }, [f.statement, f.amount, f.note]);

  if (editing) {
    return (
      <div className="afrow editing">
        <textarea value={statement} rows={3}
                  onChange={(e) => setStatement(e.target.value)}
                  placeholder="What you found, in your own words" />
        <div className="afrow-fields">
          <label>
            Amount (SAR)
            <input className="num" value={amount} inputMode="decimal"
                   onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="grow">
            Note
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
        <div className="afrow-acts">
          <button className="btn primary" disabled={busy || !statement.trim()}
                  onClick={() => {
                    onSave(f.seq, { statement: statement.trim(),
                                    amount: Number(amount) || 0, note: note.trim() });
                    setEditing(false);
                  }}>
            Save
          </button>
          <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <div className="afrow">
      <div className="afrow-main">
        <p className="afrow-st">{f.statement}</p>
        {f.note && <p className="afrow-note">{f.note}</p>}
      </div>
      <div className="afrow-amt num">{f.amount ? sar(f.amount) : <span className="muted">no amount</span>}</div>
      <div className="afrow-acts">
        <button className="btn sm" onClick={() => setEditing(true)}>Edit</button>
        <button className="btn sm" disabled={busy} onClick={() => onRemove(f.seq)}>Remove</button>
      </div>
    </div>
  );
}

function AddFinding({ onAdd, busy }: { onAdd: (f: Partial<AuditorFinding>) => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const [statement, setStatement] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  if (!open) {
    return (
      <button className="btn" onClick={() => setOpen(true)}>+ Add a finding of your own</button>
    );
  }
  return (
    <div className="afrow editing">
      <textarea rows={3} value={statement} autoFocus
                onChange={(e) => setStatement(e.target.value)}
                placeholder="What you found, in your own words" />
      <div className="afrow-fields">
        <label>
          Amount (SAR)
          <input className="num" value={amount} inputMode="decimal"
                 onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label className="grow">
          Note
          <input value={note} onChange={(e) => setNote(e.target.value)}
                 placeholder="optional — what it rests on" />
        </label>
      </div>
      <div className="afrow-acts">
        <button className="btn primary" disabled={busy || !statement.trim()}
                onClick={() => {
                  onAdd({ statement: statement.trim(), amount: Number(amount) || 0,
                          note: note.trim() });
                  setStatement(""); setAmount(""); setNote(""); setOpen(false);
                }}>
          Add
        </button>
        <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the tab
/** Tab 4 — what the auditor has decided, and the only tab the audit report reads.
 *
 *  Two kinds of row sit here and are never merged: the AI findings the auditor confirmed, which
 *  carry the agent that proposed them and the evidence it was settled on, and findings the
 *  auditor wrote themselves. The report records which is which, so a reader can tell a
 *  confirmed machine proposal from an auditor's own observation.
 *
 *  Nothing here computes. The amounts are the engine's, carried through unchanged; the words
 *  are the auditor's. */
export default function AuditorFindingsTab({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged: () => void;
}) {
  const [hyps, setHyps] = useState<Hypothesis[] | null>(null);
  const [own, setOwn] = useState<AuditorFinding[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    fetch(`/api/cases/${id}/investigation`)
      .then((r) => r.json())
      .then((j) => setHyps(j.hypotheses ?? []))
      .catch(() => setHyps([]));
    fetch(`/api/cases/${id}/auditor-findings`)
      .then((r) => r.json())
      .then(setOwn)
      .catch(() => setOwn([]));
  }, [id]);
  useEffect(load, [load, rev]);

  const call = async (path: string, init: RequestInit) => {
    setBusy(true);
    try {
      await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
      load();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const accepted = (hyps ?? []).filter((h) => h.decision?.decision === "accepted");
  const reconfirm = accepted.filter((h) => h.decision?.needs_reconfirmation);
  const undecided = (hyps ?? []).filter(
    (h) => !h.decision && h.status !== "refuted" && h.outcome_code);
  const total = accepted.reduce((n, h) => n + Math.abs(h.amount), 0)
    + own.reduce((n, f) => n + Math.abs(f.amount), 0);

  return (
    <>
      <div className="panel">
        <div className="panel-head">
          <h2>Confirmed findings</h2>
          <span className="sub num">
            {accepted.length + own.length} confirmed
            {total ? ` · ${sar(total)}` : ""}
          </span>
        </div>

        {!!reconfirm.length && (
          <div className="notice warn">
            {reconfirm.length} finding(s) you accepted have been contradicted by a later run.
            Your acceptance was not overwritten — re-confirm it on the AI Findings tab, or
            withdraw it.
          </div>
        )}

        {accepted.length === 0 && own.length === 0 ? (
          <p className="muted">
            Nothing is confirmed yet. The audit report will record that no finding was
            established — which is the correct outcome until you confirm one, since what an
            agent proposes is not what the audit concludes.
            {undecided.length > 0 &&
              ` ${undecided.length} matter(s) are waiting for your decision on the AI Findings tab.`}
          </p>
        ) : (
          <div className="aflist">
            {accepted.map((h) => (
              <div className="afrow confirmed" key={h.hypothesis_id}>
                <div className="afrow-main">
                  <div className="afrow-src">
                    <span className="pill sm teal">confirmed AI finding</span>
                    <span className="mono xs">{h.hypothesis_id}</span>
                    <span className="xs muted">{h.agent}</span>
                    {h.confidence?.band && (
                      <span className="xs muted">confidence: {h.confidence.band}</span>
                    )}
                  </div>
                  <p className="afrow-st">{h.explanation || h.claim}</p>
                  {h.regulatory?.state === "found" && (
                    <p className="afrow-note">
                      <b>{h.regulatory.label}</b> — {h.regulatory.establishes}
                    </p>
                  )}
                  {h.decision?.comment && <p className="afrow-note">{h.decision.comment}</p>}
                </div>
                <div className="afrow-amt num">
                  {h.amount ? sar(h.amount) : <span className="muted">no amount</span>}
                </div>
                <div className="afrow-acts">
                  <button className="btn sm" disabled={busy}
                          onClick={() => call(`/api/cases/${id}/hypotheses/${h.hypothesis_id}/decision`,
                                              { method: "DELETE" })}>
                    Withdraw
                  </button>
                </div>
              </div>
            ))}

            {own.map((f) => (
              <div key={f.seq}>
                <div className="afrow-src" style={{ padding: "0 0 4px" }}>
                  <span className="pill sm">your own finding</span>
                </div>
                <OwnFinding
                  f={f} busy={busy}
                  onSave={(seq, patch) =>
                    call(`/api/cases/${id}/auditor-findings/${seq}`,
                         { method: "PATCH", body: JSON.stringify(patch) })}
                  onRemove={(seq) =>
                    call(`/api/cases/${id}/auditor-findings/${seq}`, { method: "DELETE" })}
                />
              </div>
            ))}
          </div>
        )}

        <div className="afadd">
          <AddFinding busy={busy}
                      onAdd={(f) => call(`/api/cases/${id}/auditor-findings`,
                                         { method: "POST", body: JSON.stringify(f) })} />
        </div>

        <div className="panel-note">
          <span className="ct">yours to sign</span> Only what appears here reaches the audit
          report and the outcome letter. A finding an agent proposed and you have not confirmed
          is not in the audit&rsquo;s conclusions, and the report says so rather than quietly
          including it.
        </div>
      </div>

      {/* The auditor's own conclusion over the whole investigation — one position, drafted from
          what the engine settled and then owned by the person who signs it. */}
      <AuditorAssessment id={id} rev={rev} onChanged={onChanged} part="assessment" />

      {/* The handoff states what it is carrying, in the engine's own counts, before you press
          it — including the case that earns the rule: nothing confirmed, and the report will
          then record that no finding was established. */}
      <ModuleHandoff
        label="Confirm and draft audit report"
        to={`/cases/${id}/report`}
        carries={
          accepted.length + own.length === 0
            ? "Nothing confirmed yet"
            : `${accepted.length + own.length} finding(s) confirmed`
              + (total ? ` · ${sar(total)}` : "")
        }
        caution={
          accepted.length + own.length === 0
            ? "The audit report will record that no finding was established."
            : undecided.length
              ? `${undecided.length} matter(s) are still undecided and will not be carried forward.`
              : undefined
        }
      />
    </>
  );
}
