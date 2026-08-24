import { useCallback, useEffect, useRef, useState } from "react";
import ReviewControls from "./ReviewControls";
import {
  getFollowup,
  saveReview,
  parseRequestChain,
  uploadDocument,
  uploadEmails,
  type Assessment,
  type CorrespondenceThread,
  type Draft,
  type FiledEmail,
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

/** A sample chain, as two real `.eml` files rather than as text. */
const SAMPLE_CHAIN: { name: string; from: string; to: string; date: string;
                      subject: string; body: string; attachment?: [string, string] }[] = [
  {
    name: "01-request.eml",
    from: "vat.audit@zatca.gov.sa",
    to: "finance@taxpayer.example",
    date: "Mon, 14 Apr 2025 09:12:00 +0300",
    subject: "VAT audit — Q1 2025 — information request",
    body: `Dear Sir/Madam,

Further to our review of your VAT position for Q1 2025, please provide the following
within 20 working days:

1. A detailed sales analysis for the period, with the following columns: invoice date,
   invoice number, customer name, customer VAT number, description, taxable amount,
   VAT rate and VAT amount.
2. A detailed purchases analysis on which input VAT was claimed.
3. The trial balance as at 31 March 2025.

Yours faithfully,
Zakat, Tax and Customs Authority`,
  },
  {
    name: "02-reply.eml",
    from: "finance@taxpayer.example",
    to: "vat.audit@zatca.gov.sa",
    date: "Tue, 22 Apr 2025 16:40:00 +0300",
    subject: "RE: VAT audit — Q1 2025 — information request",
    body: `Dear Sir,

Please find attached the sales analysis for the quarter. The trial balance is with our
external accountants and will follow next week.

Kind regards,
Finance`,
    // The point of the sample: the spreadsheet arrives with the message, and lands in step 2
    // without anyone uploading it a second time.
    attachment: ["Sales_Analysis_Q1_2025.csv",
      "invoice_date,invoice_number,customer_name,customer_vat_number,taxable_amount,vat_amount\n" +
      "2025-01-14,INV-2025-1001,Riyadh Trading Est,300044556600003,120000.00,18000.00\n" +
      "2025-02-03,INV-2025-1002,Jeddah Supplies Co,300055667700003,84000.00,12600.00\n" +
      "2025-02-27,INV-2025-1003,Dammam Retail LLC,300066778800003,196000.00,29400.00\n" +
      "2025-03-19,INV-2025-1004,Khobar Wholesale,300077889900003,58000.00,8700.00\n"],
  },
  {
    name: "03-chase.eml",
    from: "vat.audit@zatca.gov.sa",
    to: "finance@taxpayer.example",
    date: "Wed, 07 May 2025 10:05:00 +0300",
    subject: "RE: VAT audit — Q1 2025 — information request",
    body: `Dear Sir,

Thank you for the sales analysis. The following are still outstanding, and we would be
grateful to receive them within 10 working days:

1. The trial balance as at 31 March 2025.
2. A reconciliation of the return to the ledger for the period.
3. A credit and debit note listing for the period.

Yours faithfully,
Zakat, Tax and Customs Authority`,
  },
];

function sampleFiles(): File[] {
  return SAMPLE_CHAIN.map((m) => {
    const head = `From: ${m.from}\r\nTo: ${m.to}\r\nDate: ${m.date}\r\n` +
                 `Subject: ${m.subject}\r\nMIME-Version: 1.0\r\n`;
    if (!m.attachment) {
      return new File([head + `Content-Type: text/plain; charset="utf-8"\r\n\r\n${m.body}\r\n`],
                      m.name, { type: "message/rfc822" });
    }
    const [name, csv] = m.attachment;
    const b = "eaudit-sample-boundary";
    const body =
      head +
      `Content-Type: multipart/mixed; boundary="${b}"\r\n\r\n` +
      `--${b}\r\nContent-Type: text/plain; charset="utf-8"\r\n\r\n${m.body}\r\n\r\n` +
      `--${b}\r\nContent-Type: text/csv; charset="utf-8"\r\n` +
      `Content-Disposition: attachment; filename="${name}"\r\n\r\n${csv}\r\n` +
      `--${b}--\r\n`;
    return new File([body], m.name, { type: "message/rfc822" });
  });
}

/** One step of a round, as its own card.
 *
 *  Steps 2 and 3 open by default: the state of the response is what the auditor came for, and
 *  the two letters are one click away. Opening all four at once put a page of correspondence
 *  between them and the answer. */
function Step({ n, title, note, defaultOpen = false, children }: {
  n: number;
  title: string;
  note?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className={"rstep" + (open ? " on" : "")}>
      <button className="rstep-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="rstep-n">{n}</span>
        <b>{title}</b>
        {note && <span className="sub">{note}</span>}
        <span className="rstep-mark">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="rstep-body">{children}</div>}
    </section>
  );
}

/** One round of correspondence, in the order it actually happens. */
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
  const [parsed, setParsed] = useState<ParsedRequest | null>(null);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const [mailDrag, setMailDrag] = useState(false);
  const [followup, setFollowup] = useState<Draft | null>(null);
  const [noDraft, setNoDraft] = useState("");
  const [filter, setFilter] = useState<ItemState | null>(null);
  const [copied, setCopied] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const [results, setResults] = useState<FiledEmail[]>([]);

  const docs = thread?.documents ?? [];
  const messages = thread?.messages ?? [];
  const rows = assessment?.items ?? [];
  // A round is not one pass. The chase goes out, they reply with more files, and
  // steps 3 and 4 recompute against everything on the round.
  const exchanges = messages.length;
  // Challenged rows are not chased, so they must not be counted as outstanding either —
  // a badge saying 3 above a letter asking for 2 is the sort of disagreement this whole
  // pass exists to remove.
  const outstanding = rows.filter((r) => r.chased ?? r.state !== "received").length;

  const loadFollowup = useCallback(() => {
    if (!outstanding) { setFollowup(null); setNoDraft(""); return; }
    setNoDraft("");
    getFollowup(id)
      .then((d) => { setFollowup(d); setNoDraft(""); })
      // A chase can only be written against an issued request. Saying so beats a spinner that
      // never resolves, which is what this did before.
      .catch(() => { setFollowup(null); setNoDraft("no issued request to chase against"); });
  }, [id, outstanding]);
  useEffect(loadFollowup, [loadFollowup]);

  /** Read the spec from the whole chain, not from one message. */
  const readChain = async () => {
    setBusy("read");
    setErr("");
    setConfirmed(false);
    try {
      const p = await parseRequestChain(id);
      setParsed(p);
      setKeep(new Set(p.items.map((i) => i.key)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read the chain.");
    } finally { setBusy(""); }
  };

  const sendEmails = async (list: File[] | FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (!files.length) return;
    setBusy("email");
    setErr("");
    try {
      const r = await uploadEmails(id, files);
      setResults(r.results);
      onChanged();
      loadFollowup();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read those emails.");
    } finally { setBusy(""); }
  };

  /** The auditor's verdict on one row of the analysis. */
  const review = async (key: string, verdict: "approved" | "challenged" | "", note: string) => {
    setBusy("review");
    setErr("");
    try {
      await saveReview(id, "completeness-item", key, verdict, note);
      onChanged();
      loadFollowup();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not record that.");
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
          {/* What this round is actually about. A round opened from the investigation carries
              the question in its subject, and an auditor who lands here from that button needs
              to see it — "Raised by the investigation" alone does not say which matter. */}
          {thread?.subject && thread.origin !== "initial" && (
            <span className="round-subject"> — {thread.subject}</span>
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

      <Step n={1} title="The email chain"
            note={messages.length ? `${messages.length} message${messages.length === 1 ? "" : "s"}` : "nothing sent yet"}>
        {messages.map((m) => (
          <div className={"msg msg-" + m.direction} key={m.seq}>
            <div className="msg-meta">
              <b>{m.sender}</b>
              <span className="sub">
                → {m.recipient} · {WHO[m.drafted_by] || m.drafted_by}
                {m.sent_at
                  ? ` · sent ${m.sent_at}`
                  : m.created_at && ` · filed ${m.created_at.slice(0, 10)}`}
              </span>
            </div>
            <pre className="letterpre">{m.body}</pre>
          </div>
        ))}

        <div
          className={"dropzone" + (mailDrag ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setMailDrag(true); }}
          onDragLeave={() => setMailDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setMailDrag(false);
            sendEmails(e.dataTransfer.files);
          }}
          onClick={() => emailRef.current?.click()}
        >
          <input ref={emailRef} type="file" multiple accept=".eml,.msg"
                 style={{ display: "none" }} onChange={(e) => sendEmails(e.target.files)} />
          <b>
            {busy === "email" ? "Reading the chain…" : "Drop the email chain here"}
          </b>
          <span className="sub">
            .eml or .msg — as many as you like, filed in the order they were sent, with their
            attachments
          </span>
        </div>

        <div className="row-actions">
          <button className="btn" disabled={!!busy || !messages.length} onClick={readChain}>
            {busy === "read" ? "Reading…" : "Read what was asked for"}
          </button>
          {!messages.length && (
            <button className="linklike" disabled={!!busy}
                    onClick={() => sendEmails(sampleFiles())}>
              use a sample chain
            </button>
          )}
        </div>

        {!!results.length && (
          <div className="maillist">
            {results.map((r, n) => (
              <div className={"mailrow" + (r.ok ? "" : " bad")} key={`${r.filename}-${n}`}>
                <b>{r.filename}</b>
                {r.ok ? (
                  <span className="sub">
                    {r.direction === "outbound" ? "sent by ZATCA" : "from the taxpayer"}
                    {r.sent_at ? ` · ${r.sent_at}` : " · no date header"}
                    {r.filed?.length
                      ? ` · ${r.filed.length} attachment${r.filed.length === 1 ? "" : "s"} filed: ${r.filed.join(", ")}`
                      : " · no attachments"}
                  </span>
                ) : (
                  <span className="sub">not filed — {r.note}</span>
                )}
                {r.ok && r.note && <span className="sub">{r.note}</span>}
              </div>
            ))}
          </div>
        )}


        {parsed && (
          <div className="parsed">
            <div className="parsed-head">
              <b>{parsed.items.length} item{parsed.items.length === 1 ? "" : "s"} recognised</b>
              {parsed.period_from && (
                <span className="sub">Period read as {parsed.period_from} to {parsed.period_to}</span>
              )}
              {parsed.due_phrase && <span className="sub">Due: {parsed.due_phrase}</span>}
              {parsed.outbound_read !== undefined && (
                <span className="sub">
                  read from {parsed.outbound_read} ZATCA message
                  {parsed.outbound_read === 1 ? "" : "s"}
                  {!!parsed.inbound_skipped && `, ${parsed.inbound_skipped} taxpayer reply not read as a request`}
                </span>
              )}
            </div>
            {parsed.period_note && (
              <div className="callout warn">
                <b>The chain names two periods.</b> {parsed.period_note}.
              </div>
            )}
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
            {!!parsed.messages_read?.length && (
              <details>
                <summary>Which message asked for what</summary>
                <div className="maillist">
                  {parsed.messages_read.map((m) => (
                    <div className={"mailrow" + (m.direction === "inbound" ? " muted" : "")}
                         key={m.seq}>
                      <b>
                        {m.direction === "outbound" ? "ZATCA" : "Taxpayer"} · message {m.seq}
                        {m.subject ? ` — ${m.subject}` : ""}
                      </b>
                      <span className="sub">
                        {m.items.length
                          ? `first asked for: ${m.items.join(", ")}`
                          : m.note}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
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

      <Step n={2} defaultOpen title="Documents received"
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

      <Step n={3} defaultOpen title="Documents received analysis"
            note={rows.length ? `${outstanding} outstanding of ${rows.length}` : ""}>
        {!docs.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            Nothing has arrived on this round yet, so there is nothing to check. This fills in
            the moment a document lands in step 2.
          </p>
        ) : !hasFormalRequest || !rows.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            {thread?.origin === "initial"
              ? "No specification has been confirmed for this round yet, so there is nothing "
                + "to check the response against. Read the chain in step 1 and confirm the "
                + "reading — the item list, and this check, follow from it."
              : "This round was raised from the investigation rather than as a formal request "
                + "with a column specification, so there is no item list to check the response "
                + "against. What arrived is above; whether it answers the question is settled "
                + "by re-running the investigation."}
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
                <div className={"assessrow " + i.state
                       + (i.review?.verdict === "challenged" ? " challenged" : "")}
                     key={i.key || `${i.request_item_id}-${i.label}`}>
                  <span className={"pill " + STATE_PILL[i.state]}>{i.state_label}</span>
                  <div>
                    <b>{i.label}</b>
                    {i.reason && <p>{i.reason}</p>}
                    {!!i.documents.length && i.documents.join(", ") !== i.label && (
                      <small className="mono">{i.documents.join(", ")}</small>
                    )}
                    <ReviewControls
                      review={i.review}
                      label={i.label}
                      context={i.reason}
                      busy={!!busy}
                      onReview={(v, note) => review(i.key, v, note)}
                    />
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </Step>

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
        ) : noDraft ? (
          <p className="detail-note" style={{ margin: 0 }}>
            No chase can be drafted yet — {noDraft}. Confirm the reading in step 1 and the draft
            is written from whatever step 3 still shows outstanding.
          </p>
        ) : (
          <p className="detail-note" style={{ margin: 0 }}>Drafting…</p>
        )}
      </Step>
    </div>
  );
}
