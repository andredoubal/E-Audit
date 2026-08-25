import { useCallback, useEffect, useRef, useState } from "react";
import { getInstructions, saveInstructions, type CaseInstructions as Data } from "../api";
import { closePanels, onPanel } from "../ai/ask";

/** What the auditor wants the AI to keep in mind on this case.
 *
 *  A slide-over rather than a panel in the page: it is a property of the *case*, not of the
 *  module you happen to be reading, and it is written once and then left alone. Saving is on
 *  blur — there is one field, and a Save button next to one field is a step that exists only
 *  to be forgotten.
 */
export default function CaseInstructions({ id }: { id: string }) {
  const [d, setD] = useState<Data | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [err, setErr] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(() => {
    getInstructions(id).then((s) => { setD(s); setDraft(s.text); }).catch(() => {});
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => onPanel((p) => setOpen(p === "instr")), []);
  useEffect(() => { if (open) box.current?.focus(); }, [open]);

  const commit = async (text: string) => {
    if (!d || text.trim() === d.text.trim()) return;
    setErr("");
    try {
      const next = await saveInstructions(id, text, d.enabled);
      setD(next);
      setDraft(next.text);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the instructions.");
    }
  };

  if (!d || !open) return null;

  const over = draft.length > d.max_length;

  return (
    <aside className="slideover">
      <div className="slideover-head">
        <b>Case instructions</b>
        <span className="sub">applied to every module</span>
        <button className="slideover-x" onClick={closePanels} aria-label="Close">×</button>
      </div>

      <div className="slideover-body">
        {err && <div className="callout warn">{err}</div>}
        <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, color: "var(--muted)" }}>
          What the AI should know about this case that the documents do not say — context,
          house style, what not to raise.
        </p>
        <textarea
          ref={box}
          className="instr-input"
          rows={12}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => { if (e.key === "Escape") { setDraft(d.text); closePanels(); } }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
          <button className="btn-ghost" onClick={() => { setDraft(""); commit(""); }}>
            Clear
          </button>
          <span className="sub" style={{ color: over ? "var(--high)" : "var(--fainter)" }}>
            {draft.length.toLocaleString()} / {d.max_length.toLocaleString()}
          </span>
        </div>
      </div>

      <div className="slideover-foot">
        <p>
          Steers wording and emphasis. It cannot state a figure, change a verdict, or alter a
          test — every number is computed before any sentence is written.
        </p>
      </div>
    </aside>
  );
}
