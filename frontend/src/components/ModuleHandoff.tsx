import { useState } from "react";
import { useNavigate } from "react-router-dom";

/** The end of a module: what carries forward, and the one control that takes you there.
 *
 *  An auditor finishing a module had no way to say so — they navigated by the rail and hoped
 *  the next module had noticed. This states what is being handed over, in the engine's own
 *  counts, and performs whatever actually has to happen before the next module is right.
 *
 *  It confirms a handoff, not a figure. Nothing here decides a matter or computes an amount:
 *  the rulings are made above it, and this says what they come to before you act on them —
 *  which is also why the line is stated even when it is "nothing confirmed yet". A button that
 *  moved you on without saying what it was carrying would be the one place in this application
 *  where the auditor could not see what they had just agreed to. */
export default function ModuleHandoff({ label, to, carries, caution, onConfirm }: {
  label: string;
  to: string;
  /** What goes forward, in counts the engine computed. */
  carries: string;
  /** What the button will do, and anything the auditor should know before it does. */
  caution?: string;
  /** The real work, if the handoff has any. Navigation waits on it, and does not happen if
   *  it fails — a failed handoff must not look like a successful one. */
  onConfirm?: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const nav = useNavigate();

  const go = async () => {
    setBusy(true);
    setErr("");
    try {
      if (onConfirm) await onConfirm();
      nav(to);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not complete that.");
      setBusy(false);
    }
  };

  return (
    <div className="handoff">
      {err && <div className="callout warn">{err}</div>}
      <div className="handoff-row">
        <div className="handoff-what">
          <b>{carries}</b>
          {caution && <span className="sub">{caution}</span>}
        </div>
        <button className="btn handoff-go" disabled={busy} onClick={go}>
          {busy ? "Working…" : label}
          <span aria-hidden="true"> →</span>
        </button>
      </div>
    </div>
  );
}
