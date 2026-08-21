import type { RegCitedUnit } from "../api";

const STATUTORY = new Set(["STATUTORY_TEXT", "IMPLEMENTING_REGULATION", "BOARD_DECISION"]);

function statusPill(status: RegCitedUnit["status"]) {
  if (status === "NEEDS_LEGAL_VALIDATION")
    return (
      <span className="pill pri-high" title="No version on file is confirmed to cover the tax period asked about.">
        ⚠ Needs legal validation
      </span>
    );
  if (status === "SUPERSEDED")
    return <span className="pill status">Superseded</span>;
  return <span className="pill pri-low">Active</span>;
}

function contentTypeBadge(contentType: string) {
  const binding = STATUTORY.has(contentType);
  return (
    <span
      className={"pill " + (binding ? "pri-medium" : "status")}
      title={binding ? "Binding legal text — citable as law." : "Non-binding — guidance or internal notes, never cited as law."}
    >
      {binding ? "⚖ " : "◦ "}
      {contentType.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

/** The Regulatory Knowledge Agent's grounding, rendered structurally — deterministic retrieval
 *  output, no model call, works with zero API key. Mirrors PrecedentPanel.tsx: chip header,
 *  a table/card of matches, drill-down detail. */
export default function RegulatoryCitationsPanel({ units }: { units: RegCitedUnit[] }) {
  if (units.length === 0)
    return (
      <div className="callout warn">
        No matching regulatory text was found for this question in the ingested corpus.
      </div>
    );

  return (
    <div className="reg-citations">
      {units.map((u) => (
        <div key={u.unit_id} className="panel" style={{ marginBottom: 12 }}>
          <div className="panel-head">
            <div className="ai-h">
              <span className="chip-det">Deterministic retrieval</span>
              <h3 style={{ margin: 0 }}>{u.citation_label}</h3>
            </div>
            <span className="sub mono">{u.unit_id}</span>
          </div>
          <div className="panel-body">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              {contentTypeBadge(u.content_type)}
              {statusPill(u.status)}
              <span className="pill status">{u.authority || "unattributed"}</span>
              <span className="pill status">
                effective {u.effective_from} – {u.effective_to || "open"}
              </span>
              <span className="sub">match {u.score.toFixed(2)}</span>
            </div>

            <p style={{ whiteSpace: "pre-wrap" }}>{u.text}</p>

            {u.parent && (
              <details className="drill">
                <summary>Parent article — {u.parent.citation_label}</summary>
                <p style={{ whiteSpace: "pre-wrap" }} className="detail-note">
                  {u.parent.text}
                </p>
              </details>
            )}

            {u.related.length > 0 && (
              <details className="drill">
                <summary>Related provisions ({u.related.length})</summary>
                <ul className="tally">
                  {u.related.map((r) => (
                    <li key={r.type + r.unit_id}>
                      <code>{r.type}</code>
                      <span>{r.citation_label}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
