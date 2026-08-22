import { useCallback, useEffect, useRef, useState } from "react";
import { getInstructions, saveInstructions, type CaseInstructions as Data } from "../api";

/** What the auditor wants the AI to keep in mind on this case.
 *
 *  Every case has something the tool cannot know: this group restructured mid-period, the
 *  letters should be plainer because the taxpayer is a sole trader, a previous round already
 *  dealt with the credit notes so stop raising them. Without somewhere to say it, the auditor
 *  says it again in every panel and loses it when they close the tab.
 *
 *  **It sits under the tabs, on all three modules, because it applies to all three.** A steer
 *  that lived on one page would be one the auditor believes is in force everywhere and is not,
 *  which is worse than not having it. Collapsed it is a single line, so a case with no
 *  instructions costs no attention; open, it says exactly which surfaces it reaches and which
 *  it deliberately does not.
 *
 *  **It steers wording, never arithmetic.** The panel says so, and it is true of the
 *  implementation rather than a promise: the text goes into the user turn beneath a system
 *  preamble it cannot reach, and every verifier still runs afterwards, so an instruction that
 *  tries to make the model state a figure produces a rejected draft, not a wrong number. */

/** Starting points, not a menu. Each is a real thing an auditor has to tell a tool that only
 *  ever sees this period's documents. */
const EXAMPLES = [
  {
    label: "Plainer language",
    text: "Write to this taxpayer in plain language — they are a small business with no tax "
      + "adviser. Avoid the phrase “economic activity” without explaining it.",
  },
  {
    label: "Context the file lacks",
    text: "The group restructured on 1 February; the second half of the period trades under a "
      + "different entity. Say where that could explain a difference rather than treating it "
      + "as unexplained.",
  },
  {
    label: "Already settled",
    text: "The credit-note treatment was agreed with this taxpayer in the prior period audit. "
      + "Do not re-open it, and do not put it in a letter.",
  },
  {
    label: "House style",
    text: "Keep letters to one page. Lead with what we need from them, not with what we found.",
  },
];

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

  const insert = (text: string) => {
    setDraft((cur) => (cur.trim() ? `${cur.trim()}\n\n${text}` : text));
    box.current?.focus();
  };

  // ---------------------------------------------------------------- collapsed
  if (!open) {
    const has = !!d.text.trim();
    return (
      <button className={"instrbar" + (has ? " set" : "") + (has && !d.enabled ? " off" : "")}
              onClick={() => setOpen(true)}>
        <span className="ai-chip">AI</span>
        <b>Instructions for this case</b>
        {has ? (
          <>
            <span className="instrbar-text">{d.text}</span>
            <span className={"pill " + (d.enabled ? "pri-low" : "status")}>
              {d.enabled ? "in force" : "paused"}
            </span>
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
        <span className="ai-chip">AI</span>
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

        <div className="instr-meta">
          <span className={"sub" + (over ? " over" : "")}>
            {draft.length.toLocaleString()} / {d.max_length.toLocaleString()}
          </span>
          <div className="instr-examples">
            {EXAMPLES.map((x) => (
              <button key={x.label} className="qchip" disabled={busy}
                      title={x.text} onClick={() => insert(x.text)}>
                + {x.label}
              </button>
            ))}
          </div>
        </div>

        <div className="row-actions">
          {/* "Re-apply" only when there is something to re-apply: with an empty box it read as
              a disabled button offering to repeat an action never taken. */}
          <button className="btn" disabled={busy || over || (!dirty && d.enabled)}
                  onClick={() => commit(draft, true)}>
            {busy ? "Saving…"
              : dirty || !d.text.trim() ? "Save instructions"
              : "Put back in force"}
          </button>
          {!!d.text.trim() && (
            <button className="linklike" disabled={busy}
                    onClick={() => commit(d.text, !d.enabled)}>
              {d.enabled ? "pause without deleting" : "put back in force"}
            </button>
          )}
          {!!d.text.trim() && (
            <button className="linklike danger" disabled={busy} onClick={() => commit("")}>
              clear
            </button>
          )}
          {saved && <span className="pill pri-low">Saved</span>}
          {dirty && !busy && <span className="sub">unsaved</span>}
        </div>

        <div className="instr-scope">
          <div>
            <h4>Applies to</h4>
            <ul>
              {d.applies_to.map((a) => <li key={a.key}>{a.label}</li>)}
            </ul>
          </div>
          <div>
            {/* Published, not buried in a tooltip. An auditor is entitled to know where their
                steer does *not* reach — and the reasons are the interesting part. */}
            <h4>Deliberately not</h4>
            <ul>
              {d.excluded.map((x) => (
                <li key={x.key}>
                  {x.label} — <i>{x.why}</i>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <p className="detail-note" style={{ marginBottom: 0 }}>
          This steers <b>wording and emphasis</b>. It cannot make the AI state a figure, change a
          verdict, or alter a test: every number is computed in Python before any sentence is
          written, and the existing checks still run over the draft afterwards. An instruction
          that asked for something they forbid produces a rejected draft, not a wrong number.
        </p>
      </div>
    </section>
  );
}
