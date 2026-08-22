import { useEffect, useRef, useState } from "react";
import type { ReportField } from "../api";

/** One field of the audit report, which the auditor can write themselves.
 *
 *  The template asks for rulings, for penalties, for a meeting date — judgements the tool has no
 *  business making. It marked them `[for the auditor to complete]` and then offered no way to
 *  complete them, which is a form you cannot fill in.
 *
 *  Two rules the interaction follows:
 *
 *  **What was replaced stays visible.** Overriding an engine-written value shows an "edited"
 *  mark and a way back to what the tool said. An override nobody can detect is not an override.
 *
 *  **Clearing the box reverts.** An empty save deletes the edit and the engine's own value comes
 *  back, which is what an auditor expects from emptying a field — not a blank report line. */
export default function EditableField({ field, onSave }: {
  field: ReportField;
  onSave: (key: string, value: string, original: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(field.value);
  const [busy, setBusy] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (!editing) setDraft(field.value); }, [field.value, editing]);
  useEffect(() => {
    if (editing) { box.current?.focus(); box.current?.setSelectionRange(9e6, 9e6); }
  }, [editing]);

  const gap = !field.held;
  const long = field.value.length > 90 || field.value.includes("\n");

  const commit = async (value: string) => {
    setBusy(true);
    try {
      // `original` is what the engine produced. Sent on every save so the first override
      // records it; the server ignores it once a row already remembers one.
      await onSave(field.key, value, field.edited ? field.original : field.value);
      setEditing(false);
    } finally { setBusy(false); }
  };

  if (editing) {
    return (
      <div className={"rfield editing" + (long ? " wide" : "")}>
        <span className="k">{field.label}</span>
        {field.note && <span className="rfield-note">{field.note}</span>}
        <textarea
          ref={box}
          className="rfield-input"
          rows={long ? 8 : 2}
          value={draft === field.value && gap ? "" : draft}
          placeholder={gap ? "Write this in your own words…" : ""}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") { setDraft(field.value); setEditing(false); }
            // Enter saves a one-line field; a long one needs the button, since newlines matter.
            if (e.key === "Enter" && !e.shiftKey && !long) { e.preventDefault(); commit(draft); }
          }}
        />
        <div className="rfield-actions">
          <button className="btn small" disabled={busy} onClick={() => commit(draft)}>
            {busy ? "Saving…" : "Save"}
          </button>
          <button className="linklike" disabled={busy}
                  onClick={() => { setDraft(field.value); setEditing(false); }}>
            cancel
          </button>
          {field.edited && (
            <button className="linklike" disabled={busy} onClick={() => commit("")}>
              restore what the engine wrote
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={"rfield" + (long ? " wide" : "") + (field.edited ? " edited" : "")}>
      <span className="k">
        {field.label}
        {field.edited && (
          <span className="rfield-tag" title={`Written by you${field.edited_at ? ` on ${field.edited_at.slice(0, 10)}` : ""}`}>
            yours
          </span>
        )}
      </span>
      <span className={"v" + (gap ? " gap" : "")}>{field.value}</span>
      <div className="rfield-actions">
        <button className="linklike" onClick={() => setEditing(true)}>
          {gap ? "fill this in" : "edit"}
        </button>
        {field.edited && field.original && (
          <button className="linklike" onClick={() => setShowOriginal((s) => !s)}>
            {showOriginal ? "hide" : "what it said before"}
          </button>
        )}
      </div>
      {showOriginal && field.original && (
        <pre className="rfield-original">{field.original}</pre>
      )}
    </div>
  );
}
