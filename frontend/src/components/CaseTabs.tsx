import { NavLink } from "react-router-dom";
import CaseInstructions from "./CaseInstructions";

/** The three modules a case is worked in. */
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
      <CaseInstructions id={id} />
    </>
  );
}
