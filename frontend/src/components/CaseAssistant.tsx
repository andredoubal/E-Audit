import { useCallback, useEffect, useRef, useState } from "react";
import { onAsk, onOpenAssistant } from "../ai/ask";
import {
  askAssistant, clearAssistant, getAssistant, type AssistantState,
} from "../api";
import { Sparkles } from "./Icon";

/** One conversation per case, reachable from every tab. */
export default function CaseAssistant({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const [d, setD] = useState<AssistantState | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    getAssistant(id).then(setD).catch(() => {});
  }, [id]);
  useEffect(() => { if (open) load(); }, [open, load]);

  // A challenge elsewhere on the case opens this panel with the question already written. The
  // auditor is looking at the row they dispute; making them retype it — and leaving the
  // assistant to guess which of forty rows is meant — is the version of this that helps nobody.
  useEffect(() => onOpenAssistant(() => setOpen(true)), []);

  useEffect(() => onAsk((question) => {
    setOpen(true);
    setQ(question);
    setTimeout(() => inputRef.current?.focus(), 60);
  }), []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [d?.messages.length]);

  const send = async (question: string, action = "") => {
    if (!question.trim() && !action) return;
    setBusy(true);
    setErr("");
    try {
      setD(await askAssistant(id, question.trim() || action, action));
      setQ("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not answer that.");
    } finally { setBusy(false); }
  };

  if (!open) {
    return (
      <button className="asst-fab" onClick={() => setOpen(true)}
              title="Ask about this case">
        <span className="ai-chip"><Sparkles size={13} /></span> Ask about this case
      </button>
    );
  }

  const msgs = d?.messages ?? [];
  const quick = (d?.actions ?? []).filter((a) => a.key !== "explain");

  return (
    <aside className="asst">
      <div className="asst-head">
        <span className="ai-chip"><Sparkles size={13} /></span>
        <b>Case assistant</b>
        <span className="sub">{id}</span>
        <button className="linklike" onClick={() => clearAssistant(id).then(setD)}>clear</button>
        <button className="asst-x" onClick={() => setOpen(false)} aria-label="Close">×</button>
      </div>

      <div className="asst-body">
        {!msgs.length && (
          <p className="detail-note" style={{ marginTop: 0 }}>
            Ask about this case, or pick one of the things below. Everything the assistant can
            do is on that list — it runs the application's own checks rather than analysis of
            its own, and every figure in an answer was computed before the sentence was
            written.
          </p>
        )}

        {msgs.map((m) => (
          <div className={"asst-msg " + m.role} key={m.seq}>
            {m.role === "assistant" && m.action && m.action !== "explain" && (
              <span className="pill status">{m.action.replace(/_/g, " ")}</span>
            )}
            <pre>{m.content}</pre>
            {m.did && <span className="asst-did">✓ {m.did}</span>}
          </div>
        ))}
        {busy && <p className="detail-note">Working…</p>}
        {err && <div className="callout warn">{err}</div>}
        <div ref={endRef} />
      </div>

      <div className="asst-foot">
        <div className="asst-quick">
          {quick.map((a) => (
            <button key={a.key} className="qchip" title={a.hint} disabled={busy}
                    onClick={() => send(a.label, a.key)}>
              {a.label}
            </button>
          ))}
        </div>
        <div className="asst-input">
          <input
            ref={inputRef}
            value={q}
            placeholder="Ask about this case…"
            disabled={busy}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(q); }}
          />
          <button className="btn" disabled={busy || !q.trim()} onClick={() => send(q)}>
            Ask
          </button>
        </div>
      </div>
    </aside>
  );
}
