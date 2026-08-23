import { useCallback, useEffect, useState } from "react";
import ReviewControls from "./ReviewControls";
import { getZatca, saveReview, type ItemReview, type ZatcaState } from "../api";

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
 *  Results only. The dataset is loaded at the top of Investigation, and with none loaded there
 *  is one side and no comparison — so this renders nothing at all rather than a panel reporting
 *  a reconciliation that was never run. */
export default function ZatcaPanel({ id, rev }: { id: string; rev?: number }) {
  const [d, setD] = useState<ZatcaState | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [reviews, setReviews] = useState<Record<string, ItemReview>>({});

  const load = useCallback(() => {
    getZatca(id).then(setD).catch(() => {});
    fetch(`/api/cases/${id}/reviews/zatca-mismatch`)
      .then((r) => (r.ok ? r.json() : { reviews: {} }))
      .then((r) => setReviews(r.reviews ?? {}))
      .catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const review = async (key: string, verdict: "approved" | "challenged" | "", note: string) => {
    try {
      const r = await saveReview(id, "zatca-mismatch", key, verdict, note);
      setReviews(r.reviews);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not record that.");
    }
  };

  // No dataset, or one side only: there is no comparison, so there is nothing to report.
  if (!d?.dataset || !d.comparable) return null;

  const shown = open ? d.mismatches.filter((m) => m.category === open) : d.mismatches;

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="chip-det">Deterministic</span>
          <h2>ZATCA's own invoice records</h2>
        </div>
        <span className="muted">
          {d.dataset.row_count} invoices · {d.dataset.filename}
        </span>
      </div>
      <div className="panel-body">
        {err && <div className="callout warn">{err}</div>}

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
              different figure are different money.{" "}
              {d.mismatches.length > 0 && !open && (
                <b>Choose a category above to inspect the invoices behind it.</b>
              )}
            </p>

            {!!open && (
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
                    <ReviewControls
                      review={reviews[`${m.code}::${m.ref}`] ?? null}
                      label={`${CATEGORY[m.category] || m.category} — ${m.ref}`}
                      context={m.detail}
                      busy={false}
                      onReview={(v, note) => review(`${m.code}::${m.ref}`, v, note)}
                    />
                  </div>
                </div>
              ))}
            </div>
            )}

            {!d.mismatches.length && (
              <p className="detail-note" style={{ margin: 0 }}>
                Every invoice in ZATCA's records for this period appears in the listing, with
                the same figures.
              </p>
            )}
        </>
      </div>
    </div>
  );
}
