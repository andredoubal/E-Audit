import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getReconciliations, openThread, type ReconResult, type ReconState } from "../api";

const sar = (n: number) =>
  "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

/** Colour says which of the five, and the five are the only things a comparison may conclude. */
const PILL: Record<string, string> = {
  reconciled: "pri-low",
  "reconciled-with-explained-difference": "pri-low",
  "partially-reconciled": "pri-medium",
  "variance-identified": "pri-high",
  "insufficient-evidence": "status",
};

function Row({ r, onDrill, onAsk, busy }: {
  r: ReconResult;
  onDrill: (title: string, detail: unknown) => void;
  onAsk: (r: ReconResult) => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const missing = r.status === "insufficient-evidence";

  return (
    <div className={"rcrow " + r.status}>
      <button className="rcrow-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="rcrow-what">
          <b>{r.title}</b>
          <small>{r.note}</small>
        </span>
        {!missing ? (
          <span className="rcrow-nums">
            <span className="num">{sar(r.value_a)}</span>
            <span className="vs">vs</span>
            <span className="num">{sar(r.value_b)}</span>
            <span className={"num delta " + r.status}>
              {r.variance > 0 ? "+" : r.variance < 0 ? "−" : ""}{sar(r.variance)}
            </span>
          </span>
        ) : (
          <span className="rcrow-nums missing">not run</span>
        )}
        <span className={"pill " + (PILL[r.status] || "status")}>{r.status_label}</span>
        <span className="rcrow-mark">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="rcrow-body">
          <p className="detail-note" style={{ margin: 0 }}>{r.explanation}</p>

          {missing ? (
            <>
              <p className="detail-note" style={{ margin: 0 }}>
                <b>To run this, the case needs:</b> {r.needs.join("; ")}.
              </p>
              <div className="row-actions">
                <button className="btn-ghost challenge" disabled={busy} onClick={() => onAsk(r)}>
                  Ask the taxpayer for it
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="rcmeta">
                <span><span className="k">Method</span>{r.method}</span>
                <span><span className="k">Tolerance</span>
                  {r.tolerance.name} · {sar(r.tolerance.allowance)} allowed
                </span>
                <span><span className="k">Sources</span>
                  {[r.source_a, r.source_b].filter(Boolean).join(" · ") || "the VAT return"}
                </span>
              </div>

              {!!r.causes.length && (
                <div className="rccauses">
                  {r.causes.map((c, n) => (
                    <div className="rccause" key={c.cause + n}>
                      <b>{c.label}{!!c.amount && <> · {sar(c.amount)}</>}</b>
                      <span>{c.detail}</span>
                    </div>
                  ))}
                </div>
              )}

              {!!r.conventions.filter((c) => c.convention !== "as-stated").length && (
                <div className="rccauses">
                  {r.conventions.filter((c) => c.convention !== "as-stated").map((c, n) => (
                    <div className="rccause" key={n}>
                      <b>How {c.source} writes its figures</b>
                      <span>{c.note}</span>
                    </div>
                  ))}
                </div>
              )}

              {!!r.quality_notes.length && (
                <div className="callout warn">
                  <b>Defects in the files this rests on.</b>
                  <ul>{r.quality_notes.map((q, n) => <li key={n}>{q}</li>)}</ul>
                </div>
              )}

              <div className="row-actions">
                {!!r.contributions.length && (
                  <button className="linklike" onClick={() => onDrill(
                    r.title,
                    { type: "recon-contributions", contributions: r.contributions,
                      label_a: r.label_a, label_b: r.label_b, note: r.method })}>
                    see the {r.contributions.length} row
                    {r.contributions.length === 1 ? "" : "s"} behind it
                  </button>
                )}
                {(r.status === "variance-identified" || r.status === "partially-reconciled") && (
                  <button className="btn-ghost challenge" disabled={busy}
                          onClick={() => onAsk(r)}>
                    Ask the taxpayer about it
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Stage 1 — every comparison the evidence supports, and every one it does not.
 *
 *  The second half earns its place. A comparison that silently does not run looks identical to
 *  one that ran and found nothing, and the list of what is missing is also the list a chase
 *  letter should be asking for. */
export default function ReconciliationPanel({ id, workstream, rev, onDrill }: {
  id: string;
  workstream: "sales" | "purchases";
  rev?: number;
  onDrill: (title: string, detail: unknown) => void;
}) {
  const [d, setD] = useState<ReconState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showBlocked, setShowBlocked] = useState(false);
  const nav = useNavigate();

  const load = useCallback(() => {
    getReconciliations(id).then(setD).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const ask = async (r: ReconResult) => {
    setBusy(true);
    setErr("");
    try {
      await openThread(id, `${r.title} — ${r.status_label}`, "investigation-request");
      nav(`/cases/${id}/correspondence`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not open a round for that.");
      setBusy(false);
    }
  };

  if (!d) return null;

  // Only what the six pairwise comparisons do not already answer. Four of these definitions
  // ask exactly what a pairing asks — the same two sources, the same metric — and the
  // dashboard above states those. Showing both would report one difference twice in slightly
  // different words, which is how an auditor comes to distrust both panels.
  const mine = d.results.filter((r) => r.workstream === workstream && !r.superseded_by);
  const ran = mine.filter((r) => r.status !== "insufficient-evidence");
  const blocked = mine.filter((r) => r.status === "insufficient-evidence");
  const s = d.workstreams[workstream];

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Supporting reconciliations</h2>
        <span className="sub">
          {ran.length} of {mine.length} could be run
          {s.unexplained_count ? ` · ${s.unexplained_count} with an unexplained difference` : ""}
        </span>
        {!!s.largest_unexplained && (
          <span className="sub num" style={{ marginLeft: "auto" }}>
            largest {sar(s.largest_unexplained)}
          </span>
        )}
      </div>

      <div className="panel-body">
        {err && <div className="callout warn">{err}</div>}

        {!ran.length && !blocked.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            Every comparison defined for this workstream is one of the six above. There is no
            further supporting reconciliation — point-of-sale takings, the ledger, credit notes
            or customs records — defined for it.
          </p>
        ) : (
          <>
            {!ran.length ? (
              <p className="detail-note" style={{ margin: 0 }}>
                None of the supporting reconciliations can be run on the {workstream} side
                yet — they need documents beyond the register, the e-invoices and the return.
                What is missing is listed below, and that list is what to ask the taxpayer for.
              </p>
            ) : (
              <div className="rclist">
                {ran.map((r) => (
                  <Row key={r.id} r={r} busy={busy} onDrill={onDrill} onAsk={ask} />
                ))}
              </div>
            )}

            {!!blocked.length && (
              <>
                <button className="linklike" onClick={() => setShowBlocked((v) => !v)}>
                  {showBlocked ? "hide" : "show"} the {blocked.length} comparison
                  {blocked.length === 1 ? "" : "s"} that could not be run
                </button>
                {showBlocked && (
                  <div className="rclist muted-list">
                    {blocked.map((r) => (
                      <Row key={r.id} r={r} busy={busy} onDrill={onDrill} onAsk={ask} />
                    ))}
                  </div>
                )}
              </>
            )}

            {s.not_summed_because && (
              <div className="panel-note">
                <span className="ct">∑ computed</span> {s.not_summed_because}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
