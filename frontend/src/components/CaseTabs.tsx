import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { getCaseDetail, type CaseDetail } from "../api";
import { MODULES } from "./Layout";
import CaseInstructions from "./CaseInstructions";
import CaseAssistant from "./CaseAssistant";

/** The case header: who this is, and which of its three modules you are in.
 *
 *  The modules appear here and in the sidebar. That is deliberately the same navigation twice
 *  — the rail says which case is open, the header says where you are inside it — and the two
 *  are driven by the same route, so they cannot disagree.
 *
 *  It also mounts the two case-wide surfaces, because both are on all three modules and
 *  neither belongs to any one of them.
 */
export default function CaseHeader({ id }: { id: string }) {
  const [d, setD] = useState<CaseDetail | null>(null);

  useEffect(() => {
    getCaseDetail(id).then(setD).catch(() => {});
  }, [id]);


  return (
    <>
      <div className="casehead">
        <div className="casehead-in">
          <Link to="/" className="back">← All cases</Link>
          <h1>{d?.taxpayer?.name || id}</h1>
          <p className="meta">
            <span className="mono">{id}</span>
            {d?.taxpayer?.vat_no && (
              <> · <span className="mono">{d.taxpayer.vat_no}</span></>
            )}
            {d?.period && <> · {d.period}</>}
          </p>
          <nav className="casetabs">
            {MODULES.map((m) => (
              <NavLink key={m.to} to={`/cases/${id}${m.to}`}
                       className={({ isActive }) => "casetab" + (isActive ? " active" : "")}>
                {m.short}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>

      <CaseInstructions id={id} />
      <CaseAssistant id={id} />
    </>
  );
}
