import { useEffect, useState } from "react";
import { getDossier, type Dossier } from "../api";

/* ---------------------------------------------------------------- who we are dealing with */
/** The registration and the audit record, and nothing else. */
function CaseContext({ d }: { d: Dossier }) {
  const tp = d.taxpayer;
  const h = tp.audit_history;
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Who you are dealing with</h2>
        <span className="pill status">∑ From the registration</span>
      </div>
      <div className="ctx">
        <div className="ctx-block">
          <h4>Registered activities</h4>
          {tp.activities?.length ? (
            <ul className="acts">
              {tp.activities.map((a) => (
                <li key={a.isic}>
                  <span className="rc">{a.isic}</span> {a.description}
                  {a.primary && <span className="pill status">primary</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No economic activities are recorded on the registration.</p>
          )}
          <p className="detail-note">
            Revenue described in terms that match none of these is a secondary activity the
            return may not disclose — which is why the list is here and not in the dossier.
          </p>
        </div>

        <div className="ctx-block">
          <h4>Audit history</h4>
          {h.closed_cases ? (
            <>
              <div className="kv2">
                <div><span className="k">Closed cases</span>{h.closed_cases}</div>
                <div><span className="k">Findings</span>{h.findings}</div>
                <div>
                  <span className="k">Total assessed</span>
                  SAR {Math.abs(h.total_assessed).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </div>
                <div><span className="k">Last outcome</span>{h.last_outcome || "—"}</div>
              </div>
              {!!h.root_causes?.length && (
                <div className="causes">
                  <span className="k">Root causes previously found</span>
                  {h.root_causes.map((c) => <span className="rc" key={c}>{c}</span>)}
                </div>
              )}
            </>
          ) : (
            <p className="muted">This taxpayer has not been audited before.</p>
          )}
        </div>

        <div className="ctx-block">
          <h4>Registration</h4>
          <div className="kv2">
            <div><span className="k">Sector</span>{tp.sector}</div>
            <div><span className="k">Size</span>{tp.size}</div>
            <div><span className="k">Registered</span>{tp.registered_from || "—"}</div>
            <div><span className="k">Accounting</span>{tp.accounting_method}</div>
            <div><span className="k">POS registered</span>{tp.pos_registered ? "yes" : "no"}</div>
            <div><span className="k">Branches</span>{tp.branches}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- what we asked for, from the email */

/** The two facts about the taxpayer the investigation cannot work without, fetched where they are used rather than threaded down from a page. */
export default function CaseContextPanel({ id }: { id: string }) {
  const [d, setD] = useState<Dossier | null>(null);
  useEffect(() => {
    if (!id) return;
    getDossier(id).then(setD).catch(() => {});
  }, [id]);
  if (!d) return null;
  return <CaseContext d={d} />;
}
