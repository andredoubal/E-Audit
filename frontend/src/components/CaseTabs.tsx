import { NavLink } from "react-router-dom";
import CaseInstructions from "./CaseInstructions";

/** The three modules a case is worked in. Not a wizard: an auditor part-way through the
 *  investigation who finds they need another document goes back to Correspondence and returns,
 *  so these are places to stand rather than steps to complete in order.
 *
 *  Dossier — what ZATCA already holds — is still routable and linked from the case header. It
 *  is planning-era and dormant under the current scope, so it does not earn a place here. */
const TABS = [
  { to: "/correspondence", label: "Taxpayer Correspondence", hint: "What we asked, what arrived" },
  { to: "/investigation", label: "Investigation", hint: "What the evidence shows" },
  { to: "/report", label: "Audit Report", hint: "What you concluded" },
];

export default function CaseTabs({ id }: { id: string }) {
  return (
    <>
      <div className="casetabs">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={`/cases/${id}${t.to}`}
            className={({ isActive }) => "casetab" + (isActive ? " active" : "")}
          >
            <b>{t.label}</b>
            <small>{t.hint}</small>
          </NavLink>
        ))}
      </div>
      {/* Here rather than on a page, because it applies to all three modules. A steer that
          lived on one of them would be one the auditor believes is in force everywhere and is
          not — worse than not having it at all. */}
      <CaseInstructions id={id} />
    </>
  );
}
