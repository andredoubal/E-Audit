import { useEffect, useState } from "react";
import { getThreads, openThread, recordReply, type ThreadState } from "../api";

const WHO: Record<string, string> = {
  auditor: "written by the auditor",
  "ai-assisted": "drafted with AI, edited by the auditor",
  "ai-drafted": "AI draft — review before sending",
  taxpayer: "the taxpayer's own words",
};

const ORIGIN: Record<string, string> = {
  initial: "Opening request",
  "investigation-request": "Raised by the investigation",
  clarification: "Clarification",
};

/** Everything said to the taxpayer and back, oldest first. */
export default function ThreadTrail({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged?: () => void;
}) {
  const [d, setD] = useState<ThreadState | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => { getThreads(id).then(setD).catch(() => {}); };
  useEffect(load, [id, rev]);

  const submitReply = async () => {
    if (!reply.trim()) return;
    setBusy(true);
    try {
      setD(await recordReply(id, reply.trim()));
      setReply("");
      onChanged?.();
    } catch {
      /* the trail keeps its last good state rather than blanking */
    } finally {
      setBusy(false);
    }
  };

  const newThread = async () => {
    setBusy(true);
    try {
      setD(await openThread(id, ""));
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  if (!d) return null;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Correspondence with the taxpayer</h2>
        <span className="muted">
          {d.threads.length} enquir{d.threads.length === 1 ? "y" : "ies"} ·{" "}
          {d.open_thread_id ? "one open" : "none open"}
        </span>
      </div>
      <div className="panel-body">
        {!d.threads.length && (
          <p className="detail-note" style={{ marginTop: 0 }}>
            Nothing has been sent yet. Record the request you sent below, or ask the
            investigation to raise one when it cannot settle a hypothesis.
          </p>
        )}

        {d.retestable.length > 0 && (
          <div className="callout ok">
            <b>New evidence has arrived.</b>{" "}
            {d.retestable.length} hypothes{d.retestable.length === 1 ? "is" : "es"} parked
            waiting on the taxpayer can now be re-tested — re-run the investigation to settle
            {d.retestable.length === 1 ? " it" : " them"}.
            <ul className="conf-list" style={{ marginTop: 7 }}>
              {d.retestable.map((r) => (
                <li key={r.hypothesis_id}>
                  <b>{r.hypothesis_id}</b>
                  <span className="sub">
                    {r.note || r.claim} · answered by {r.documents.join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {d.missing_attachments?.map((m) => (
          <div className="callout warn" key={`${m.thread_id}-${m.message_seq}`}>
            <b>Enquiry {m.thread_seq}: a reply mentions an attachment, and none is filed.</b>{" "}
            {m.detail} Check the email it came from before chasing it.
          </div>
        ))}

        {d.threads.map((t) => {
          const isOpen = open === t.id || t.status === "open";
          return (
            <div className={"thread" + (t.status === "open" ? " live" : "")} key={t.id}>
              <button className="thread-head" onClick={() => setOpen(isOpen ? -1 : t.id)}>
                <span className="thread-seq">{t.seq}</span>
                <span className="thread-subj">
                  {t.subject}
                  <span className="sub">
                    {ORIGIN[t.origin] || t.origin}
                    {t.origin_hypothesis_id && ` · ${t.origin_hypothesis_id}`}
                    {" · "}
                    {t.messages.length} message{t.messages.length === 1 ? "" : "s"}
                    {t.documents.length > 0 && ` · ${t.documents.length} document${t.documents.length === 1 ? "" : "s"}`}
                  </span>
                </span>
                <span className={"pill " + (t.status === "open" ? "pri-low" : "status")}>
                  {t.status}
                </span>
              </button>

              {isOpen && (
                <div className="thread-body">
                  {t.messages.map((m) => (
                    <div className={"msg msg-" + m.direction} key={m.seq}>
                      <div className="msg-meta">
                        <b>{m.direction === "outbound" ? m.sender : m.sender}</b>
                        <span className="sub">
                          → {m.recipient} · {WHO[m.drafted_by] || m.drafted_by}
                          {m.created_at && ` · ${m.created_at.slice(0, 10)}`}
                        </span>
                      </div>
                      <pre className="letterpre">{m.body}</pre>
                    </div>
                  ))}
                  {!t.messages.length && (
                    <p className="detail-note" style={{ margin: 0 }}>
                      No message recorded on this enquiry yet.
                    </p>
                  )}
                  {t.documents.length > 0 && (
                    <div className="doclist">
                      {t.documents.map((doc) => (
                        <div className="docrow" key={doc.id}>
                          <b>{doc.filename}</b>
                          <span className="sub">
                            {doc.rows} rows · {doc.columns} columns
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        <div className="resp-form" style={{ marginTop: 14 }}>
          <textarea
            className="letter-input"
            rows={3}
            placeholder="Paste what the taxpayer wrote back — kept verbatim, and recorded as theirs"
            value={reply}
            onChange={(e) => setReply(e.target.value)}
          />
          <div className="resp-actions">
            <button className="btn" onClick={submitReply} disabled={!reply.trim() || busy}>
              {busy ? "Recording…" : "Record their reply"}
            </button>
            <button className="linklike" onClick={newThread} disabled={busy}>
              start a new enquiry
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
