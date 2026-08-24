import { useEffect, useState } from "react";
import {
  getDashboard,
  type CompareCard,
  type Comparison,
  type CompareSide,
  type MatchRow,
  type MatrixRow,
  type ReconDashboard,
  type ReconException,
  type ReconObservation,
  type WorkstreamDash,
} from "../api";
import { FileReturn, Hash, Info, Ledger, Minus, Shield, Stamp, Tag, Warn } from "./Icon";
import { Legend, ProportionBar, RankedBars, SourceBars,
         type Segment, type SourceBar } from "./Charts";

const sar = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const plain = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—" : Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const signed = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : (n < 0 ? "−" : "") + sar(n);

/** Inside the dashboard tables the currency is stated once, in the header, and left off every
 *  cell. Four columns of "SAR 17,453,333" is the same three characters repeated forty times,
 *  and the width it costs is the width the variance column needed. */
const bare = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : (n < 0 ? "−" : "") + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : `${(Math.abs(n) * 100).toFixed(2)}%`;

/** Colour says *how settled the comparison is*, never how bad the taxpayer is. */
const STATUS_CLASS: Record<string, string> = {
  reconciled: "pri-low",
  "reconciled-with-explained-difference": "pri-low",
  "partially-reconciled": "pri-medium",
  "variance-identified": "pri-high",
  "insufficient-evidence": "status",
};

/** A variance cell: the figure, which way it runs, and how settled the comparison is.
 *
 *  **The colour is never taken from the sign.** S2 compares e-invoices against the return and
 *  S3 compares the return against the register, so one under-declaration of SAR 618,000 is
 *  positive in one card and negative in the other — colouring by sign painted the same fact
 *  red in one and green in the other, which is worse than no colour at all. Colour therefore
 *  comes from the engine's status, exactly as it does on every pill in the application: it
 *  says how settled the comparison is, not how bad the taxpayer is.
 *
 *  The arrow keeps the direction, which is real information — it says which of the two named
 *  sources is the higher, and the auditor decides what that means. */
function Var({ v, pctv, status }: {
  v: number | null; pctv?: number | null; status?: string;
}) {
  if (v === null || v === undefined) return <span className="muted">&mdash;</span>;
  if (v === 0) return <span className="var zero num">0</span>;
  const tone = status === "variance-identified" ? " off"
    : status === "partially-reconciled" ? " part"
    : status ? " ok" : "";
  return (
    <span className={"var num" + tone}>
      {bare(v)}
      <i title={v > 0 ? "the first source is higher" : "the second source is higher"}>
        {v > 0 ? "▲" : "▼"}
      </i>
      {pctv !== undefined && pctv !== null && <em>{pct(pctv)}</em>}
    </span>
  );
}

// ------------------------------------------------------------------ KPI row
/** The headline figures, one card each, with an icon saying what kind of thing it is.
 *
 *  Built from what the case actually has: a card for a dataset that is not there would read
 *  zero, which is a lie, or sit empty, which teaches the eye to skip the row. Which cards
 *  exist is therefore a fact about the evidence, and the reasons for the absent ones are
 *  published under the comparisons rather than left as a gap. */
function Kpis({ w, workstream }: { w: WorkstreamDash; workstream: string }) {
  const pick = (key: string) => w.kpis.find((k) => k.key === key);
  const vatWord = workstream === "sales" ? "Output VAT" : "Input VAT";

  const card = (key: string, icon: JSX.Element, title: string,
                headKey: string, subKey?: string, subLabel?: string) => {
    const head = pick(headKey);
    if (!head) return null;
    const sub = subKey ? pick(subKey) : undefined;
    return (
      <div className="kpic" key={key}>
        <span className="kpic-ic">{icon}</span>
        <span className="kpic-body">
          <span className="kpic-t">{title}</span>
          <b className="kpic-n num">
            {head.unit === "sar" ? sar(head.value) : plain(head.value)}
          </b>
          {sub ? (
            <span className="kpic-s">
              {subLabel || sub.label}
              <b className="num">{sub.unit === "sar" ? sar(sub.value) : plain(sub.value)}</b>
            </span>
          ) : head.source ? (
            <span className="kpic-src">{head.source}</span>
          ) : null}
        </span>
      </div>
    );
  };

  const cards = [
    card("ret", <FileReturn />, "VAT return — declared", "declared_base",
         "declared_vat", vatWord),
    card("reg", <Ledger />, "Register — the taxpayer’s", "register_base",
         "register_vat", vatWord),
    card("ein", <Stamp />, "E-invoices — the Authority’s", "einvoices_base",
         "einvoices_vat", vatWord),
    card("regcnt", <Hash />, "Records on the register", "register_count"),
    card("eincnt", <Hash />, "Invoices on the extract", "einvoices_count"),
    card("notes", <Minus />, "Credit and debit notes", "register_notes_count",
         "register_notes_value", "VAT"),
    card("zero", <Tag />, "Zero-rated records", "register_zero-rated_count",
         "register_zero-rated_base", "Taxable"),
    card("exempt", <Shield />, "Exempt records", "register_exempt_count",
         "register_exempt_base", "Taxable"),
  ].filter(Boolean);

  if (!cards.length) return null;
  return <div className="kpics">{cards}</div>;
}

// ------------------------------------------------------------------ one comparison card
/** One pairing, stated in every metric the evidence supports, with the transaction level
 *  summarised beneath it.
 *
 *  Three of these side by side is the shape of the whole question: the same money as the
 *  taxpayer's own listing, the Authority's invoice records and the filed return each have it.
 *  Which *pair* disagrees is the only thing that changes what the auditor does next, so each
 *  card carries the question it answers rather than only a title. */
function CompareCardView({ c, open, onOpen }: {
  c: CompareCard; open: boolean; onOpen: () => void;
}) {
  if (!c.runnable) {
    return (
      <div className="ccard blocked">
        <div className="ccard-head">
          <b>{c.code}. {c.title}</b>
          <span className="pill status">Not run</span>
        </div>
        <p className="ccard-blocked">
          {c.blocked_by.join("; ")}. Reported rather than run against whatever happens to be on
          the case: one side is not a comparison.
        </p>
      </div>
    );
  }
  return (
    <div className={"ccard" + (open ? " on" : "")}>
      <div className="ccard-head">
        <b>{c.code}. {c.title}</b>
        <button className="linklike" onClick={onOpen}>
          {open ? "hide details" : "View details ›"}
        </button>
      </div>
      <p className="ccard-q">{c.question}</p>
      <table className="ctable">
        <thead>
          <tr>
            <th />
            <th className="r">{c.a_label}</th>
            <th className="r">{c.b_label}</th>
            <th className="r">Variance</th>
          </tr>
        </thead>
        <tbody>
          {c.rows.map((r) => (
            <tr key={r.metric}>
              <td>{r.label}</td>
              <td className="r num">{bare(r.a)}</td>
              <td className="r num">{bare(r.b)}</td>
              <td className="r">
                <Var v={r.variance} pctv={r.variance_pct} status={r.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!!c.strip.length && (
        <div className="cstrip">
          {c.strip.map((s) => (
            <div className={"cbox" + (s.key === "matched" ? " good" : "")} key={s.key}>
              <b className="num">{plain(s.count)}</b>
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      )}
      <div className="ccard-foot">
        <span className={"pill " + (STATUS_CLASS[c.status] || "status")}>{c.status_label}</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the return, box by box
const EVIDENCE_WORD: Record<string, string> = {
  "records": "register & e-invoices",
  "customs-import": "customs import declarations",
  "customs-export": "customs export declarations",
  "nothing": "nothing on this case",
  "computed": "computed",
};

/** Every box the return declares, against whatever evidences it.
 *
 *  The rows are the **return's own boxes**, not our canonical treatments. Those are two
 *  vocabularies and conflating them loses precisely what an auditor looks for: the return keeps
 *  15% apart from 5%, imports cleared at customs apart from imports under reverse charge, and
 *  domestic zero-rated apart from exports, and a row per treatment merges every one of those
 *  pairs.
 *
 *  Three kinds of row, and the difference is the point. A box evidenced by the records carries
 *  a real variance. A box evidenced by customs is compared on its **base** only, because a
 *  declaration states a value in SAR and no tax. A **declared-only** box carries no variance at
 *  all and says why: comparing it against an absent population would report the entire
 *  declaration as a difference. */
function Matrix({ m, name }: { m: WorkstreamDash["matrix"]; name: string }) {
  const [showAr, setShowAr] = useState(false);
  if (!m.rows.length) return null;

  const cell = (v: number | null, muted = false) =>
    v === null
      ? <span className="muted" title="not declared, which is not a declaration of zero">
          &mdash;</span>
      : <span className={"num" + (muted ? " muted" : "")}>{bare(v)}</span>;

  const row = (r: MatrixRow, total = false) => {
    const dim = r.declared_only;
    return (
      <tr key={r.code}
          className={(total ? "totalrow" : "") + (dim ? " declared-only" : "")
            + (r.unallocated ? " unalloc" : "")}>
        <td>
          <span className="bx">{showAr && r.label_ar ? r.label_ar : r.label}</span>
          {!total && (
            <i className="bx-ev" title={r.why_unevidenced || undefined}>
              {EVIDENCE_WORD[r.evidenced_by] || r.evidenced_by}
              {dim && " — declared only"}
            </i>
          )}
        </td>
        <td className="r">{cell(r.declared_base)}</td>
        <td className="r">{cell(r.declared_adjustment, true)}</td>
        <td className="r">{cell(r.declared_vat)}</td>
        <td className="r">{cell(r.register_base)}</td>
        <td className="r">{cell(r.register_vat)}</td>
        <td className="r">{cell(r.einvoice_base)}</td>
        <td className="r">{cell(r.einvoice_vat)}</td>
        <td className="r"><Var v={r.reg_vs_einvoice} /></td>
        <td className="r"><Var v={r.einvoice_vs_declared} /></td>
        <td className="r"
            title={r.variance_metric === "taxable"
              ? "compared on the taxable amount: a customs declaration states a value in SAR "
                + "and never the tax on it"
              : undefined}>
          <Var v={r.declared_vs_reg} />
          {r.variance_metric === "taxable" && r.declared_vs_reg !== null && (
            <i className="vm">base</i>
          )}
        </td>
      </tr>
    );
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{name} — the return, box by box</h2>
        <span className="sub">{m.rows.length} boxes &middot; all amounts in SAR</span>
        <button className="linklike" style={{ marginLeft: "auto" }}
                onClick={() => setShowAr((a) => !a)}>
          {showAr ? "English" : "عربي"}
        </button>
      </div>
      <div className="tablewrap">
        <table className="dtable mtable">
          <thead>
            <tr className="grouprow">
              <th />
              <th colSpan={3} className="grp">VAT return &mdash; declared</th>
              <th colSpan={2} className="grp">Primary record</th>
              <th colSpan={2} className="grp">E-invoices &mdash; the Authority&rsquo;s</th>
              <th colSpan={3} className="grp last">Variance</th>
            </tr>
            <tr>
              <th>Box</th>
              <th className="r">Applied</th><th className="r">Adjustment</th>
              <th className="r">VAT</th>
              <th className="r">Taxable</th><th className="r">VAT</th>
              <th className="r">Taxable</th><th className="r">VAT</th>
              <th className="r">Reg &harr; E-inv</th>
              <th className="r">E-inv &harr; Return</th>
              <th className="r">Return &harr; Reg</th>
            </tr>
          </thead>
          <tbody>
            {m.rows.map((r) => row(r))}
            {row(m.total, true)}
          </tbody>
        </table>
      </div>
      <div className="panel-note">
        <span className="ct">empty &ne; zero</span> A blank cell means the box was not declared,
        or that side holds nothing for it &mdash; neither is a declaration of zero.
        &ldquo;Primary record&rdquo; is the register for most boxes and the <b>customs
        declarations</b> for imports and exports; each row says which. Those two populations are
        not added together, so the column total states the register alone.
        {!!m.declared_only_count && ` ${m.note}`}
        {!!m.unallocated_count && (
          <> <b>Records the return has no box for</b> carries {m.unallocated_count} record(s)
          charged at a rate no box declares. It is a visible row rather than a silent loss:
          without it the columns would not foot to the totals above.</>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ observations rail
function ObservationRail({ observations, exceptions, workstream }: {
  observations: ReconObservation[];
  exceptions: ReconException[];
  workstream: string;
}) {
  const [all, setAll] = useState(false);
  const mine = observations.filter((o) => o.workstream === workstream);
  if (!mine.length) return null;
  const material = new Set(
    exceptions.filter((e) => e.kind !== "comparison-not-possible").map((e) => e.id));
  // The ones behind an exception first: those are what the investigation works from, and a
  // rail that opens with six restatements of a total nobody disputes is a rail nobody reads.
  const ordered = [...mine].sort(
    (a, b) => Number(material.has(b.id)) - Number(material.has(a.id)));
  const shown = all ? ordered : ordered.slice(0, 8);
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Descriptive observations</h2>
        <span className="sub">{mine.length}</span>
        {ordered.length > 8 && (
          <button className="linklike" style={{ marginLeft: "auto" }}
                  onClick={() => setAll((a) => !a)}>
            {all ? "show fewer" : `View all ${ordered.length} ›`}
          </button>
        )}
      </div>
      <ul className="obsrail">
        {shown.map((o) => (
          <li key={o.id} className={material.has(o.id) ? "warn" : ""}>
            <span className="obsrail-ic">{material.has(o.id) ? <Warn /> : <Info />}</span>
            <span>{o.text}</span>
          </li>
        ))}
      </ul>
      <div className="panel-note">
        <span className="ct">&sum; computed</span> Counts and sums over the records on file.
        They say what differs, never why &mdash; that is the next tab, and it is proposed
        rather than concluded.
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ level 3 drill-down
const MATCH_ORDER = [
  "a-only", "b-only", "value-mismatch", "vat-mismatch", "treatment-mismatch",
  "period-mismatch", "date-mismatch", "duplicate", "missing-identifier", "exact-match",
];

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
                    <td className="mono">
                      {m.reference || <span className="muted">none</span>}
                    </td>
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

/** The detail behind one card. Opened from the card rather than shown beside it: three cards'
 *  worth of this at once is a page nobody reads. */
function CardDetail({ code, comparisons, onClose }: {
  code: string;
  comparisons: Comparison[];
  onClose: () => void;
}) {
  const group = comparisons.filter((c) => c.code === code);
  const c = group.find((x) => x.metric === "vat") || group[0];
  if (!c) return null;
  return (
    <div className="drill">
      <div className="drill-head">
        <b>{c.code} &middot; {c.title}</b>
        <button className="linklike" onClick={onClose}>close</button>
      </div>
      <p className="detail-note" style={{ marginTop: 0 }}>
        Measured in <b>{c.metric_label}</b>. Tolerance for this comparison is{" "}
        {sar(c.tolerance.allowance)} &mdash; {c.tolerance.note}.
      </p>
      {c.notes.map((n, i) => <p className="cmp-note" key={i}>{n}</p>)}

      {!!c.treatments.length && (
        <div className="ch-splits">
          {([["a", c.a] as const, ["b", c.b] as const]).map(([which, side]) => {
            const segs: Segment[] = c.treatments.map((t) => ({
              key: t.treatment, label: t.label,
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
            key: t.treatment, label: t.label, value: Math.abs(t.variance || 0),
            tone: t.treatment === "standard-rated" ? "agree"
              : t.treatment === "unclassified" ? "warn" : "neutral",
          }))} />
          <p className="ch-note">
            Each bar is one source&rsquo;s own composition; the legend carries the difference
            between them per treatment.
          </p>
        </div>
      )}

      <h4 className="lvl">By transaction</h4>
      <Transactions c={c} />
    </div>
  );
}

// ------------------------------------------------------------------ one workstream
function WorkstreamDashboard({ w, name, comparisons, observations, exceptions, workstream }: {
  w: WorkstreamDash;
  name: string;
  comparisons: Comparison[];
  observations: ReconObservation[];
  exceptions: ReconException[];
  workstream: string;
}) {
  const [drill, setDrill] = useState<string | null>(null);
  const s = w.summary;

  const vat = comparisons.filter((c) => c.metric === "vat");
  const sideOf = (src: CompareSide["source"]) => {
    for (const c of vat) {
      if (c.a.source === src && c.a.present) return c.a;
      if (c.b.source === src && c.b.present) return c.b;
    }
    return null;
  };
  const registerLabel = workstream === "sales" ? "Sales register" : "Purchase register";
  const sources: SourceBar[] = ([
    ["register", registerLabel, "the taxpayer’s own listing",
     `no ${registerLabel.toLowerCase()} on the case`],
    ["e-invoices", "E-invoices", "the Authority’s extract",
     "no e-invoice extract for this side on the case"],
    ["vat-return", "VAT return", "as filed", "no return on file for this period"],
  ] as const).map(([key, label, origin, missing]) => {
    const side = sideOf(key);
    return {
      key, label, value: side?.total ?? null, origin: side?.origin || origin,
      present: !!side && side.total !== null, missing,
    };
  });

  const mine = exceptions.filter((e) => e.workstream === workstream);
  const ranked = [...mine].filter((e) => e.metric === "vat" && e.variance);

  return (
    <>
      <div className="dashhead">
        <h2>{name}</h2>
        <span className="sub num">
          {s.comparisons_run} of {s.comparisons_total} comparisons run
          {s.with_variance ? ` · ${s.with_variance} with a variance` : ""}
          {" · all amounts in SAR"}
        </span>
      </div>

      <Kpis w={w} workstream={workstream} />

      {/* The three pairings side by side: the same money as the taxpayer's listing, the
          Authority's records and the filed return each have it. */}
      <div className="ccards">
        {w.cards.map((c) => (
          <CompareCardView key={c.code} c={c} open={drill === c.code}
                           onOpen={() => setDrill(drill === c.code ? null : c.code)} />
        ))}
      </div>

      {drill && (
        <CardDetail code={drill} comparisons={comparisons} onClose={() => setDrill(null)} />
      )}

      <div className="dashgrid">
        <Matrix m={w.matrix} name={workstream === "sales" ? "Sales" : "Purchases"} />
        <ObservationRail observations={observations} exceptions={mine}
                         workstream={workstream} />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Where the difference sits</h2>
          {!!s.largest_exception && (
            <span className="sub num">
              largest single exception {sar(s.largest_exception)}
            </span>
          )}
        </div>
        <div className="ch-row">
          <SourceBars
            title="What each source says this period is worth, in VAT"
            bars={sources}
            note="One scale, so the outlier is the one that stands out. A source not on the
                  case has no bar rather than a bar of nothing &mdash; a zero-length bar would
                  say the taxpayer declared nothing, which is a different claim entirely."
          />
        </div>
        {!!ranked.length && (
          <div className="ch-row">
            <RankedBars
              rows={ranked
                .sort((a, b) => Math.abs(b.variance || 0) - Math.abs(a.variance || 0))
                .slice(0, 8)
                .map((e) => ({ key: e.id, label: e.category,
                               sub: `${e.reconciliation}${e.affected_count
                                 ? ` · ${e.affected_count} record(s)` : ""}`,
                               value: e.variance || 0 }))}
              note="Ranked, not accumulated. These bars share a scale but not a baseline:
                    adding them would count the same records more than once, which is why the
                    dashboard publishes the largest single exception and never a total."
            />
          </div>
        )}
        {!!w.unavailable.length && (
          <div className="unavail">
            <span className="ct">not measured</span>
            <ul>
              {w.unavailable.map((u, i) => <li key={i}><b>{u.what}</b> &mdash; {u.why}</li>)}
            </ul>
          </div>
        )}
      </div>
    </>
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
        <span className="sub">{material.length} &mdash; what the investigation works from</span>
      </div>
      <div className="tablewrap">
        <table className="dtable">
          <thead>
            <tr>
              <th>Ref</th><th>Workstream</th><th>Reconciliation</th><th>Category</th>
              <th className="r">Records</th><th className="r">Value</th>
              <th>Also measured as</th>
            </tr>
          </thead>
          <tbody>
            {material.map((e) => (
              <tr key={e.id}>
                <td className="mono xs">{e.id}</td>
                <td>{e.workstream}</td>
                <td>{e.reconciliation}</td>
                <td>{e.category}</td>
                <td className="r num">{e.affected_count || "—"}</td>
                <td className="r num">{signed(e.variance)} <i className="xs">{e.metric}</i></td>
                <td className="xs">
                  {e.also_measured.length
                    ? e.also_measured.map((a) =>
                        `${signed(a.variance)} of ${a.metric_label.toLowerCase()}`).join("; ")
                    : <span className="muted">&mdash;</span>}
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
type View = "overview" | "sales" | "purchases";

export default function ReconciliationDashboard({ id, rev }: { id: string; rev?: number }) {
  const [d, setD] = useState<ReconDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<View>("overview");

  useEffect(() => { setD(null); setErr(null); }, [id]);
  useEffect(() => {
    let live = true;
    getDashboard(id)
      .then((j) => { if (live) { setD(j); setErr(null); } })
      .catch((e) => { if (live) setErr(String(e)); });
    return () => { live = false; };
  }, [id, rev]);

  if (err)
    return (
      <div className="panel">
        <div className="notice err">Could not build the dashboard &mdash; {err}</div>
      </div>
    );
  if (!d) return <p className="muted">Reconciling&hellip;</p>;

  const forWs = (ws: string) => d.comparisons.filter((c) => c.workstream === ws);
  const ws = (k: "sales" | "purchases") => (
    <WorkstreamDashboard
      w={d.workstreams[k]}
      name={k === "sales" ? "Sales — output VAT" : "Purchases — input VAT"}
      comparisons={forWs(k)} observations={d.observations} exceptions={d.exceptions}
      workstream={k}
    />
  );

  return (
    <>
      {/* Sales and purchases are two audits — opposite risks, different evidence,
          different provisions — so each gets the whole dashboard rather than a filter
          over a shared one. Overview is where they are seen against each other. */}
      <div className="dashtabs" role="tablist">
        {(["overview", "sales", "purchases"] as View[]).map((v) => (
          <button key={v} role="tab" aria-selected={view === v}
                  className={"dashtab" + (view === v ? " on" : "")}
                  onClick={() => setView(v)}>
            {v === "overview" ? "Overview"
              : v === "sales" ? "Sales dashboard" : "Purchases dashboard"}
          </button>
        ))}
        <span className="dashtabs-meta num">{d.period_from} &rarr; {d.period_to}</span>
      </div>

      {view === "overview" && (
        <>
          <div className="ovgrid">
            {(["sales", "purchases"] as const).map((k) => {
              const s = d.workstreams[k].summary;
              return (
                <div className="ovcard" key={k}>
                  <div className="ovcard-head">
                    <b>{k === "sales" ? "Sales — output VAT"
                       : "Purchases — input VAT"}</b>
                    <button className="linklike" onClick={() => setView(k)}>open &rsaquo;</button>
                  </div>
                  <div className="ovstats">
                    <span className="ovstat">
                      <b className="num">{s.comparisons_run}<i>/{s.comparisons_total}</i></b>
                      <span>comparisons run</span>
                    </span>
                    <span className={"ovstat" + (s.with_variance ? " hot" : "")}>
                      <b className="num">{s.with_variance}</b>
                      <span>with a variance</span>
                    </span>
                    <span className={"ovstat" + (s.exceptions ? " hot" : "")}>
                      <b className="num">{s.exceptions}</b>
                      <span>exceptions</span>
                    </span>
                  </div>
                  {!!s.largest_exception && (
                    <div className="ovlargest">
                      <b className="num">{sar(s.largest_exception)}</b>
                      <span>largest single exception &mdash; {s.largest_exception_is}</span>
                    </div>
                  )}
                  {s.not_summed_because && <p className="ovnote">{s.not_summed_because}</p>}
                </div>
              );
            })}
          </div>
          <Exceptions exceptions={d.exceptions} />
        </>
      )}

      {view === "sales" && ws("sales")}
      {view === "purchases" && ws("purchases")}
    </>
  );
}
