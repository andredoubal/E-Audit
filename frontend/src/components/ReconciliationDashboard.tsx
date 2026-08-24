import { useEffect, useState } from "react";
import {
  getDashboard,
  type Comparison,
  type CompareSide,
  type MatchRow,
  type ReconDashboard,
  type ReconException,
  type ReconObservation,
  type WorkstreamDash,
} from "../api";
import { Legend, ProportionBar, RankedBars, SourceBars,
         type Segment, type SourceBar } from "./Charts";

const sar = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const signed = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : (n < 0 ? "−" : "") + sar(n);

const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : `${(Math.abs(n) * 100).toFixed(1)}%`;

/** Colour says *how settled the comparison is*, never how bad the taxpayer is. */
const STATUS_CLASS: Record<string, string> = {
  reconciled: "pri-low",
  "reconciled-with-explained-difference": "pri-low",
  "partially-reconciled": "pri-medium",
  "variance-identified": "pri-high",
  "insufficient-evidence": "status",
};

// ------------------------------------------------------------------ level 3
const MATCH_ORDER = [
  "a-only", "b-only", "value-mismatch", "vat-mismatch", "treatment-mismatch",
  "period-mismatch", "date-mismatch", "duplicate", "missing-identifier", "exact-match",
];

/** The transaction level, opened one category at a time.
 *
 *  Twenty-two invoices is a table an auditor can read; four thousand is not, and neither is
 *  useful opened all at once. So the level lands on its own rollup — how many agree, how many
 *  are on one side only, how many disagree about a figure — and the rows are behind the
 *  category. That is the same shape the ZATCA reconciliation panel already uses, for the same
 *  reason: the count is the finding, the rows are the evidence for it. */
function Transactions({ c }: { c: Comparison }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!c.matches.length) return null;

  const groups = new Map<string, MatchRow[]>();
  for (const m of c.matches) {
    const g = groups.get(m.status) ?? [];
    g.push(m);
    groups.set(m.status, g);
  }
  const ordered = [...groups.entries()].sort(
    (a, b) => MATCH_ORDER.indexOf(a[0]) - MATCH_ORDER.indexOf(b[0]));

  const segs: Segment[] = ordered.map(([status, rows]) => ({
    key: status,
    label: rows[0].status_label,
    value: rows.length,
    tone: status === "exact-match" ? "agree"
      : status === "missing-identifier" ? "warn" : "differ",
  }));

  return (
    <div className="l3">
      {/* Proportion, not count: "18 of 22 agree" is a glance rather than four chips read and
          added. Selecting a segment is the same act as selecting its chip. */}
      <ProportionBar segments={segs} onSelect={(k) => setOpen(open === k ? null : k)}
                     selected={open} />
      <div className="l3-rollup">
        {ordered.map(([status, rows]) => (
          <button
            key={status}
            className={"l3-chip" + (open === status ? " on" : "")
              + (status === "exact-match" ? " agree" : "")}
            onClick={() => setOpen(open === status ? null : status)}
            aria-expanded={open === status}
          >
            <b className="num">{rows.length}</b>
            <span>{rows[0].status_label.toLowerCase()}</span>
          </button>
        ))}
      </div>

      {open && (
        <div className="l3-rows">
          <p className="detail-note" style={{ margin: "0 0 8px" }}>
            {groups.get(open)![0].detail
              || `${groups.get(open)!.length} record(s) — ${groups.get(open)![0].status_label.toLowerCase()}.`}
          </p>
          <div className="tablewrap">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Reference</th>
                  <th className="r">{c.a.label}</th>
                  <th className="r">{c.b.label}</th>
                  <th className="r">Difference</th>
                  <th>Source rows</th>
                </tr>
              </thead>
              <tbody>
                {groups.get(open)!.slice(0, 200).map((m, i) => (
                  <tr key={m.reference + i}>
                    <td className="mono">{m.reference || <span className="muted">none</span>}</td>
                    <td className="r num">{sar(m.a_amount)}</td>
                    <td className="r num">{sar(m.b_amount)}</td>
                    <td className="r num">{m.delta === null ? "—" : signed(m.delta)}</td>
                    <td className="mono xs">
                      {[...m.a_records, ...m.b_records].slice(0, 4).join(", ")}
                      {m.a_records.length + m.b_records.length > 4 && " …"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {groups.get(open)!.length > 200 && (
            <p className="detail-note">
              Showing the first 200 of {groups.get(open)!.length}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ one comparison
/** One pairing, at all three levels, with the question it answers stated on it.
 *
 *  The question is not decoration. "Sales register ↔ e-invoices" and "e-invoices ↔ VAT return"
 *  can carry the same figure and mean completely different things — the first is the taxpayer's
 *  own record against the invoice population, the second is that population against what was
 *  filed — and which pair disagrees is the only thing that changes what the auditor does next. */
function ComparisonCard({ c }: { c: Comparison }) {
  const [open, setOpen] = useState(false);

  if (!c.runnable) {
    return (
      <div className="cmp cmp-blocked">
        <div className="cmp-head">
          <span className="cmp-code num">{c.code}</span>
          <span className="cmp-title">
            <b>{c.title}</b>
            <small>{c.question}</small>
          </span>
          <span className="pill status">Not run</span>
        </div>
        <p className="cmp-blockedwhy">
          Could not be compared — {c.blocked_by.join("; ")}. Reported rather than run against
          whatever happens to be on the case: one side is not a comparison.
        </p>
      </div>
    );
  }

  const varyTreatments = c.treatments.filter((t) => t.status === "variance-identified");

  return (
    <div className={"cmp" + (open ? " open" : "")}>
      <button className="cmp-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="cmp-code num">{c.code}</span>
        <span className="cmp-title">
          <b>{c.title}</b>
          <small>{c.question}</small>
        </span>
        <span className="cmp-figs">
          <span className="cmp-fig">
            <i>{c.a.label}</i>
            <b className="num">{sar(c.a.total)}</b>
          </span>
          <span className="cmp-fig">
            <i>{c.b.label}</i>
            <b className="num">{sar(c.b.total)}</b>
          </span>
          <span className={"cmp-fig" + (c.variance ? " hot" : "")}>
            <i>Difference</i>
            <b className="num">{signed(c.variance)}</b>
          </span>
        </span>
        <span className={"pill " + (STATUS_CLASS[c.status] || "status")}>{c.status_label}</span>
        <span className="cmp-mark">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="cmp-body">
          <p className="detail-note" style={{ marginTop: 0 }}>
            Measured in <b>{c.metric_label}</b>. Tolerance for this comparison is{" "}
            {sar(c.tolerance.allowance)} — {c.tolerance.note}.
          </p>

          {/* Why the status can differ from what the headline difference suggests. Written by
              the engine, not here: this card must not compose a reason of its own for a
              verdict Python reached. */}
          {c.notes.map((n, i) => (
            <p className="cmp-note" key={i}>{n}</p>
          ))}

          {/* level 2 — the category that earns its own level: totals that broadly agree while
              a single VAT treatment inside them does not. */}
          {!!c.treatments.length && (
            <>
              <h4 className="lvl">By VAT treatment</h4>
              <div className="tablewrap">
                <table className="dtable">
                  <thead>
                    <tr>
                      <th>Treatment</th>
                      <th className="r">{c.a.label}</th>
                      <th className="r">{c.b.label}</th>
                      <th className="r">Difference</th>
                      <th className="r">%</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.treatments.map((t) => (
                      <tr key={t.treatment} className={t.status === "variance-identified" ? "hot" : ""}>
                        <td>{t.label}</td>
                        <td className="r num">{sar(t.a_total)} <i className="xs">({t.a_count})</i></td>
                        <td className="r num">{sar(t.b_total)} <i className="xs">({t.b_count})</i></td>
                        <td className="r num">{signed(t.variance)}</td>
                        <td className="r num">{pct(t.variance_pct)}</td>
                        <td>
                          <span className={"pill sm " + (STATUS_CLASS[t.status] || "status")}>
                            {t.status_label}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* The two sides as proportions. Money moved between treatments nets to nothing
                  in the totals above, so this is the only level that shows it — and side by
                  side as proportions is the only way two sources of different size compare. */}
              <div className="ch-splits">
                {([["a", c.a] as const, ["b", c.b] as const]).map(([which, side]) => {
                  const segs: Segment[] = c.treatments.map((t) => ({
                    key: t.treatment,
                    label: t.label,
                    value: Math.abs((which === "a" ? t.a_total : t.b_total) || 0),
                    tone: t.treatment === "standard-rated" ? "agree"
                      : t.treatment === "unclassified" ? "warn" : "neutral",
                  }));
                  if (!segs.some((x) => x.value)) return null;
                  return (
                    <div className="ch-split" key={which}>
                      <span className="ch-split-l">{side.label}</span>
                      <ProportionBar segments={segs} />
                    </div>
                  );
                })}
                <Legend segments={c.treatments.map((t) => ({
                  key: t.treatment, label: t.label,
                  value: Math.abs(t.variance || 0),
                  tone: t.treatment === "standard-rated" ? "agree"
                    : t.treatment === "unclassified" ? "warn" : "neutral",
                }))} />
                <p className="ch-note">
                  Each bar is one source&rsquo;s own composition; the legend carries the
                  difference between them per treatment.
                </p>
              </div>

              {!varyTreatments.length && (
                <p className="detail-note">Every treatment agrees within tolerance.</p>
              )}
            </>
          )}

          <h4 className="lvl">By transaction</h4>
          <Transactions c={c} />
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ one workstream
function WorkstreamDashboard({ w, name, comparisons }: {
  w: WorkstreamDash;
  name: string;
  comparisons: Comparison[];
}) {
  const s = w.summary;

  // The three sources on one scale. Every value here is lifted from a comparison the engine
  // already ran — nothing is recomputed to draw the picture.
  const vat = comparisons.filter((c) => c.metric === "vat");
  const sideOf = (src: CompareSide["source"]) => {
    for (const c of vat) {
      if (c.a.source === src && c.a.present) return c.a;
      if (c.b.source === src && c.b.present) return c.b;
    }
    return null;
  };
  const registerLabel = name.startsWith("Sales") ? "Sales register" : "Purchase register";
  const sources: SourceBar[] = ([
    ["register", registerLabel, "the taxpayer\u2019s own listing",
     `no ${registerLabel.toLowerCase()} on the case`],
    ["e-invoices", "E-invoices", "the Authority\u2019s extract",
     "no e-invoice extract for this side on the case"],
    ["vat-return", "VAT return", "as filed", "no return on file for this period"],
  ] as const).map(([key, label, origin, missing]) => {
    const side = sideOf(key);
    return {
      key, label,
      value: side?.total ?? null,
      origin: side?.origin || origin,
      present: !!side && side.total !== null,
      missing,
    };
  });
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{name}</h2>
        <span className="sub num">
          {s.comparisons_run} of {s.comparisons_total} comparisons run
          {s.with_variance ? ` · ${s.with_variance} with a variance` : ""}
        </span>
      </div>

      {/* Only what the evidence supports. A KPI card for a dataset that is not on the case
          would read zero — which is a lie — or empty, which trains the eye to skip the row. */}
      {!!w.kpis.length && (
        <div className="kpis">
          {w.kpis.map((k) => (
            <div className="kpi" key={k.key} title={k.note || undefined}>
              <div className="kpi-n num">
                {k.unit === "sar" ? sar(k.value) : k.value.toLocaleString("en-US")}
              </div>
              <div className="kpi-l">{k.label}</div>
              <div className="kpi-s">{k.source}</div>
              {k.note && <div className="kpi-note">{k.note}</div>}
            </div>
          ))}
        </div>
      )}

      {/* The picture the module exists to give: which of the three sources is out of line,
          at a glance rather than six figures read across the tiles above. */}
      <div className="ch-row">
        <SourceBars
          title="What each source says this period is worth, in VAT"
          bars={sources}
          note="One scale, so the outlier is the one that stands out. A source not on the case
                has no bar rather than a bar of nothing — a zero-length bar would say the
                taxpayer declared nothing, which is a different claim entirely."
        />
      </div>

      {/* The one figure a stakeholder repeats, and deliberately not a total. Three comparisons
          over the same two files disagree about the same money three times; adding them yields
          a number that corresponds to nothing. */}
      {!!s.largest_exception && (
        <div className="headline">
          <div>
            <div className="headline-n num">{sar(s.largest_exception)}</div>
            <div className="headline-l">
              Largest single exception — {s.largest_exception_is}
            </div>
          </div>
          {s.not_summed_because && <p className="headline-note">{s.not_summed_because}</p>}
        </div>
      )}

      {!!w.unavailable.length && (
        <div className="unavail">
          <span className="ct">not measured</span>
          <ul>
            {w.unavailable.map((u, i) => (
              <li key={i}><b>{u.what}</b> — {u.why}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="cmps">
        {comparisons.map((c) => <ComparisonCard key={c.code + c.metric} c={c} />)}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ observations
/** What the calculations show, as sentences — and nothing more than that.
 *
 *      WRONG    The taxpayer understated sales because invoices were omitted.
 *      CORRECT  3 e-invoices totalling SAR 357,000 could not be matched to the sales register.
 *
 *  Every sentence here is the second kind, generated deterministically from the comparison
 *  results and passed through the neutrality guard before it leaves Python. No model writes any
 *  of it, which is what makes this section quotable in a letter. */
function Observations({ observations }: { observations: ReconObservation[] }) {
  if (!observations.length) return null;
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Reconciliation observations</h2>
        <span className="sub">{observations.length} — descriptive, computed, no explanation attached</span>
      </div>
      <ul className="obslist">
        {observations.map((o) => (
          <li key={o.id}>
            <span className="obs-id mono xs">{o.id}</span>
            <span className="obs-t">{o.text}</span>
            {!!o.source_files.length && (
              <span className="obs-src mono xs">{o.source_files.join(" · ")}</span>
            )}
          </li>
        ))}
      </ul>
      <div className="panel-note">
        <span className="ct">∑ computed</span> These are counts and sums over the records on
        file. They say what differs, never why — that is the next tab, and it is proposed rather
        than concluded.
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ exceptions
function Exceptions({ exceptions }: { exceptions: ReconException[] }) {
  const material = exceptions.filter((e) => e.kind !== "comparison-not-possible");
  if (!material.length) return null;
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Exceptions</h2>
        <span className="sub">{material.length} — what the investigation works from</span>
      </div>
      {/* Separate baselines, never stacked and never running to a total. The shape is the
          argument: several of these rest on the same records, so a stacked bar would draw a
          figure that corresponds to nothing. */}
      <div className="ch-row">
        <RankedBars
          rows={[...material]
            .filter((e) => e.metric === "vat" && e.variance)
            .sort((a, b) => Math.abs(b.variance || 0) - Math.abs(a.variance || 0))
            .slice(0, 8)
            .map((e) => ({ key: e.id, label: e.category,
                           sub: `${e.reconciliation}${e.affected_count
                             ? ` · ${e.affected_count} record(s)` : ""}`,
                           value: e.variance || 0 }))}
          note="Ranked, not accumulated. These bars share a scale but not a baseline: adding
                them would count the same records more than once, which is why the dashboard
                publishes the largest single exception and never a total."
        />
      </div>

      <div className="tablewrap">
        <table className="dtable">
          <thead>
            <tr>
              <th>Ref</th>
              <th>Reconciliation</th>
              <th>Category</th>
              <th className="r">Records</th>
              <th className="r">Value</th>
              <th>Also measured as</th>
            </tr>
          </thead>
          <tbody>
            {material.map((e) => (
              <tr key={e.id}>
                <td className="mono xs">{e.id}</td>
                <td>{e.reconciliation}</td>
                <td>{e.category}</td>
                <td className="r num">{e.affected_count || "—"}</td>
                <td className="r num">{signed(e.variance)} <i className="xs">{e.metric}</i></td>
                <td className="xs">
                  {e.also_measured.length
                    ? e.also_measured.map((a) =>
                        `${signed(a.variance)} of ${a.metric_label.toLowerCase()}`).join("; ")
                    : <span className="muted">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel-note">
        <span className="ct">counted once</span> An exception measured in VAT and again in the
        taxable amount beneath it is <b>one</b> matter read twice, so it is one row with the
        second reading beside it. Exceptions are never added together: several of these rest on
        the same records, and summing them produces a figure corresponding to nothing.
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the tab
export default function ReconciliationDashboard({ id, rev }: { id: string; rev?: number }) {
  const [d, setD] = useState<ReconDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { setD(null); setErr(null); }, [id]);
  useEffect(() => {
    let live = true;
    getDashboard(id)
      .then((j) => { if (live) { setD(j); setErr(null); } })
      .catch((e) => { if (live) setErr(String(e)); });
    return () => { live = false; };
  }, [id, rev]);

  if (err)
    return <div className="panel"><div className="notice err">Could not build the dashboard — {err}</div></div>;
  if (!d) return <p className="muted">Reconciling…</p>;

  const forWs = (ws: string) => d.comparisons.filter((c) => c.workstream === ws);

  return (
    <>
      <WorkstreamDashboard w={d.workstreams.sales} name="Sales — output VAT"
                           comparisons={forWs("sales")} />
      <WorkstreamDashboard w={d.workstreams.purchases} name="Purchases — input VAT"
                           comparisons={forWs("purchases")} />
      <Observations observations={d.observations} />
      <Exceptions exceptions={d.exceptions} />
    </>
  );
}
