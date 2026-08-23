import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
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

  const answered = doc?.completeness.filled ?? 0;

  return (
    <>
      <CaseTabs id={id} />
      <div className="page">
      <div className="modulehead">
        <h2 className="display">Audit report</h2>
        {doc && (
          <span className="sub">
            <span className="num">{answered}</span> of{" "}
            <span className="num">{doc.completeness.fields}</span> fields answered
            {edited > 0 && <> · <span className="num">{edited}</span> yours</>}
            {outstanding > 0 && (
              <> · <span className="num">{outstanding}</span> still open</>
            )}
          </span>
        )}
        {doc && (
          <div className="modulehead-act">
            <a className="btn-ghost" href={auditReportDocUrl(id)}>Download Word</a>
            <a className="btn-ghost" href={auditReportHtmlUrl(id)}
               target="_blank" rel="noreferrer">Printable</a>
          </div>
        )}
      </div>

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

          {doc.sections.map((s) => (
            <section key={s.title} className="panel rsection">
              <h3>{s.title}</h3>
              <div className="panel-body">
                <div className="rfields">
                  {s.fields.map((f) => (
                    <EditableField key={f.key || f.label} field={f} onSave={save} />
                  ))}
                </div>
              </div>
            </section>
          ))}

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

    </div>
    </>
  );
}
