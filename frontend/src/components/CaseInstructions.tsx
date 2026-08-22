import { useCallback, useEffect, useRef, useState } from "react";
import { getInstructions, saveInstructions, type CaseInstructions as Data } from "../api";
import { Sparkles } from "./Icon";

/** What the auditor wants the AI to keep in mind on this case. */

export default function CaseInstructions({ id }: { id: string }) {
  const [d, setD] = useState<Data | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(() => {
    getInstructions(id).then((s) => { setD(s); setDraft(s.text); }).catch(() => {});
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => { if (open) box.current?.focus(); }, [open]);

  if (!d) return null;

  const dirty = draft.trim() !== d.text.trim();
  const over = draft.length > d.max_length;

  const commit = async (text: string, enabled = d.enabled) => {
    setBusy(true);
    setErr("");
    try {
      const next = await saveInstructions(id, text, enabled);
      setD(next);
      setDraft(next.text);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      if (!text.trim()) setOpen(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the instructions.");
    } finally { setBusy(false); }
  };

  // ---------------------------------------------------------------- collapsed
  if (!open) {
    const has = !!d.text.trim();
    return (
      <button className={"instrbar" + (has ? " set" : "")}
              onClick={() => setOpen(true)}>
        <span className="ai-chip"><Sparkles size={13} /></span>
        <b>Instructions for this case</b>
        {has ? (
          <>
            <span className="instrbar-text">{d.text}</span>
            <span className="pill pri-low">in force</span>
          </>
        ) : (
          <span className="instrbar-empty">
            Tell the AI what it cannot see in the documents — context, house style, what not to
            raise. It applies to every module of this case.
          </span>
        )}
        <span className="instrbar-open">{has ? "Edit" : "Add"}</span>
      </button>
    );
  }

  // ------------------------------------------------------------------ expanded
  return (
    <section className="instr">
      <div className="instr-head">
        <span className="ai-chip"><Sparkles size={13} /></span>
        <b>Instructions for this case</b>
        <span className="sub">
          Applied to every module — {d.updated_at
            ? `last changed ${d.updated_at.slice(0, 10)}`
            : "nothing written yet"}
        </span>
        <button className="asst-x" onClick={() => { setDraft(d.text); setOpen(false); }}
                aria-label="Close">×</button>
      </div>

      <div className="instr-body">
        {err && <div className="callout warn">{err}</div>}

        <textarea
          ref={box}
          className="instr-input"
          rows={7}
          value={draft}
          disabled={busy}
          placeholder={"What should the AI know about this case that the documents do not say?\n\n"
            + "e.g. “The group restructured on 1 February — say where that could explain a "
            + "difference rather than calling it unexplained.”"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { setDraft(d.text); setOpen(false); } }}
        />

        <div className="row-actions">
          <button className="btn" disabled={busy || over || !dirty}
                  onClick={() => commit(draft)}>
            {busy ? "Saving…" : "Save instructions"}
          </button>
          {!!d.text.trim() && (
            <button className="linklike danger" disabled={busy} onClick={() => commit("")}>
              Clear
            </button>
          )}
          <span className={"sub" + (over ? " over" : "")}>
            {draft.length.toLocaleString()} / {d.max_length.toLocaleString()}
          </span>
          {saved && <span className="pill pri-low">Saved</span>}
          {dirty && !busy && <span className="sub">unsaved</span>}
        </div>

        <p className="detail-note" style={{ marginBottom: 0 }}>
          This steers <b>wording and emphasis</b> across all three modules. It cannot make the AI
          state a figure, change a verdict, or alter a test — every number is computed in Python
          before any sentence is written.
        </p>
      </div>
    </section>
  );
}
