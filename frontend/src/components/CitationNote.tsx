import { useState } from "react";
import type { Citation } from "../api";

/** The provision a finding rests on — and, when it matters, a warning about the wording.
 *
 *  A finding is a finding because an obligation exists, not because a spreadsheet disagreed
 *  with a box. This is the middle of that sentence: what the article establishes, and what
 *  follows from the evidence being as found.
 *
 *  Two states earn their own treatment. **needs-validation** means the English edition — ZATCA's
 *  unofficial translation of November 2021 — predates the current Arabic, so the wording shown
 *  is superseded; Article 14 is in this state and founds half the vocabulary, so this is the
 *  normal case rather than an edge one. **not-found** is shown rather than hidden: an absent
 *  citation and one nobody looked for read identically, and only one of them is honest. */
export default function CitationNote({ c }: { c?: Citation | null }) {
  const [open, setOpen] = useState(false);
  if (!c) return null;

  if (c.state === "not-found") {
    return (
      <div className="cite none">
        <span className="pill status">no provision identified</span>
        <span className="sub">{c.note}</span>
      </div>
    );
  }

  return (
    <div className={"cite " + c.state}>
      <div className="cite-head">
        <span className="pill pri-low">{c.label}</span>
        <b>{c.title}</b>
        {c.state === "needs-validation" && (
          <span className="pill pri-medium" title={c.note}>wording superseded</span>
        )}
        <button className="linklike" onClick={() => setOpen(!open)}>
          {open ? "hide the article" : "read the article"}
        </button>
      </div>

      <p className="cite-because">
        <b>{c.label}</b> establishes that {c.establishes}; accordingly, {c.consequence}.
      </p>

      {c.state === "needs-validation" && <p className="cite-warn">{c.note}</p>}

      {open && (
        <>
          <pre className="letterpre cite-text">{c.text}</pre>
          <span className="sub">
            {c.chapter}
            {c.supporting.length > 0 && (
              <> · see also {c.supporting.map((s) => s.label).join(", ")}</>
            )}
            {" · "}ZATCA English translation, unofficial — the Arabic is the official version.
          </span>
        </>
      )}
    </div>
  );
}
