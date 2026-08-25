import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Collapsible from "./Collapsible";
import { getRegulatoryControls, openThread,
         type ControlAssessment, type RegulatoryState } from "../api";
import { askAbout } from "../ai/ask";

const PILL: Record<string, string> = {
  "applicable-potential-concern": "pri-high",
  "applicable-insufficient-evidence": "pri-medium",
  "potentially-applicable": "pri-medium",
  "not-testable": "status",
  "applicable-tested": "pri-low",
  "not-applicable": "status",
};

/** The order the counts read in: what needs a person, first. */
const ORDER = [
  "applicable-potential-concern",
  "applicable-insufficient-evidence",
  "potentially-applicable",
  "not-testable",
  "applicable-tested",
  "not-applicable",
];

const SHORT: Record<string, string> = {
  "applicable-potential-concern": "Potential concern",
  "applicable-insufficient-evidence": "Evidence missing",
  "potentially-applicable": "Needs your judgement",
  "not-testable": "Not testable",
  "applicable-tested": "Assessed, nothing arising",
  "not-applicable": "Not applicable",
};

function Control({ c, busy, onAsk }: {
  c: ControlAssessment;
  busy: boolean;
  onAsk: (c: ControlAssessment) => void;
}) {
  const [open, setOpen] = useState(false);
  const superseded = c.citation.state === "needs-validation";

  return (
    <div className={"rgrow " + c.status}>
      <button className="rgrow-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="rgrow-what">
          <b>{c.title}</b>
          <small>
            <span className="mono">{c.citation.label || `Article ${c.article}`}</span>
            {c.citation.title && ` · ${c.citation.title}`}
          </small>
        </span>
        {superseded && <span className="pill pri-medium">wording superseded</span>}
        <span className={"pill " + (PILL[c.status] || "status")}>{c.status_label}</span>
        <span className="rgrow-mark">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="rgrow-body">
          <p className="detail-note" style={{ margin: 0 }}>{c.detail}</p>

          <div className="rgblock">
            <span className="k">What the provision requires</span>
            <p>{c.requirement}</p>
          </div>
          {!!c.conditions.length && (
            <div className="rgblock">
              <span className="k">Conditions</span>
              <ul>{c.conditions.map((x, n) => <li key={n}>{x}</li>)}</ul>
            </div>
          )}
          {!!c.exceptions.length && (
            <div className="rgblock">
              <span className="k">Exceptions</span>
              <ul>{c.exceptions.map((x, n) => <li key={n}>{x}</li>)}</ul>
            </div>
          )}
          <div className="rgblock">
            <span className="k">Why it is in scope here</span>
            <p>{c.scope_reason}</p>
          </div>
          {!!c.outcome?.rows?.length && (
            <div className="rgblock">
              <span className="k">Rows behind it</span>
              <p className="mono">
                {c.outcome.rows.slice(0, 20).join(", ")}
                {c.outcome.rows.length > 20 && ` and ${c.outcome.rows.length - 20} more`}
                {c.outcome.files?.length ? ` — in ${c.outcome.files.join(", ")}` : ""}
              </p>
            </div>
          )}

          {/* The article's own words, because a paraphrase is what an auditor checks against
              the source rather than something to rely on. */}
          {c.citation.text && (
            <details className="rgcite">
              <summary>
                {c.citation.label} — the article's own words
                {superseded && " (superseded wording)"}
              </summary>
              {superseded && <div className="callout warn">{c.citation.note}</div>}
              <pre className="letterpre cite-text">{c.citation.text}</pre>
            </details>
          )}

          <div className="row-actions">
            <button className="linklike"
                    onClick={() => askAbout(
                      `About ${c.citation.label || `Article ${c.article}`} — “${c.title}”. `
                      + `The screening says: “${c.detail}” `
                      + `Talk me through whether this provision really applies here, and what `
                      + `evidence would settle it.`)}>
              ask the assistant about it
            </button>
            {(c.status === "applicable-potential-concern"
              || c.status === "applicable-insufficient-evidence") && (
              <button className="btn-ghost challenge" disabled={busy} onClick={() => onAsk(c)}>
                Ask the taxpayer
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Stage 2 — which provisions this case's evidence brings into scope, and what they show.
 *
 *  Six counts, not seventy-nine rows. The specification is explicit that an auditor must not be
 *  made to review a checklist of articles, and the counts are what turns a corpus into
 *  something a person can act on: everything needing attention is above everything that does
 *  not, and the ones that do not still say why. */
export default function RegulatoryCoverage({ id, workstream, rev }: {
  id: string;
  workstream: "sales" | "purchases";
  rev?: number;
}) {
  const [d, setD] = useState<RegulatoryState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const nav = useNavigate();

  const load = useCallback(() => {
    getRegulatoryControls(id).then(setD).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const ask = async (c: ControlAssessment) => {
    setBusy(true);
    setErr("");
    try {
      await openThread(id, `${c.citation.label || `Article ${c.article}`} — ${c.title}`,
                       "investigation-request");
      nav(`/cases/${id}/correspondence`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not open a round for that.");
      setBusy(false);
    }
  };

  if (!d) return null;

  const mine = d.controls.filter((c) => c.applies_to === workstream || c.applies_to === "both");
  const counts = ORDER.map((s) => ({ status: s, n: mine.filter((c) => c.status === s).length }))
                      .filter((x) => x.n);
  const shown = filter ? mine.filter((c) => c.status === filter) : mine;
  const concerns = mine.filter((c) => c.status === "applicable-potential-concern").length;
  const cov = d.summary.coverage;

  return (
    <Collapsible
      title="Regulatory coverage"
      note={`${mine.length} control${mine.length === 1 ? "" : "s"} screened`
            + (concerns ? ` · ${concerns} potential concern${concerns === 1 ? "" : "s"}` : "")}
    >
      {err && <div className="callout warn">{err}</div>}

      {/* The draft status travels to every consumer. A control framework that looked
          authoritative while being unreviewed would be the most dangerous thing here. */}
      <div className="callout warn">
        <b>This control set is an unreviewed draft.</b> It is an editorial reading of the
        articles it cites, not reviewed legal analysis, and it must be confirmed by a tax
        specialist before any of it supports a position taken with a taxpayer. The article's own
        words travel with every citation for exactly that reason.
      </div>

      <div className="statebar">
        {counts.map(({ status, n }) => (
          <button key={status}
                  className={"statechip " + (PILL[status] || "status")
                             + (filter === status ? " on" : "")}
                  onClick={() => setFilter(filter === status ? null : status)}>
            <b>{n}</b>
            <span>{SHORT[status]}</span>
          </button>
        ))}
      </div>

      <div className="rglist">
        {shown.map((c) => <Control key={c.control_id} c={c} busy={busy} onAsk={ask} />)}
      </div>

      <div className="panel-note">
        <span className="ct">∑ computed</span> Scope comes from the evidence and the return, not
        from whether anything differs — which is why a case whose numbers agree is still
        screened. The control set reaches <b>{cov.articles_covered} of {cov.articles_total}</b>{" "}
        articles; the remaining {cov.articles_uncovered} have no control written for them and
        are reported as such rather than passed over in silence.
      </div>
    </Collapsible>
  );
}
