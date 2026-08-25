import { useState } from "react";
import { parseRequestEmail, type ParsedRequest } from "../api";

const SAMPLE_EMAIL = `Dear Sir/Madam,

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

export default function RequestEmailPanel({ id }: { id: string }) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedRequest | null>(null);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const run = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setConfirmed(false);
    try {
      const p = await parseRequestEmail(id, text);
      setParsed(p);
      setKeep(new Set(p.items.map((i) => i.key)));
    } finally { setBusy(false); }
  };

  const toggle = (key: string) => {
    const next = new Set(keep);
    next.has(key) ? next.delete(key) : next.add(key);
    setKeep(next);
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>What you asked for</h2>
        <span className="pill status" title="Read from your own email. The parse is a proposal you confirm before anything is checked against it.">
          ∑ Recovered from the email
        </span>
      </div>
      <div className="panel-body">
        <p className="detail-note" style={{ marginTop: 0 }}>
          Paste the email you sent the taxpayer. It becomes the specification the response is
          checked against — so nothing binds until you have confirmed the reading below.
        </p>
        <textarea className="letter-input" rows={8} value={text}
                  placeholder="Paste the request email here…"
                  onChange={(e) => setText(e.target.value)} />
        <div className="row-actions">
          <button className="btn" disabled={busy || !text.trim()} onClick={run}>
            {busy ? "Reading…" : "Read the email"}
          </button>
          <button className="linklike" onClick={() => setText(SAMPLE_EMAIL)}>use a sample</button>
        </div>

        {parsed && (
          <>
            <div className="parsed-head">
              <b>{parsed.items.length} item(s) recognised</b>
              {parsed.period_from && (
                <span className="sub">
                  Period read as {parsed.period_from} to {parsed.period_to}
                </span>
              )}
              {parsed.due_phrase && <span className="sub">Due: {parsed.due_phrase}</span>}
            </div>

            {parsed.items.map((i) => (
              <label className={"parsed-item" + (keep.has(i.key) ? " on" : "")} key={i.key}>
                <input type="checkbox" checked={keep.has(i.key)} onChange={() => toggle(i.key)} />
                <div>
                  <b>{i.label}</b>
                  {i.confidence === "low" && <span className="pill pri-medium">check this one</span>}
                  <div className="sub">
                    matched on “{i.cue}” · {i.required_columns.length} required column(s)
                  </div>
                  {!!i.required_columns.length && (
                    <div className="cols">
                      {i.required_columns.map((c) => <span className="ct" key={c}>{c}</span>)}
                    </div>
                  )}
                </div>
              </label>
            ))}

            {!!parsed.unmatched.length && (
              <div className="callout warn">
                <b>Could not be placed.</b> These asks did not match anything in the catalogue,
                so they were not guessed into an item:
                <ul>{parsed.unmatched.map((u, n) => <li key={n}>{u}</li>)}</ul>
              </div>
            )}

            <div className="row-actions">
              <button className="btn" disabled={!keep.size} onClick={() => setConfirmed(true)}>
                Confirm {keep.size} item(s) as the request
              </button>
              {confirmed && <span className="pill pri-low">Confirmed</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- the received files */
