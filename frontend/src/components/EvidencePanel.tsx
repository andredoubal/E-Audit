import { useCallback, useEffect, useState } from "react";
import Collapsible from "./Collapsible";
import { getEvidence, setDatasetType, type DatasetProfile, type EvidenceState } from "../api";

const CONFIDENCE_PILL: Record<string, string> = {
  confirmed: "pri-low",
  high: "pri-low",
  medium: "pri-medium",
  low: "pri-high",
};

const CONFIDENCE_WORD: Record<string, string> = {
  confirmed: "you confirmed this",
  high: "read with confidence",
  medium: "read, worth checking",
  low: "uncertain — please check",
};

/** One dataset, with why the engine thinks it is what it thinks it is.
 *
 *  The reasoning is the point. A classifier that cannot be interrogated is worse than the
 *  filename matching it replaced, because a filename at least behaves predictably — so the
 *  evidence for a reading is on the row, and correcting it is one control away. */
function Dataset({ d, busy, onSet, types }: {
  d: DatasetProfile;
  busy: boolean;
  onSet: (filename: string, type: string) => void;
  types: { key: string; label: string }[];
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const blocking = d.quality_flags.filter((f) => f.severity === "blocking");
  const advisory = d.quality_flags.filter((f) => f.severity !== "blocking");

  return (
    <div className={"evrow" + (d.confidence === "low" ? " uncertain" : "")}>
      <button className="evrow-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="evrow-what">
          <b>{d.dataset_label}</b>
          <small className="mono">{d.filename}</small>
        </span>
        <span className="evrow-meta num">
          {d.record_count} rows · {d.column_count} cols
          {d.date_min && ` · ${d.date_min} → ${d.date_max}`}
        </span>
        <span className={"pill " + (CONFIDENCE_PILL[d.confidence] || "status")}>
          {CONFIDENCE_WORD[d.confidence] || d.confidence}
        </span>
        {!!blocking.length && <span className="pill pri-high">{blocking.length} blocking</span>}
        <span className="evrow-mark">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="evrow-body">
          <p className="detail-note" style={{ margin: 0 }}>
            <b>Why:</b> {d.why}
            {d.provenance === "authority" && " (the Authority's own extract, not a taxpayer document)"}
          </p>
          {d.read_as && (
            <p className="detail-note" style={{ margin: 0 }}>
              <b>Originally read as:</b> {d.read_as.label} — {d.read_as.why}
            </p>
          )}
          {!!d.alternatives.length && (
            <p className="detail-note" style={{ margin: 0 }}>
              <b>Could also be:</b> {d.alternatives.join(", ")}
            </p>
          )}

          <div className="evroles">
            {d.roles.map((r) => (
              <span key={r.column} className={"evrole " + r.confidence} title={r.why}>
                <b>{r.role.replace(/_/g, " ")}</b>
                <span className="mono">{r.column}</span>
              </span>
            ))}
          </div>
          {!!d.unmapped_columns.length && (
            <p className="detail-note" style={{ margin: 0 }}>
              <b>Not used:</b>{" "}
              <span className="mono">{d.unmapped_columns.join(", ")}</span> — the engine does
              not read these, which is worth knowing as well as what it does read.
            </p>
          )}

          {(!!blocking.length || !!advisory.length) && (
            <div className="evflags">
              {[...blocking, ...advisory].map((f, n) => (
                <div className={"evflag " + f.severity} key={f.code + n}>
                  <b>{f.detail}</b>
                  {!!f.rows.length && (
                    <span className="sub mono">
                      row{f.rows.length === 1 ? "" : "s"} {f.rows.slice(0, 12).join(", ")}
                      {f.rows.length > 12 && ` and ${f.rows.length - 12} more`}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {!!d.transformations.length && (
            <details className="evtrans">
              <summary>
                {d.transformations.length} value{d.transformations.length === 1 ? "" : "s"} had
                to be reformatted to be read
              </summary>
              <div className="tablescroll">
                <table className="inv-table">
                  <thead>
                    <tr><th>Row</th><th>Column</th><th>As supplied</th><th>Read as</th>
                      <th>Why</th></tr>
                  </thead>
                  <tbody>
                    {d.transformations.slice(0, 40).map((t, n) => (
                      <tr key={n}>
                        <td className="mono">{t.row_number}</td>
                        <td className="mono">{t.column}</td>
                        <td className="mono">{t.original}</td>
                        <td className="mono">{t.normalised}</td>
                        <td>{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}

          <div className="row-actions">
            {editing ? (
              <>
                <select className="evselect" defaultValue={d.dataset_type} disabled={busy}
                        onChange={(e) => { onSet(d.filename, e.target.value); setEditing(false); }}>
                  {types.map((t) => (
                    <option key={t.key} value={t.key}>{t.label}</option>
                  ))}
                </select>
                <button className="linklike" onClick={() => setEditing(false)}>cancel</button>
              </>
            ) : (
              <>
                <button className="btn-ghost" disabled={busy} onClick={() => setEditing(true)}>
                  This is something else
                </button>
                {d.overridden && (
                  <button className="linklike" disabled={busy}
                          onClick={() => onSet(d.filename, "")}>
                    undo your correction
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Stage 0 — what is on the case, and what the engine made of it.
 *
 *  First in the module and collapsed by default: an auditor wants the answer before the
 *  inputs, but every figure below rests on these readings, so a wrong one has to be findable
 *  and correctable without leaving the page. */
export default function EvidencePanel({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged?: () => void;
}) {
  const [d, setD] = useState<EvidenceState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    getEvidence(id).then(setD).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const set = async (filename: string, type: string) => {
    setBusy(true);
    setErr("");
    try {
      setD(await setDatasetType(id, filename, type));
      onChanged?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not record that.");
    } finally { setBusy(false); }
  };

  if (!d) return null;

  const attention = d.needs_attention;
  const flagged = attention.unclassified.length + attention.low_confidence.length
    + attention.blocking_quality.length;
  const note = d.datasets.length
    ? `${d.datasets.length} file${d.datasets.length === 1 ? "" : "s"} read`
      + (flagged ? ` · ${flagged} need${flagged === 1 ? "s" : ""} a look` : "")
    : "nothing on this case yet";

  return (
    <Collapsible title="Evidence on file" note={note}>
      {err && <div className="callout warn">{err}</div>}

      {!d.datasets.length ? (
        <p className="detail-note" style={{ margin: 0 }}>
          Nothing has been filed on this case. The taxpayer's documents arrive on a round in
          Taxpayer Correspondence, and the Authority's own invoice extract is loaded above.
        </p>
      ) : (
        <>
          {!!flagged && (
            <div className="callout warn">
              <b>Worth a look before you rely on what follows.</b>{" "}
              {!!attention.unclassified.length && (
                <>The engine could not tell what{" "}
                  <span className="mono">{attention.unclassified.join(", ")}</span> is.{" "}</>
              )}
              {!!attention.low_confidence.length && (
                <>It is unsure about{" "}
                  <span className="mono">{attention.low_confidence.join(", ")}</span>.{" "}</>
              )}
              {!!attention.blocking_quality.length && (
                <>{attention.blocking_quality.length} file(s) carry a defect that stops a figure
                  being established from them.</>
              )}
            </div>
          )}

          <div className="evlist">
            {d.datasets.map((x) => (
              <Dataset key={x.filename} d={x} busy={busy} onSet={set}
                       types={d.known_types} />
            ))}
          </div>

          <div className="panel-note">
            <span className="ct">∑ computed</span> Each file is read for what it contains — which
            columns are present and what they hold — rather than for what it is called. Where the
            reading is wrong, correcting it here changes every comparison and every regulatory
            control below.
          </div>
        </>
      )}
    </Collapsible>
  );
}
