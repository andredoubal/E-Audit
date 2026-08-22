import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import LifecycleRail from "../components/LifecycleRail";
import AuditReport from "../components/AuditReport";
import TraceInspector from "../components/TraceInspector";
import {
  auditReportDocUrl, auditReportHtmlUrl, getAuditReport, getInvestigationState,
  type AuditReportDoc, type InvestigationState,
} from "../api";

/** What the auditor concluded — assembled from the findings they accepted, and nothing else.
 *
 *  The engine confirms hypotheses; that is not the same as an audit conclusion. So a case
 *  where nothing has been accepted reports no finding, and says why rather than looking
 *  broken. The alternative — quietly reporting every hypothesis the adjudicator confirmed —
 *  would put a machine's proposals under the Authority's letterhead as though a person had
 *  signed them.
 */
export default function Report() {
  const { id = "" } = useParams();
  const [doc, setDoc] = useState<AuditReportDoc | null>(null);
  const [inv, setInv] = useState<InvestigationState | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setDoc(null);
    setErr(null);
    getAuditReport(id).then(setDoc).catch((e) => setErr(String(e)));
    getInvestigationState(id).then(setInv).catch(() => {});
  }, [id]);

  const accepted = inv?.counts.accepted ?? 0;
  const undecided = inv ? inv.counts.total - inv.counts.decided : 0;
  const findingsField = doc?.sections
    .flatMap((s) => s.fields)
    .find((f) => f.label === "Audit Findings");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Audit report</p>
          <h1>{doc?.taxpayer || id}</h1>
        </div>
        {doc && (
          <div style={{ display: "flex", gap: 10 }}>
            <a className="btn" href={auditReportDocUrl(id)}>
              Download Word
            </a>
            <a className="btn-ghost" href={auditReportHtmlUrl(id)} target="_blank" rel="noreferrer">
              Open printable / PDF
            </a>
          </div>
        )}
      </div>

      <CaseTabs id={id} />
      <LifecycleRail id={id} />

      {err && <div className="notice err">Could not build the report — {err}</div>}
      {!doc && !err && <p className="muted">Assembling the report…</p>}

      {doc && (
        <>
          {/* Said before the report rather than after it: a report with nothing in it is a
              statement about where the audit has got to, not a failure to produce one. */}
          {accepted === 0 ? (
            <div className="callout warn">
              <b>No finding has been confirmed yet.</b> This report is built from the findings
              you accept in the Investigation tab — the engine's own verdicts are proposals, not
              audit conclusions.
              {undecided > 0 && ` ${undecided} hypothes${undecided === 1 ? "is is" : "es are"} still undecided.`}
            </div>
          ) : (
            <div className="callout ok">
              <b>
                {accepted} finding{accepted === 1 ? "" : "s"} confirmed by you
              </b>{" "}
              {undecided > 0
                ? `· ${undecided} hypothes${undecided === 1 ? "is" : "es"} still undecided in the Investigation tab.`
                : "· every hypothesis on this case has been ruled on."}
            </div>
          )}

          <div className="panel">
            <div className="panel-head">
              <h2>{doc.title}</h2>
              <span className="muted">
                {doc.completeness.filled} of {doc.completeness.fields} fields answered from the
                case · {doc.completeness.outstanding} need a person or another system
              </span>
            </div>
            <div className="panel-body">
              {doc.sections.map((s) => (
                <div key={s.title} className="rep-section">
                  <h3 className="rep-h">{s.title}</h3>
                  <div className="kv">
                    {s.fields.map((f) => (
                      <div key={f.label}>
                        <span className="k">{f.label}</span>
                        <span className={"v" + (f.held ? "" : " gap")}>{f.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {findingsField && findingsField.trace.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Traceability</h2>
                <span className="muted">Check a statement before you sign it</span>
              </div>
              <div className="panel-body">
                <TraceInspector trace={findingsField.trace} />
              </div>
            </div>
          )}

          {/* The AI's narrative pass over the same case — drafted, verified, and clearly
              separate from the structured report above, which is the document of record. */}
          <AuditReport id={id} />
        </>
      )}
    </div>
  );
}
