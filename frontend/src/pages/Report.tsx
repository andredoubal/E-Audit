import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import CaseAssistant from "../components/CaseAssistant";
import StepEmails from "../components/StepEmails";
import AuditReport from "../components/AuditReport";
import EditableField from "../components/EditableField";
import TraceInspector from "../components/TraceInspector";
import {
  auditReportDocUrl, auditReportHtmlUrl, getAuditReport, getInvestigationState,
  saveReportField, type AuditReportDoc, type InvestigationState,
} from "../api";

/** What the auditor concluded — assembled from the findings they accepted, and nothing else. */
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

  // The endpoint returns the whole report, so the completeness tally in the header moves with
  // the edit rather than going stale until the next reload.
  const save = useCallback(async (key: string, value: string, original: string) => {
    setDoc(await saveReportField(id, key, value, original));
  }, [id]);

  const accepted = inv?.counts.accepted ?? 0;
  const undecided = inv ? inv.counts.total - inv.counts.decided : 0;
  const findingsField = doc?.sections
    .flatMap((s) => s.fields)
    .find((f) => f.label === "Audit Findings");
  const outstanding = doc?.completeness.outstanding ?? 0;
  const edited = doc?.edited_fields ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Audit report</p>
          <h1>{doc?.taxpayer || id}</h1>
        </div>
        {doc && (
          <div className="chips">
            <a className="btn" href={auditReportDocUrl(id)}>Download Word</a>
            <a className="btn small" href={auditReportHtmlUrl(id)}
               target="_blank" rel="noreferrer">Open printable / PDF</a>
          </div>
        )}
      </div>

      <CaseTabs id={id} />

      {err && <div className="callout warn">Could not build the report — {err}</div>}
      {!doc && !err && <p className="muted">Assembling the report…</p>}

      {doc && (
        <>
          {accepted === 0 ? (
            <div className="callout warn">
              <b>No finding has been confirmed yet.</b> This report — and the letter at the
              bottom of this page — are built from the findings you accept in the Investigation
              tab. The engine's own verdicts are proposals, not audit conclusions.
              {undecided > 0 && ` ${undecided} hypothes${undecided === 1 ? "is is" : "es are"} still undecided.`}
            </div>
          ) : (
            <div className="callout ok">
              <b>{accepted} finding{accepted === 1 ? "" : "s"} confirmed by you</b>{" "}
              {undecided > 0
                ? `· ${undecided} hypothes${undecided === 1 ? "is" : "es"} still undecided in the Investigation tab.`
                : "· every hypothesis on this case has been ruled on."}
            </div>
          )}

          <div className="panel">
            <div className="panel-head">
              <h2>{doc.title}</h2>
              <div className="chips">
                <span className="pill status">
                  {doc.completeness.filled} of {doc.completeness.fields} answered
                </span>
                {outstanding > 0 && (
                  <span className="pill pri-medium"
                        title="Either ZATCA holds it in another system, or it is a judgement only you can make. Both are editable.">
                    {outstanding} still open
                  </span>
                )}
                {edited > 0 && (
                  <span className="pill pri-low">{edited} written by you</span>
                )}
              </div>
            </div>
            <div className="panel-body">
              <p className="detail-note" style={{ marginTop: 0 }}>
                Every field here can be written in your own words — the ones marked{" "}
                <b>[for the auditor to complete]</b> are judgements the tool has no business
                making, and <b>[not held]</b> is something ZATCA keeps in another system. What
                you write replaces what the engine wrote, is marked as yours, keeps the original
                beside it, and goes into the Word and printable versions too.
              </p>
              {doc.sections.map((s) => (
                <section key={s.title} className="rep-section">
                  <h3 className="rep-h">{s.title}</h3>
                  <div className="rfields">
                    {s.fields.map((f) => (
                      <EditableField key={f.key || f.label} field={f} onSave={save} />
                    ))}
                  </div>
                </section>
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

          <AuditReport id={id} />

          <StepEmails id={id} only={["verdict"]} />
        </>
      )}

      <CaseAssistant id={id} />
    </div>
  );
}
