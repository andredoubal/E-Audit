import { useCallback, useEffect, useState } from "react";
import { getDashboard, getEvidence, type DatasetProfile, type EvidenceState,
         type ReconDashboard } from "../api";
import { PeriodBars } from "./Charts";
import EvidencePanel from "./EvidencePanel";
import ZatcaSource from "./ZatcaSource";

const CONFIDENCE_PILL: Record<string, string> = {
  confirmed: "pri-low", high: "pri-low", medium: "pri-medium", low: "pri-high",
};
const CONFIDENCE_WORD: Record<string, string> = {
  confirmed: "confirmed by you", high: "read with confidence",
  medium: "read, worth checking", low: "uncertain",
};

/** Every dataset on the case, in one table, before any of it is compared to anything.
 *
 *  This is the layer everything else answers to. A register read as an e-invoice extract, a
 *  file whose period sits outside the case, a VAT column that is blank on half its rows — each
 *  of those produces a downstream figure that is wrong in a way no reconciliation can detect,
 *  because by then the reading has already been made. So the readings are stated here, with
 *  what they rest on, and correcting one is a control on the row rather than a support ticket. */
function DatasetTable({ ev, dash, period }: {
  ev: EvidenceState;
  dash: ReconDashboard | null;
  period: [string, string];
}) {
  if (!ev.datasets.length) {
    return (
      <p className="muted">
        No dataset has been filed on this case yet. Everything the taxpayer sent arrives on an
        enquiry in Taxpayer Correspondence; the Authority&rsquo;s own e-invoice extract is
        uploaded above.
      </p>
    );
  }

  /** Which side each canonicalised dataset was actually used on — read from the dashboard, so
   *  the table reports what the engine did rather than what it was expected to do. */
  const usedAs = new Map<string, string>();
  if (dash) {
    for (const [ws, w] of Object.entries(dash.workstreams)) {
      for (const s of [w.sources.register, w.sources.einvoices,
                       w.sources.customs_import, w.sources.customs_export]) {
        if (s) usedAs.set(s.source_file, ws);
      }
    }
  }

  /** How a file's own dates sit against the period under audit.
   *
   *  A listing whose last invoice falls five weeks before the period ends is the single most
   *  expensive thing to miss here: every total taken from it is short by whatever is in those
   *  five weeks, and no comparison downstream can tell that from a genuine under-declaration.
   *  So a partial cover is named as plainly as a file from the wrong period entirely. */
  const coverage = (d: DatasetProfile): { kind: "none" | "outside" | "partial" | "full";
                                          note: string } => {
    if (!d.date_min || !d.date_max) return { kind: "none", note: "" };
    if (d.date_max < period[0] || d.date_min > period[1])
      return { kind: "outside", note: "entirely outside the case period" };
    // A business does not necessarily invoice on the first day of the quarter, and a file whose
    // first row is the 6th is not missing the first five days — it is a file. So a stretch is
    // only named once it is long enough to be an absence rather than a start date, and the
    // count of days is given so the auditor judges it rather than taking the flag's word.
    const days = (a: string, b: string) =>
      Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);
    const MIN_GAP = 14;
    const before = days(period[0], d.date_min);
    const after = days(d.date_max, period[1]);
    const ends = [
      before > MIN_GAP ? `the first ${before} days of the period carry nothing` : "",
      after > MIN_GAP ? `nothing in the last ${after} days` : "",
    ].filter(Boolean);
    if (ends.length)
      return { kind: "partial", note: "covers part of the period — " + ends.join(", ") };
    return { kind: "full", note: "" };
  };

  return (
    <div className="tablewrap">
      <table className="dtable">
        <thead>
          <tr>
            <th>File</th>
            <th>Read as</th>
            <th>Period covered</th>
            <th className="r">Records</th>
            <th>Reading</th>
            <th>Issues</th>
          </tr>
        </thead>
        <tbody>
          {ev.datasets.map((d) => {
            const blocking = d.quality_flags.filter((f) => f.severity === "blocking");
            const advisory = d.quality_flags.filter((f) => f.severity !== "blocking");
            const ws = usedAs.get(d.filename);
            const cover = coverage(d);
            return (
              <tr key={d.filename} className={d.confidence === "low" ? "hot" : ""}>
                <td>
                  <b className="mono xs">{d.filename}</b>
                  <div className="xs muted">
                    {d.provenance === "authority"
                      ? "the Authority's own extract"
                      : "filed by the taxpayer"}
                  </div>
                </td>
                <td>
                  {d.dataset_label}
                  <div className="xs muted">
                    {ws ? `used on ${ws}` : "not used in a comparison"}
                  </div>
                </td>
                <td className="mono xs">
                  {d.date_min ? `${d.date_min} → ${d.date_max}` : <span className="muted">no dates read</span>}
                  {cover.note && <div className="xs hot">{cover.note}</div>}
                </td>
                <td className="r num">{d.record_count}</td>
                <td>
                  <span className={"pill sm " + (CONFIDENCE_PILL[d.confidence] || "status")}>
                    {CONFIDENCE_WORD[d.confidence] || d.confidence}
                  </span>
                </td>
                <td className="xs">
                  {blocking.length > 0 && (
                    <span className="pill sm pri-high">{blocking.length} blocking</span>
                  )}
                  {advisory.length > 0 && (
                    <span className="pill sm pri-medium">{advisory.length} advisory</span>
                  )}
                  {!blocking.length && !advisory.length && <span className="muted">none</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** What could not be read, stated rather than left as an absence.
 *
 *  A column the file does not carry and a column of zeroes are different facts about a
 *  taxpayer, and the second is a declaration while the first is a gap in the evidence. The
 *  canonical layer keeps them apart all the way down; this is where an auditor sees it. */
function Quality({ ev, dash }: { ev: EvidenceState; dash: ReconDashboard | null }) {
  const unreadable: { file: string; field: string; rows: number[] }[] = [];
  const notes: { file: string; note: string }[] = [];
  if (dash) {
    for (const w of Object.values(dash.workstreams)) {
      for (const s of [w.sources.register, w.sources.einvoices]) {
        if (!s) continue;
        for (const [field, rows] of Object.entries(s.unreadable_rows)) {
          if (rows.length) unreadable.push({ file: s.source_file, field, rows });
        }
        for (const n of s.notes) notes.push({ file: s.source_file, note: n });
      }
    }
  }
  // Named by workstream, because the two are merged here and the sentences are written per
  // workstream. "No e-invoice extract for this side has been loaded" sitting under a table
  // that lists one loaded is a panel contradicting the panel above it — the extract is there,
  // it is on sales, and what is missing is the purchases one.
  const unavailable = dash
    ? (Object.entries(dash.workstreams) as [string, typeof dash.workstreams.sales][])
        .flatMap(([ws, w]) => w.unavailable.map((u) => ({ ...u, ws })))
    : [];
  const attention = ev.needs_attention;
  const nothing = !unreadable.length && !notes.length && !unavailable.length
    && !attention.unclassified.length && !attention.low_confidence.length
    && !attention.blocking_quality.length;

  if (nothing) {
    return (
      <p className="detail-note">
        Every dataset on the case was read without a blocking defect, and every column the
        comparisons need is present.
      </p>
    );
  }

  return (
    <div className="quality">
      {!!attention.unclassified.length && (
        <div className="qgroup">
          <span className="ct">unread</span>
          <p>
            Not recognised as any known dataset, so they take part in no comparison:{" "}
            <b className="mono xs">{attention.unclassified.join(", ")}</b>. Say what each one is
            on its row below and it joins the reconciliation.
          </p>
        </div>
      )}
      {!!attention.blocking_quality.length && (
        <div className="qgroup">
          <span className="ct">blocking</span>
          <ul>
            {attention.blocking_quality.map((f, i) => (
              <li key={i}><b className="mono xs">{f.filename}</b> — {f.detail || f.code}</li>
            ))}
          </ul>
        </div>
      )}
      {!!unreadable.length && (
        <div className="qgroup">
          <span className="ct">skipped, not zero</span>
          <ul>
            {unreadable.map((u, i) => (
              <li key={i}>
                <b className="mono xs">{u.file}</b> — {u.rows.length} row(s) carry no readable{" "}
                {u.field.replace(/_/g, " ")} (row{u.rows.length > 1 ? "s" : ""}{" "}
                <span className="mono xs">{u.rows.slice(0, 12).join(", ")}
                {u.rows.length > 12 && " …"}</span>). They contribute nothing to a total rather
                than being summed as zero.
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!unavailable.length && (
        <div className="qgroup">
          <span className="ct">not measured</span>
          <ul>
            {unavailable.map((u, i) => (
              <li key={i}>
                <span className="pill sm">{u.ws}</span> <b>{u.what}</b> — {u.why}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!notes.length && (
        <div className="qgroup">
          <span className="ct">read as</span>
          <ul>
            {notes.map((n, i) => <li key={i}><b className="mono xs">{n.file}</b> — {n.note}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Tab 1 — what arrived, and what the engine made of it.
 *
 *  First because every figure in the other three tabs rests on it, and because a wrong reading
 *  has to be correctable without leaving the investigation. */
export default function DataTab({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged: () => void;
}) {
  const [ev, setEv] = useState<EvidenceState | null>(null);
  const [dash, setDash] = useState<ReconDashboard | null>(null);

  const load = useCallback(() => {
    getEvidence(id).then(setEv).catch(() => {});
    getDashboard(id).then(setDash).catch(() => setDash(null));
  }, [id]);
  useEffect(load, [load, rev]);

  // One entry per canonicalised dataset the comparisons actually used, with the workstream it
  // was used on — the same file can only stand on one side, and saying which is half the point.
  const datasets = dash
    ? (Object.entries(dash.workstreams) as [string, typeof dash.workstreams.sales][])
        .flatMap(([ws, w]) => [w.sources.register, w.sources.einvoices]
          .filter((s): s is NonNullable<typeof s> => !!s)
          .map((src) => ({ ws, src })))
    : [];

  return (
    <>
      <ZatcaSource id={id} rev={rev} onChanged={onChanged} />

      <div className="panel">
        <div className="panel-head">
          <h2>Datasets on this case</h2>
          {ev && (
            <span className="sub num">
              {ev.datasets.length} file(s) ·{" "}
              {ev.datasets.reduce((n, d) => n + d.record_count, 0).toLocaleString("en-US")} records
            </span>
          )}
        </div>
        {ev
          ? <DatasetTable ev={ev} dash={dash} period={[ev.period_from, ev.period_to]} />
          : <p className="muted">Reading the files…</p>}
        <div className="panel-note">
          <span className="ct">read, not assumed</span> What each file <i>is</i> was read from
          its own columns and values, never from its name — a filename may fill a gap but it
          never settles a contradiction. Open a row below to see the evidence for a reading, and
          correct it there if it is wrong.
        </div>
      </div>

      {/* Where the records actually fall across the period. The empty column is the finding:
          a register that stops six weeks before the period ends looks entirely healthy in
          every total it produces. */}
      {!!datasets.length && (
        <div className="panel">
          <div className="panel-head">
            <h2>Coverage across the period</h2>
            <span className="sub">{dash!.period_from} → {dash!.period_to}</span>
          </div>
          <div className="ch-covers">
            {datasets.map(({ ws, src }) => (
              <div className="ch-cover" key={src.source_file + ws}>
                <div className="ch-cover-head">
                  <b className="mono xs">{src.source_file}</b>
                  <span className="sub">{ws} · {src.count} records</span>
                </div>
                <PeriodBars series={src.by_period} from={dash!.period_from}
                            to={dash!.period_to}
                            undated={src.by_period.find((b) => b.period === null)?.count} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-head"><h2>Data quality</h2></div>
        {ev ? <Quality ev={ev} dash={dash} /> : <p className="muted">Checking…</p>}
      </div>

      {/* The existing profiler view, kept whole: the per-dataset reasoning, the detected roles,
          the normalisations applied and the control that overrides a reading. */}
      <EvidencePanel id={id} rev={rev} onChanged={onChanged} />
    </>
  );
}
