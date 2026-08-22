import { useEffect, useRef, useState } from "react";
import { saveLetter, type StepEmail } from "../api";
import VerifyBadge from "./VerifyBadge";
import { Sparkles } from "./Icon";

/** An outbound letter, as a draft the auditor actually edits. */
export default function LetterDraft({ id, email, onSaved }: {
  id: string;
  email: StepEmail;
  onSaved: (next: StepEmail[]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(email.text);
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (!editing) setDraft(email.text); }, [email.text, editing]);
  useEffect(() => { if (editing) box.current?.focus(); }, [editing]);

  const commit = async (body: string) => {
    setBusy(body ? "save" : "restore");
    setErr("");
    try {
      const next = await saveLetter(id, email.kind, body, email.generated ?? email.text);
      onSaved(next.emails);
      setEditing(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the letter.");
    } finally { setBusy(""); }
  };

  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">{email.edited ? "✎" : <Sparkles size={13} />}</span>
          <h2>{email.title}</h2>
        </div>
        <div className="chips">
          <span className="pill status" title="What caused this draft to exist">
            {email.trigger}
          </span>
          {email.edited ? (
            <span className="pill pri-low"
                  title="You rewrote this. The verifier's badge describes what it checked, and it never saw these words.">
              your wording
            </span>
          ) : (
            <VerifyBadge source={email.source === "none" ? null : (email.source as never)}
                         violations={email.violations} />
          )}
          {!editing && email.text && (
            <>
              <button className="btn small" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn small" onClick={() => {
                navigator.clipboard?.writeText(email.text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}>
                {copied ? "Copied" : "Copy"}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="panel-body">
        {err && <div className="callout warn">{err}</div>}

        {editing ? (
          <>
            <textarea className="letter-edit" rows={Math.min(30, draft.split("\n").length + 4)}
                      value={draft} disabled={!!busy}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Escape") setEditing(false); }} />
            <div className="row-actions">
              <button className="btn" disabled={!!busy || !draft.trim()}
                      onClick={() => commit(draft)}>
                {busy === "save" ? "Saving…" : "Save the letter"}
              </button>
              <button className="linklike" disabled={!!busy}
                      onClick={() => { setDraft(email.text); setEditing(false); }}>
                cancel
              </button>
              {email.edited && (
                <button className="linklike" disabled={!!busy} onClick={() => commit("")}>
                  {busy === "restore" ? "Restoring…" : "restore the generated draft"}
                </button>
              )}
            </div>
          </>
        ) : (
          <pre className="letterpre">{email.text}</pre>
        )}

        <p className="detail-note">
          {email.edited
            ? "These are your words, saved on the case. The draft the engine wrote is kept — "
              + "restore it from the edit view if you want to start again."
            : email.kind === "follow-up"
              ? "Written from the gaps alone — items already supplied in full are not repeated."
              : "Written from the findings you accepted, and from nothing else. Each amount is "
                + "stated once; where several statements describe one piece of evidence, the "
                + "others follow without repeating the figure."}
        </p>
      </div>
    </div>
  );
}
