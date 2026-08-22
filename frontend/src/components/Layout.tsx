import { useEffect, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { Cases, Moon, Sun } from "./Icon";

/** Cases is the whole sidebar. */
const NAV = [{ to: "/", label: "Cases", end: true, icon: <Cases /> }];

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

export default function Layout({ children }: { children: ReactNode }) {
  const [theme, toggle] = useTheme();

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
