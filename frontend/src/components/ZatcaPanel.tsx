import { useCallback, useEffect, useRef, useState } from "react";
import { getZatca, removeZatca, uploadZatca, type ZatcaState } from "../api";

const CATEGORY: Record<string, string> = {
  omission: "On one side only",
  value: "Figures disagree",
  timing: "Dates disagree",
  party: "Counterparty differs",
  duplicate: "Repeated invoice number",
  identifier: "Nothing to match on",
  sequence: "Break in the numbering",
};

const sar = (n: number) =>
  n ? `SAR ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "";

/** The Authority's own invoice records, matched against the listing the taxpayer sent.
 *
 *  Every disagreement here comes from a named deterministic rule — no model is involved in the
 *  matching or in any figure. That is not a limitation: joining two invoice populations is
 *  closed arithmetic, and doing it in Python is what makes the same two files produce the same
 *  answer every time it is run.
 *
 *  With only one side loaded the panel says it cannot compare, rather than showing every record
 *  as unmatched. */
export default function ZatcaPanel({ id, onChanged }: { id: string; onChanged?: () => void }) {
  const [d, setD] = useState<ZatcaState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => { getZatca(id).then(setD).catch(() => {}); }, [id]);
  useEffect(load, [load]);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setErr("");
    try {
      setD(await uploadZatca(id, files[0]));
      onChanged?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally { setBusy(false); }
  };

  const unload = async () => {
    setBusy(true);
    try {
      setD(await removeZatca(id));
      onChanged?.();
    } finally { setBusy(false); }
  };

  if (!d) return null;

  const shown = open ? d.mismatches.filter((m) => m.category === open) : d.mismatches;

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="chip-det">Deterministic</span>
          <h2>ZATCA's own invoice records</h2>
        </div>
        <span className="muted">
          {d.dataset
            ? `${d.dataset.row_count} invoices · ${d.dataset.filename}`
            : "nothing loaded"}
        </span>
      </div>
      <div className="panel-body">
        {!d.dataset && (
          <div
            className={"dropzone" + (drag ? " over" : "")}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
            onClick={() => fileRef.current?.click()}
          >
            <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv"
                   style={{ display: "none" }}
                   onChange={(e) => send(e.target.files)} />
            <b>{busy ? "Reading…" : "Drop the Authority's invoice extract here"}</b>
            <span className="sub">
              optional — the case works without it, and says so rather than guessing
            </span>
          </div>
        )}
        {err && <div className="callout warn">{err}</div>}

        {!d.comparable && (
          <div className="callout">
            <b>Not compared.</b> {d.note}
          </div>
        )}

        {d.comparable && (
          <>
            <div className="statebar">
              <div className="statechip pri-low" style={{ cursor: "default" }}>
                <b>{d.matched_count}</b><span>matched</span>
              </div>
              {d.categories.map((c) => (
                <button
                  key={c.category}
                  className={"statechip " + (c.blocking ? "pri-high" : "pri-medium")
                             + (open === c.category ? " on" : "")}
                  onClick={() => setOpen(open === c.category ? null : c.category)}
                  title={CATEGORY[c.category] || c.category}
                >
                  <b>{c.count}</b>
                  <span>
                    {CATEGORY[c.category] || c.category}
                    {c.vat_at_stake ? ` · ${sar(c.vat_at_stake)}` : ""}
                  </span>
                </button>
              ))}
            </div>

            <p className="detail-note" style={{ marginTop: 0 }}>
              {d.listing_count} rows in <b>{d.listing_name || "the listing"}</b> against{" "}
              {d.zatca_count} in <b>{d.zatca_name}</b>. Amounts are read per rule, never added
              across them — an invoice missing from the listing and one recorded with a
              different figure are different money.
            </p>

            <div className="assesslist">
              {shown.map((m, i) => (
                <div
                  className={"assessrow " + (m.severity === "blocking" ? "incomplete" : "needs-review")}
                  key={`${m.code}-${m.ref}-${i}`}
                >
                  <span className={"pill " + (m.severity === "blocking" ? "pri-high" : "pri-medium")}>
                    {m.code}
                  </span>
                  <div>
                    <b>{CATEGORY[m.category] || m.category}</b>
                    {m.vat_at_stake ? <span className="sub"> · {sar(m.vat_at_stake)}</span> : null}
                    <p>{m.detail}</p>
                    {m.citation && <small className="mono">{m.citation}</small>}
                  </div>
                </div>
              ))}
              {!shown.length && (
                <p className="detail-note" style={{ margin: 0 }}>
                  Every invoice in ZATCA's records for this period appears in the listing, with
                  the same figures.
                </p>
              )}
            </div>
          </>
        )}

        {d.dataset && (
          <div className="resp-actions" style={{ marginTop: 12 }}>
            <button className="linklike" onClick={unload} disabled={busy}>
              {busy ? "…" : "unload this dataset"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
