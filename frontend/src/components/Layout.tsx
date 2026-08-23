import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useMatch } from "react-router-dom";
import { openAssistant, openInstructions } from "../ai/ask";
import { listCases, type CaseRow } from "../api";
import { Book, Cases, Moon, Sparkles, Sun } from "./Icon";

const MODULES = [
  { to: "/correspondence", label: "Taxpayer Correspondence" },
  { to: "/investigation", label: "Investigation" },
  { to: "/report", label: "Audit Report" },
];

/** Where the whole audit starts, and where this application does not.
 *
 *  The PoC begins when the taxpayer's documents arrive: the assessment that decided this
 *  taxpayer was worth auditing, and the request that went out in the auditor's own words,
 *  both happened before the app saw the case. Naming that phase and leaving it inert is
 *  the honest way to show it — a link would promise a screen that does not exist. */
const OUT_OF_SCOPE = "Initial Assessment & Document Request";

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

/** The case you have open, as a group in the sidebar.
 *
 *  The modules were briefly here on their own, pointing at a hard-coded case id — a link that
 *  lied about where it went. Nested under the case that is actually open they are what they
 *  always were: a case's own places, reached by opening it. */
function OpenCase({ id }: { id: string }) {
  const [name, setName] = useState("");
  const [open, setOpen] = useState(true);

  useEffect(() => {
    listCases()
      .then((rows: CaseRow[]) => setName(rows.find((c) => c.case_id === id)?.taxpayer ?? ""))
      .catch(() => {});
  }, [id]);

  return (
    <div className={"navgroup-open" + (open ? " on" : "")}>
      <button className="navgroup-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="ic"><Book /></span>
        <span className="navgroup-name">
          <b>{name || "Open case"}</b>
          <small>{id}</small>
        </span>
        <span className="navgroup-mark">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="navgroup-items">
          <span className="navsub out" aria-disabled="true"
                title="Outside the scope of this proof of concept">
            {OUT_OF_SCOPE}
            <span className="navsub-scope">Out of PoC scope</span>
          </span>
          {MODULES.map((m) => (
            <NavLink key={m.to} to={`/cases/${id}${m.to}`}
                     className={({ isActive }) => "navsub" + (isActive ? " active" : "")}>
              {m.label}
            </NavLink>
          ))}
          <button className="navsub ai" onClick={openAssistant}>
            <span className="ic"><Sparkles size={14} /></span>
            AI assistant
          </button>
          <button className="navsub" onClick={openInstructions}>
            Custom instructions
          </button>
        </div>
      )}
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const [theme, toggle] = useTheme();
  const match = useMatch("/cases/:id/*");
  const caseId = match?.params.id;

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <span className="mark">ZC</span>
          <span>
            <b>ZATCA</b>
            <small>VAT Audit Agent</small>
          </span>
        </div>
        <nav>
          <NavLink to="/" end
                   className={({ isActive }) => "navlink" + (isActive ? " active" : "")}>
            <span className="ic"><Cases /></span>
            Cases
          </NavLink>
          {caseId && <OpenCase id={caseId} />}
        </nav>
        <div className="side-foot">
          <button className="iconbtn" onClick={toggle}
                  title={theme === "dark" ? "Switch to light" : "Switch to dark"}>
            {theme === "dark" ? <Sun /> : <Moon />}
          </button>
          <span>ZATCA VAT Audit Agent</span>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
