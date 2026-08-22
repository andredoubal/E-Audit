import { useCallback, useEffect, useRef, useState } from "react";
import {
  getFollowup,
  parseRequestEmail,
  recordReply,
  uploadDocument,
  uploadEmail,
  type Assessment,
  type CorrespondenceThread,
  type Draft,
  type ItemState,
  type ParsedRequest,
} from "../api";

const ORIGIN: Record<string, string> = {
  initial: "Opening request",
  "investigation-request": "Raised by the investigation",
  clarification: "Clarification",
};

const WHO: Record<string, string> = {
  auditor: "written by the auditor",
  "ai-assisted": "drafted with AI, edited by the auditor",
  "ai-drafted": "AI draft — review before sending",
  taxpayer: "the taxpayer's own words",
};

const STATE_ORDER: ItemState[] = ["missing", "incomplete", "needs-review", "received"];
const STATE_PILL: Record<ItemState, string> = {
  missing: "pri-high",
  incomplete: "pri-high",
  "needs-review": "pri-medium",
  received: "pri-low",
};

const SAMPLE = `Dear Sir/Madam,

Further to our review of your VAT position for Q1 2025, please provide the following
within 20 working days:

1. A detailed sales analysis for the period, with the following columns: invoice date,
   invoice number, customer name, customer VAT number, description, taxable amount,
   VAT rate and VAT amount.
2. A detailed purchases analysis on which input VAT was claimed.
3. The trial balance as at 31 March 2025.
4. Copies of the tax invoices for the ten largest purchases.

Yours faithfully,
Zakat, Tax and Customs Authority`;

function Step({ n, title, note, children }: {
  n: number;
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rstep">
      <div className="rstep-head">
        <span className="rstep-n">{n}</span>
        <h3>{title}</h3>
        {note && <span className="sub">{note}</span>}
      </div>
      <div className="rstep-body">{children}</div>
    </section>
  );
}

/** One round of correspondence, in the order it actually happens.
 *
 *  The email chain goes out, documents come back, the two are compared, and whatever is still
 *  missing becomes the next email. Anything that does not sit at one of those four points does
 *  not belong on this page — an auditor working a round should never have to ask which panel
 *  they are supposed to be looking at.
 *
 *  Later rounds exist only because the investigation asked for one. That is the whole loop:
 *  round 1 is the opening request, and a round 2 means the evidence could not settle something,
 *  so the case went back to the taxpayer. */
export default function RoundCard({
  id,
  thread,
  seq,
  assessment,
  hasFormalRequest,
  onChanged,
}: {
  id: string;
  thread: CorrespondenceThread | null;
  seq: number;
  assessment?: Assessment;
  hasFormalRequest: boolean;
  onChanged: () => void;
}) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedRequest | null>(null);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const [followup, setFollowup] = useState<Draft | null>(null);
  const [filter, setFilter] = useState<ItemState | null>(null);
  const [copied, setCopied] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const [filed, setFiled] = useState<string[]>([]);

  const docs = thread?.documents ?? [];
  const messages = thread?.messages ?? [];
  const rows = assessment?.items ?? [];
  // A round is not one pass. The chase goes out, they reply with more files, and
  // steps 3 and 4 recompute against everything on the round.
  const exchanges = messages.length;
  const outstanding = rows.filter((r) => r.state !== "received").length;

  const loadFollowup = useCallback(() => {
    if (!outstanding) { setFollowup(null); return; }
    getFollowup(id).then(setFollowup).catch(() => setFollowup(null));
  }, [id, outstanding]);
  useEffect(loadFollowup, [loadFollowup]);

  const readEmail = async () => {
    if (!text.trim()) return;
    setBusy("read");
    setErr("");
    setConfirmed(false);
    try {
      const p = await parseRequestEmail(id, text);
      setParsed(p);
      setKeep(new Set(p.items.map((i) => i.key)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read that email.");
    } finally { setBusy(""); }
  };

  const fileChain = async () => {
    if (!text.trim()) return;
    setBusy("file");
    try {
      await recordReply(id, text.trim());
      setText("");
      setParsed(null);
      onChanged();
    } finally { setBusy(""); }
  };

  const sendEmail = async (f: File | null) => {
    if (!f) return;
    setBusy("email");
    setErr("");
    try {
      const r = await uploadEmail(id, f);
      setFiled(r.filed);
      onChanged();
      loadFollowup();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read that email.");
    } finally { setBusy(""); }
  };

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy("upload");
    setErr("");
    try {
      for (const f of Array.from(files)) await uploadDocument(id, f);
      onChanged();
      loadFollowup();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally { setBusy(""); }
  };

  const shown = filter ? rows.filter((r) => r.state === filter) : rows;

  return (
    <div className={"roundcard" + (thread?.status === "open" ? " live" : "")}>
      <div className="round-head">
        <span className="round-n">Round {seq}</span>
        <span className="round-origin">
          {ORIGIN[thread?.origin ?? "initial"] || thread?.origin}
          {thread?.origin_hypothesis_id && (
            <span className="mono"> · {thread.origin_hypothesis_id}</span>
          )}
        </span>
        {exchanges > 1 && (
          <span className="pill status" title="Each reply and each chase is an exchange. The round stays open until nothing is outstanding.">
            {exchanges} exchanges
          </span>
        )}
        <span className={"pill " + (thread?.status === "open" ? "pri-low" : "status")}>
          {thread?.status ?? "not started"}
        </span>
      </div>

      {err && <div className="callout warn">{err}</div>}

      {/* ------------------------------------------------------- 1 · the email chain */}
      <Step n={1} title="The email chain"
            note={messages.length ? `${messages.length} message${messages.length === 1 ? "" : "s"}` : "nothing sent yet"}>
        {messages.map((m) => (
          <div className={"msg msg-" + m.direction} key={m.seq}>
            <div className="msg-meta">
              <b>{m.sender}</b>
              <span className="sub">
                → {m.recipient} · {WHO[m.drafted_by] || m.drafted_by}
                {m.created_at && ` · ${m.created_at.slice(0, 10)}`}
              </span>
            </div>
            <pre className="letterpre">{m.body}</pre>
          </div>
        ))}

        <textarea
          className="letter-input"
          rows={messages.length ? 4 : 8}
          value={text}
          placeholder="Paste the email chain — what you sent, and anything the taxpayer wrote back."
          onChange={(e) => setText(e.target.value)}
        />
        <div className="row-actions">
          <button className="btn" disabled={!!busy || !text.trim()} onClick={fileChain}>
            {busy === "file" ? "Filing…" : "Add to the chain"}
          </button>
          <button className="btn ghost" disabled={!!busy || !text.trim()} onClick={readEmail}>
            {busy === "read" ? "Reading…" : "Read what was asked for"}
          </button>
          <button className="linklike" disabled={!!busy}
                  onClick={() => emailRef.current?.click()}>
            {busy === "email" ? "Reading the email…" : "or drop in an .eml / .msg file"}
          </button>
          <input ref={emailRef} type="file" accept=".eml,.msg" style={{ display: "none" }}
                 onChange={(e) => sendEmail(e.target.files?.[0] ?? null)} />
          {!messages.length && !text && (
            <button className="linklike" onClick={() => setText(SAMPLE)}>use a sample</button>
          )}
        </div>
        {filed.length > 0 && (
          <div className="callout ok">
            <b>Filed {filed.length} attachment{filed.length === 1 ? "" : "s"} from that email.</b>{" "}
            {filed.join(", ")} — they are in step 2 and already checked in step 3.
          </div>
        )}
        <p className="detail-note">
          Forwarding the email is usually less work than pasting it, and it brings the
          attachments with it — the spreadsheets land in step 2 without a second upload.
          Reading the email turns it into the specification step 3 checks against; nothing binds
          until you confirm the reading.
        </p>

        {parsed && (
          <div className="parsed">
            <div className="parsed-head">
              <b>{parsed.items.length} item{parsed.items.length === 1 ? "" : "s"} recognised</b>
              {parsed.period_from && (
                <span className="sub">Period read as {parsed.period_from} to {parsed.period_to}</span>
              )}
              {parsed.due_phrase && <span className="sub">Due: {parsed.due_phrase}</span>}
            </div>
            {parsed.items.map((i) => (
              <label className={"parsed-item" + (keep.has(i.key) ? " on" : "")} key={i.key}>
                <input type="checkbox" checked={keep.has(i.key)}
                       onChange={() => {
                         const next = new Set(keep);
                         next.has(i.key) ? next.delete(i.key) : next.add(i.key);
                         setKeep(next);
                       }} />
                <div>
                  <b>{i.label}</b>
                  {i.confidence === "low" && <span className="pill pri-medium">check this one</span>}
                  <div className="sub">
                    matched on “{i.cue}” · {i.required_columns.length} required column
                    {i.required_columns.length === 1 ? "" : "s"}
                  </div>
                </div>
              </label>
            ))}
            {!!parsed.unmatched.length && (
              <div className="callout warn">
                <b>Could not be placed.</b> These did not match anything in the catalogue, so
                they were not guessed into an item:
                <ul>{parsed.unmatched.map((u, n) => <li key={n}>{u}</li>)}</ul>
              </div>
            )}
            <div className="row-actions">
              <button className="btn" disabled={!keep.size} onClick={() => setConfirmed(true)}>
                Confirm {keep.size} item{keep.size === 1 ? "" : "s"} as the request
              </button>
              {confirmed && <span className="pill pri-low">Confirmed</span>}
            </div>
          </div>
        )}
      </Step>

      {/* ------------------------------------------------------- 2 · what came back */}
      <Step n={2} title="Documents received"
            note={docs.length ? `${docs.length} on file` : "nothing yet"}>
        <div
          className={"dropzone" + (drag ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}
        >
          <input ref={fileRef} type="file" multiple accept=".xlsx,.xlsm,.csv,.tsv"
                 style={{ display: "none" }} onChange={(e) => send(e.target.files)} />
          <b>{busy === "upload" ? "Reading…" : "Drop what the taxpayer sent here"}</b>
          <span className="sub">.xlsx, .xlsm, .csv — read into columns and rows on arrival</span>
        </div>
        {!!docs.length && (
          <div className="doclist">
            {docs.map((d) => (
              <div className="docrow" key={d.id}>
                <b>{d.filename}</b>
                <span className="sub">{d.rows} rows · {d.columns} columns</span>
              </div>
            ))}
          </div>
        )}
      </Step>

      {/* ------------------------------------------------------- 3 · the comparison */}
      <Step n={3} title="Requested versus received"
            note={rows.length ? `${outstanding} outstanding of ${rows.length}` : ""}>
        {!docs.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            Nothing has arrived on this round yet, so there is nothing to check. This fills in
            the moment a document lands in step 2.
          </p>
        ) : !hasFormalRequest || !rows.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            This round was raised from the investigation rather than as a formal request with a
            column specification, so there is no item list to check the response against. What
            arrived is above; whether it answers the question is settled by re-running the
            investigation.
          </p>
        ) : (
          <>
            <div className="statebar">
              {STATE_ORDER.map((s) => (
                <button key={s}
                        className={"statechip " + STATE_PILL[s] + (filter === s ? " on" : "")}
                        disabled={!assessment?.summary[s]}
                        onClick={() => setFilter(filter === s ? null : s)}>
                  <b>{assessment?.summary[s] ?? 0}</b>
                  <span>{s === "needs-review" ? "need review" : s}</span>
                </button>
              ))}
            </div>
            <div className="assesslist">
              {shown.map((i) => (
                <div className={"assessrow " + i.state} key={`${i.request_item_id}-${i.label}`}>
                  <span className={"pill " + STATE_PILL[i.state]}>{i.state_label}</span>
                  <div>
                    <b>{i.label}</b>
                    {i.reason && <p>{i.reason}</p>}
                    {!!i.documents.length && i.documents.join(", ") !== i.label && (
                      <small className="mono">{i.documents.join(", ")}</small>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <p className="detail-note">
              <b>Incomplete</b> is the taxpayer's to fix; <b>needs review</b> is yours to settle.
              A chase written from the second asks for something that was already sent.
            </p>
          </>
        )}
      </Step>

      {/* ------------------------------------------------------- 4 · what goes back */}
      <Step n={4} title="The email to send next"
            note={followup?.source ? `drafted ${followup.source}` : ""}>
        {!outstanding ? (
          <p className="detail-note" style={{ margin: 0 }}>
            {docs.length
              ? "Nothing is outstanding on this round — the response meets the request, so the "
                + "next move is the Investigation tab."
              : "The chase is drafted from the gaps, so it appears once there is something to "
                + "chase."}
          </p>
        ) : followup?.text ? (
          <>
            <pre className="letterpre">{followup.text}</pre>
            <div className="row-actions">
              <button className="btn" onClick={() => {
                navigator.clipboard?.writeText(followup.text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              }}>
                {copied ? "Copied" : "Copy the draft"}
              </button>
              <span className="sub">
                Written from the gaps above and nothing else — it asks only for what is still
                missing.
              </span>
            </div>
          </>
        ) : (
          <p className="detail-note" style={{ margin: 0 }}>Drafting…</p>
        )}
      </Step>
    </div>
  );
}
