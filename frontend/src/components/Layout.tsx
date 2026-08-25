import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useMatch } from "react-router-dom";
import { openAssistant, openInstructions, onPanel } from "../ai/ask";
import { getInstructions, listCases, type CaseRow } from "../api";
import { Cases, Lines, Moon, Star, Sun } from "./Icon";

export const MODULES = [
  { to: "/correspondence", label: "Taxpayer Correspondence", short: "Correspondence" },
  { to: "/investigation", label: "Investigation", short: "Investigation" },
  { to: "/report", label: "Audit Report", short: "Audit report" },
];

/** Where the whole audit starts, and where this application does not.
 *
 *  The assessment that decided this taxpayer was worth auditing, and the request that went out
 *  in the auditor's own words, both happened before the app saw the case. Naming the phase and
 *  leaving it inert is the honest way to show it — a link would promise a screen that does not
 *  exist, and leaving it out would imply the audit begins where this application does. */
const OUT_OF_SCOPE = "Initial assessment";

type Theme = "light" | "dark";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem("eaudit-theme");
    if (saved === "light" || saved === "dark") return saved;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("eaudit-theme", theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

/** The case you have open: its name, its id, and its own places. */
function OpenCase({ id }: { id: string }) {
  const [row, setRow] = useState<CaseRow | null>(null);
  const [instr, setInstr] = useState("");
  const [open, setOpen] = useState<"instr" | "asst" | null>(null);

  useEffect(() => {
    listCases()
      .then((rows) => setRow(rows.find((c) => c.case_id === id) ?? null))
      .catch(() => {});
  }, [id]);

  // The card shows the first line of what is actually in force, so the auditor can see the
  // steer without opening the panel — an instruction you have to go and check is one you
  // forget you wrote.
  useEffect(() => {
    getInstructions(id).then((d) => setInstr(d.text)).catch(() => {});
  }, [id, open]);
  useEffect(() => onPanel(setOpen), []);

  const firstLine = instr.trim().split("\n").find((l) => l.trim()) ?? "";

  return (
    <>
      <div className="navgroup-open">
        <div className="navgroup-head">
          <span className="navgroup-name">
            <b>{row?.taxpayer || "Open case"}</b>
            <small>{id}</small>
          </span>
        </div>
        <div className="navgroup-items">
          <span className="navsub out" aria-disabled="true"
                title="Outside the scope of this proof of concept">
            {OUT_OF_SCOPE}
            <span className="navsub-scope">Out of scope</span>
          </span>
          {MODULES.map((m) => (
            <NavLink key={m.to} to={`/cases/${id}${m.to}`}
                     className={({ isActive }) => "navsub" + (isActive ? " active" : "")}>
              {m.short}
            </NavLink>
          ))}
        </div>
      </div>

      <div className="sidecards">
        <button className={"sidecard" + (open === "instr" ? " on" : "") + (firstLine ? " set" : "")}
                onClick={openInstructions}>
          <span className="ic"><Lines /></span>
          <span className="sidecard-txt">
            <b>Case instructions</b>
            <span>{firstLine || "None set — add what the documents don't say"}</span>
          </span>
        </button>

        <button className="sidecard ask" onClick={openAssistant}>
          <span className="ic"><Star /></span>
          <span className="sidecard-txt">
            <b>Ask about this case</b>
            <span>Status, gaps, ZATCA records</span>
          </span>
        </button>
      </div>
    </>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const [theme, toggle] = useTheme();
  const [count, setCount] = useState<number | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const match = useMatch("/cases/:id/*");
  // `/cases/new` is the create form, not a case called "new". Without this the rail renders an
  // open-case card for a case that does not exist, with module links pointing nowhere and an
  // instructions fetch that 404s.
  const caseId = match?.params.id === "new" ? undefined : match?.params.id;

  useEffect(() => {
    listCases().then((rows) => setCount(rows.length)).catch(() => {});
  }, []);

  // A 392px panel over a full-width column hides the third of the page the auditor is being
  // helped with — the matter rows and their controls sit exactly where it lands. So the column
  // makes room instead of being covered.
  useEffect(() => onPanel((p) => setPanelOpen(p !== null)), []);

  return (
    <div className={"app" + (panelOpen ? " panelled" : "")}>
      <aside className="side">
        <div className="brand">
          <span className="mark">ZC</span>
          <span>
            <b>ZATCA</b>
            <small>VAT Audit Agent</small>
          </span>
        </div>

        <NavLink to="/" end
                 className={({ isActive }) => "navlink" + (isActive ? " active" : "")}>
          <span className="ic"><Cases /></span>
          <span>Cases</span>
          {count !== null && <span className="count">{count}</span>}
        </NavLink>

        {caseId && <OpenCase id={caseId} />}

        <div className="side-foot">
          <button className="iconbtn" onClick={toggle}
                  title={theme === "dark" ? "Switch to light" : "Switch to dark"}>
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <span>Synthetic demo data. Every figure is the engine's own.</span>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
