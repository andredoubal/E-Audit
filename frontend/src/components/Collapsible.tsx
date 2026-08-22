import { useState, type ReactNode } from "react";

/** A section that starts closed and remembers nothing.
 *
 *  The Investigation page carries the whole working-out — the funnel, the three-way comparison,
 *  the evidence, the auditor's own arithmetic, the narrative. It is all needed and none of it is
 *  what you open the page to read, so it lives behind one heading rather than pushing the
 *  findings four screens down. */
export default function Collapsible({ title, note, children, defaultOpen = false }: {
  title: string;
  note?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={"collapse" + (open ? " on" : "")}>
      <button className="collapse-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="collapse-mark">{open ? "▾" : "▸"}</span>
        <b>{title}</b>
        {note && <span className="sub">{note}</span>}
        <span className="collapse-action">{open ? "Hide" : "Show"}</span>
      </button>
      {open && <div className="collapse-body">{children}</div>}
    </div>
  );
}
