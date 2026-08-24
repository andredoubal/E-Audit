/** The dashboard's charts. No library, no canvas, no SVG — CSS boxes sized from engine figures.
 *
 *  Three rules hold everywhere in this file, and they are the reason it is hand-rolled:
 *
 *  **A chart never introduces a figure.** Every bar is a geometric encoding of a number the
 *  deterministic core computed, and the exact value is printed beside it. A reader must never
 *  have to estimate from a bar length something the engine knows precisely — the picture is for
 *  spotting which source is out of line, and the label is the fact.
 *
 *  **Absent is not zero.** A source that is not on the case has no bar at all and says so. A
 *  zero-length bar would assert that the taxpayer declared nothing, which is a different and
 *  much more serious claim than "we do not hold this".
 *
 *  **Teal is what the engine found; red is disagreement; orange is only ever what you pressed.**
 *  The palette must not drift: a chart where the accent means both "important" and "clickable"
 *  teaches the auditor nothing.
 */
const sar = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

// ------------------------------------------------------------------ three sources, one scale
export interface SourceBar {
  key: string;
  label: string;
  value: number | null;
  origin: string;
  /** false when the source is not on the case: no bar, and the reason in its place. */
  present: boolean;
  missing?: string;
}

/** The three sources side by side, on one scale.
 *
 *  This is the picture the module exists to give: register, e-invoices and return next to each
 *  other, so *which* is out of line is a glance rather than six numbers read across tiles. The
 *  outlier is coloured because it is the outlier, not because it is bad — the same figure would
 *  be the outlier if the taxpayer had over-declared. */
export function SourceBars({ title, bars, note }: {
  title: string;
  bars: SourceBar[];
  note?: string;
}) {
  const present = bars.filter((b) => b.present && b.value !== null);
  if (present.length < 2) return null;

  const values = present.map((b) => Math.abs(b.value as number));
  const max = Math.max(...values, 1);
  // The one furthest from the middle of the others — flagged as the outlier, not as a fault.
  const mid = values.reduce((a, b) => a + b, 0) / values.length;
  const outlier = present.reduce((w, b) =>
    Math.abs(Math.abs(b.value as number) - mid) > Math.abs(Math.abs(w.value as number) - mid)
      ? b : w, present[0]);
  const spread = Math.max(...values) - Math.min(...values);

  return (
    <div className="ch-chart">
      <div className="ch-head">
        <b>{title}</b>
        {spread > 0 && (
          <span className="ch-sub num">widest gap {sar(spread)}</span>
        )}
      </div>
      <div className="ch-hbars">
        {bars.map((b) => (
          <div className="ch-hbar" key={b.key}>
            <span className="ch-hbar-l">
              {b.label}
              <i>{b.origin}</i>
            </span>
            {b.present && b.value !== null ? (
              <>
                <span className="ch-hbar-track">
                  <span
                    className={"ch-hbar-fill" + (b.key === outlier.key && spread > 0 ? " out" : "")}
                    style={{ width: `${(Math.abs(b.value) / max) * 100}%` }}
                  />
                </span>
                <span className="ch-hbar-v num">{sar(b.value)}</span>
              </>
            ) : (
              // No bar at all. A zero-length bar would say the taxpayer declared nothing.
              <span className="ch-hbar-absent">{b.missing || "not on the case"}</span>
            )}
          </div>
        ))}
      </div>
      {note && <p className="ch-note">{note}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ composition
export interface Segment {
  key: string;
  label: string;
  value: number;
  /** which palette slot: agreement, disagreement, neutral, or a treatment's own colour */
  tone?: "agree" | "differ" | "neutral" | "warn";
}

/** One proportional bar. Used for VAT-treatment composition and for match outcomes.
 *
 *  Proportions, so two sources of different size are still comparable — which is the whole
 *  point at level 2, where money moved between treatments nets to nothing in the totals. */
export function ProportionBar({ segments, total, onSelect, selected }: {
  segments: Segment[];
  total?: number;
  onSelect?: (key: string) => void;
  selected?: string | null;
}) {
  const sum = total ?? segments.reduce((n, s) => n + Math.abs(s.value), 0);
  if (!sum) return null;
  return (
    <div className="ch-pbar">
      {segments.map((s) => {
        const w = (Math.abs(s.value) / sum) * 100;
        if (w <= 0) return null;
        const cls = "ch-seg t-" + (s.tone || "neutral")
          + (selected === s.key ? " on" : "")
          + (onSelect ? " tap" : "");
        const title = `${s.label}: ${s.value.toLocaleString("en-US")} (${w.toFixed(1)}%)`;
        return onSelect ? (
          <button key={s.key} className={cls} style={{ width: `${w}%` }} title={title}
                  onClick={() => onSelect(s.key)} aria-pressed={selected === s.key}>
            {w > 7 && <span className="ch-seg-n num">{s.value.toLocaleString("en-US")}</span>}
          </button>
        ) : (
          <span key={s.key} className={cls} style={{ width: `${w}%` }} title={title}>
            {w > 7 && <span className="ch-seg-n num">{s.value.toLocaleString("en-US")}</span>}
          </span>
        );
      })}
    </div>
  );
}

export function Legend({ segments, fmt }: {
  segments: Segment[];
  fmt?: (n: number) => string;
}) {
  return (
    <div className="ch-legend">
      {segments.filter((s) => s.value).map((s) => (
        <span className="ch-lg" key={s.key}>
          <i className={"ch-sw t-" + (s.tone || "neutral")} />
          {s.label}
          <b className="num">{(fmt || sar)(s.value)}</b>
        </span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ ranked, never stacked
/** Exceptions by value, as separate bars that deliberately do not stack.
 *
 *  The shape is the argument. Several of these rest on the same records — the same money read
 *  through a second comparison, or measured again in the taxable amount beneath its VAT — so a
 *  stacked bar or a running total would draw a figure corresponding to nothing. Each stands on
 *  its own baseline, and the note says why. */
export function RankedBars({ rows, note }: {
  rows: { key: string; label: string; sub?: string; value: number }[];
  note?: string;
}) {
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <div className="ch-chart">
      <div className="ch-hbars">
        {rows.map((r) => (
          <div className="ch-hbar" key={r.key}>
            <span className="ch-hbar-l">
              {r.label}
              {r.sub && <i>{r.sub}</i>}
            </span>
            <span className="ch-hbar-track">
              <span className="ch-hbar-fill differ"
                    style={{ width: `${(Math.abs(r.value) / max) * 100}%` }} />
            </span>
            <span className="ch-hbar-v num">{sar(r.value)}</span>
          </div>
        ))}
      </div>
      {note && <p className="ch-note">{note}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ over the period
/** Records per tax period, across the whole period under audit.
 *
 *  Months with nothing in them are drawn as empty columns rather than left out, because the
 *  empty column *is* the finding: a register that stops six weeks before the period ends looks
 *  entirely healthy in every total, and the sum is simply short by whatever is in the gap.
 *
 *  A record whose date could not be read is counted apart. It is not "no invoice that month" —
 *  it is an invoice whose month is unknown, and folding the two together would invent a gap or
 *  hide one. */
export function PeriodBars({ series, from, to, undated }: {
  series: { period: string | null; count: number; total: number }[];
  from: string;
  to: string;
  undated?: number;
}) {
  const months: string[] = [];
  const start = new Date(from + "T00:00:00Z");
  const end = new Date(to + "T00:00:00Z");
  const cur = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1));
  while (cur <= end && months.length < 36) {
    months.push(`${cur.getUTCFullYear()}-${String(cur.getUTCMonth() + 1).padStart(2, "0")}`);
    cur.setUTCMonth(cur.getUTCMonth() + 1);
  }
  const by = new Map(series.filter((s) => s.period).map((s) => [s.period as string, s]));
  const max = Math.max(...months.map((m) => by.get(m)?.count ?? 0), 1);
  const empty = months.filter((m) => !by.get(m)?.count);

  return (
    <div className="ch-chart">
      <div className="ch-vbars">
        {months.map((m) => {
          const s = by.get(m);
          const n = s?.count ?? 0;
          return (
            <div className={"ch-vbar" + (n ? "" : " none")} key={m}
                 title={n ? `${m}: ${n} record(s), ${sar(s!.total)}` : `${m}: no records`}>
              <span className="ch-vbar-n num">{n || ""}</span>
              <span className="ch-vbar-track">
                <span className="ch-vbar-fill" style={{ height: `${(n / max) * 100}%` }} />
              </span>
              <span className="ch-vbar-l">{m.slice(5)}</span>
            </div>
          );
        })}
      </div>
      <p className="ch-note">
        {empty.length
          ? <>Records by month across the period. <b>{empty.join(", ")}</b>{" "}
              {empty.length === 1 ? "carries" : "carry"} no record at all — a total over this
              file is short by whatever belongs there, and no comparison downstream can tell
              that from an under-declaration.</>
          : <>Records by month across the period. Every month under audit carries records.</>}
        {!!undated && <> {undated} record(s) carry no readable date and are counted apart from
          the months rather than assigned to one.</>}
      </p>
    </div>
  );
}
