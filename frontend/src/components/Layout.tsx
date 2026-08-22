import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

/** What is genuinely global, and nothing else.
 *
 *  Correspondence, Investigation and the Audit Report are the three modules of **one case**;
 *  they were in this sidebar pointing at a hard-coded case id, so "Correspondence" opened the
 *  demo case whichever case you were actually working — a link that lies about where it goes.
 *  They belong on `CaseTabs`, which knows which case you are in, and you reach them by opening
 *  a case from the list. */
/** Cases is the whole sidebar. The Rulebook page is still built and still routable at `/rules`
 *  — it is reference material, not a place the work happens, and an auditor lands here to pick
 *  up a case rather than to read the rule library. Same treatment as Dossier: dormant, not
 *  deleted. */
const NAV = [
  { to: "/", label: "Cases", end: true, icon: "▣" },
];
const SOON = ["Legal retrieval"];

export default function Layout({ children }: { children: ReactNode }) {
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
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => "navlink" + (isActive ? " active" : "")}
            >
              <span className="ic">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
          <div className="navgroup">Coming next</div>
          {SOON.map((s) => (
            <span key={s} className="navlink disabled">
              <span className="ic">◦</span>
              {s}
            </span>
          ))}
        </nav>
        <div className="side-foot">ZATCA VAT Audit Agent</div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
