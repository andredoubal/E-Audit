import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getRegisters,
  openThread,
  uploadDocument,
  type Register,
  type RegisterInsight,
  type RegistersView,
} from "../api";

const sar = (n: number) =>
  "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const RISK_PILL: Record<string, string> = {
  "no-register": "status",
  agrees: "pri-low",
  "under-declared": "pri-high",
  "over-claimed": "pri-high",
  "over-declared": "pri-medium",
  "under-claimed": "pri-medium",
};

/** One register against its box on the return: three numbers and no rules between them.
 *
 *  The earlier version of this screen was a bridge — register total, minus a clearance-lag
 *  rule, minus netted credit notes, arriving at declared. The rule lines are what made it
 *  arguable, and which documents qualify is a different question answered in the detailed
 *  section below. Here the listing's own arithmetic stands on its own. */
function RegisterCard({ r, onInvoices, onAsk, busy }: {
  r: Register;
  onInvoices: (title: string, invoices: unknown[], note: string) => void;
  onAsk: (r: Register, i: RegisterInsight) => void;
  busy: boolean;
}) {
  const rows = r.invoice_count + r.credit_note_count;
  return (
    <section className={"vreg" + (r.comparable ? "" : " empty")}>
      <div className="vreg-head">
        <b>{r.title}</b>
        <span className="sub">{r.box_label}</span>
        <span className={"pill " + (RISK_PILL[r.risk] || "status")}>{r.risk_label}</span>
      </div>

      {!r.comparable ? (
        <p className="detail-note vreg-none">{r.not_comparable_note}</p>
      ) : (
        <>
          <div className="vreg-rows">
            <button className="vregrow" disabled={!rows}
                    onClick={() => onInvoices(
                      `${r.title} register — ${r.document?.filename ?? "listing"}`,
                      r.invoices,
                      "Every row the listing carries, as the taxpayer supplied it. The register "
                      + "total is the sum of the VAT column across these rows.")}>
              <span className="k">
                Invoice register
                <small>
                  {r.invoice_count} invoice{r.invoice_count === 1 ? "" : "s"}
                  {r.credit_note_count
                    ? ` · ${r.credit_note_count} credit note${r.credit_note_count === 1 ? "" : "s"}`
                    : ""}
                  {r.document ? ` · ${r.document.filename}` : ""}
                </small>
              </span>
              <span className="v num">{sar(r.register_total)}</span>
              <span className="go">›</span>
            </button>

            <div className="vregrow flat">
              <span className="k">
                Declared in the VAT return
                <small>{r.note}</small>
              </span>
              <span className="v num">{sar(r.declared)}</span>
              <span className="go" />
            </div>

            <div className={"vregrow diff " + r.risk}>
              <span className="k">
                Difference
                <small>register less return</small>
              </span>
              <span className="v num">
                {r.difference < 0 ? "−" : r.difference > 0 ? "+" : ""}{sar(r.difference)}
              </span>
              <span className="go" />
            </div>
          </div>

          {/* Where the difference comes from — only where that can actually be established.
              A difference against one declared figure cannot be pinned on particular rows, so
              nothing here claims it can; the lines that do name invoices say so. */}
          {r.insights.length > 0 && (
            <div className="vreg-ins">
              <div className="vreg-ins-head">Where the difference comes from</div>
              {r.insights.map((i) => (
                <div className="vins" key={i.key}>
                  <div className="vins-what">
                    <b>{i.headline}</b>
                    {!!i.amount && <span className="vins-amt num">{sar(i.amount)}</span>}
                    <p>{i.detail}</p>
                  </div>
                  <div className="vins-act">
                    {!!i.invoices.length && (
                      <button className="linklike"
                              onClick={() => onInvoices(i.headline, i.invoices, i.detail)}>
                        see the {i.invoices.length} invoice{i.invoices.length === 1 ? "" : "s"}
                      </button>
                    )}
                    <button className="btn-ghost challenge" disabled={busy}
                            title="Opens a round in Taxpayer Correspondence asking for this"
                            onClick={() => onAsk(r, i)}>
                      Ask the taxpayer
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** The VAT return against the taxpayer's own invoice registers.
 *
 *  First thing in the module, because it is the first thing an auditor asks. The listings
 *  themselves belong to Taxpayer Correspondence and are read from there — but a file can be
 *  dropped here too, and it is filed onto the open round rather than into a second store, so
 *  the same document cannot end up on the case twice. */
export default function VatRegisters({ id, rev, onChanged, onInvoices }: {
  id: string;
  rev?: number;
  onChanged?: () => void;
  onInvoices: (title: string, invoices: unknown[], note: string) => void;
}) {
  const [d, setD] = useState<RegistersView | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  const load = useCallback(() => {
    getRegisters(id).then(setD).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setErr("");
    try {
      // Filed onto the open correspondence round, never into a store of its own — a document
      // that exists in two places is a completeness check answering the wrong question.
      for (const f of Array.from(files)) await uploadDocument(id, f);
      load();
      onChanged?.();
    } catch {
      try {
        await openThread(id, "Registers filed during the investigation",
                         "investigation-request");
        for (const f of Array.from(files)) await uploadDocument(id, f);
        load();
        onChanged?.();
      } catch (e2) {
        setErr(e2 instanceof Error ? e2.message : "Could not read that file.");
      }
    } finally { setBusy(false); }
  };

  const ask = async (r: Register, i: RegisterInsight) => {
    setBusy(true);
    setErr("");
    try {
      await openThread(id, `${r.title} register — ${i.headline}`, "investigation-request");
      nav(`/cases/${id}/correspondence`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not open a round for that.");
      setBusy(false);
    }
  };

  if (!d) return null;

  return (
    <div className="panel vregs">
      <div className="panel-head">
        <h2>The VAT return, against the invoice registers</h2>
        <span className="sub">
          {d.period_from} → {d.period_to}
        </span>
      </div>

      <div className="panel-body">
        {err && <div className="callout warn">{err}</div>}

        <div className="vreg-grid">
          {d.registers.map((r) => (
            <RegisterCard key={r.direction} r={r} busy={busy}
                          onInvoices={onInvoices} onAsk={ask} />
          ))}
        </div>

        <div
          className={"dropzone slim" + (drag ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}
        >
          <input ref={fileRef} type="file" multiple accept=".xlsx,.xlsm,.csv,.tsv"
                 style={{ display: "none" }} onChange={(e) => send(e.target.files)} />
          <b>{busy ? "Reading…" : "Drop a sales or purchases listing here"}</b>
          <span className="sub">
            .xlsx, .xlsm, .csv — read into invoices on arrival. Whichever box a file belongs to
            is decided by its own columns, and it is filed onto the open correspondence round so
            it is on the case once, not twice.
          </span>
        </div>

        <div className="panel-note">
          <span className="ct">∑ computed</span> The register total is the VAT the listing
          itself states, summed row by row — no rule has acted on it, and a row with no readable
          VAT amount is skipped rather than counted as zero. Which documents <i>qualify</i> for a
          box is a different question, answered in the detailed section below.
        </div>
      </div>
    </div>
  );
}
