import { useState } from "react";
import CitationNote from "./CitationNote";
import type { ReportTrace } from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

/** Where a sentence in the report came from.
 *
 *  A report that states a conclusion nobody can follow back to its source is not something an
 *  auditor can defend in front of a taxpayer. So every finding line can be opened out into the
 *  chain that produced it:
 *
 *    report statement → the auditor's decision → the hypothesis → the evidence tested
 *                                                              → the regulatory basis
 *
 *  The regulatory leg is shown as explicitly missing rather than omitted. "No article was
 *  identified" and "nobody looked" must not look the same on the page. */
export default function TraceInspector({ trace }: { trace: ReportTrace[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!trace.length) return null;

  return (
    <div className="trace">
      <div className="trace-h">Where each finding came from</div>
      {trace.map((t, i) => {
        const key = `${t.hypothesis_id || "auditor"}-${i}`;
        const isOpen = open === key;
        const auditorWrote = t.source === "auditor-authored";
        return (
          <div className="trace-row" key={key}>
            <button className="trace-line" onClick={() => setOpen(isOpen ? null : key)}>
              <span className="trace-mark">{isOpen ? "▾" : "▸"}</span>
              <span className="trace-stmt">{t.statement}</span>
              {!t.carries_amount && t.amount !== 0 && (
                <span className="sub" title="Another reading of an amount already counted once">
                  same amount
                </span>
              )}
            </button>
            {isOpen && (
              <div className="trace-body">
                <div className="trace-step">
                  <span className="k">Confirmed by</span>
                  {auditorWrote ? (
                    <span>the auditor, written directly — no agent proposed this</span>
                  ) : (
                    <span>
                      the auditor on {t.decided_at ? t.decided_at.slice(0, 10) : "—"}
                      {t.decided_by ? ` (${t.decided_by})` : ""}
                      {t.auditor_comment ? ` — “${t.auditor_comment}”` : ""}
                    </span>
                  )}
                </div>

                {!auditorWrote && (
                  <>
                    <div className="trace-step">
                      <span className="k">Proposed by</span>
                      <span>
                        {t.agent} · <code>{t.hypothesis_id}</code>
                        {t.confidence_band ? ` · ${t.confidence_band} confidence` : ""}
                      </span>
                    </div>
                    {t.why && (
                      <div className="trace-step">
                        <span className="k">Because</span>
                        <span>{t.why}</span>
                      </div>
                    )}
                  </>
                )}

                {t.explanation && (
                  <div className="trace-step">
                    <span className="k">The engine found</span>
                    <span>{t.explanation}</span>
                  </div>
                )}

                <div className="trace-step">
                  <span className="k">Evidence</span>
                  <span>
                    {t.evidence.document ? (
                      <>
                        <b>{t.evidence.document}</b>
                        {t.evidence.rows != null && ` · ${t.evidence.rows} rows tested`}
                      </>
                    ) : (
                      "no single document — see the explanation above"
                    )}
                  </span>
                </div>

                <div className="trace-step">
                  <span className="k">Counted against</span>
                  <span>
                    <code>{t.basis}</code>
                    {t.carries_amount
                      ? ` · ${sar(t.amount)}`
                      : " · already counted under this evidence"}
                  </span>
                </div>

                <div className="trace-step">
                  <span className="k">Regulatory basis</span>
                  <CitationNote c={t.regulatory} />
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
