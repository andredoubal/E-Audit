import { useEffect, useState } from "react";
import { getInvestigationSummary, type InvestigationSummary as Data, type SummaryCard } from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

/** What kind of thing each card is — and the word matters more than the styling.
 *
 *  "Observed" is a measurement over the documents. "Not settled" is the checker saying it could
 *  not answer, which is a real verdict and not a weak finding. "Records defect" is a fault in
 *  the file itself with no amount claimed. None of the three is a determination that tax is due;
 *  that is the auditor's, further down the page. */
const KIND: Record<SummaryCard["kind"], { label: string; cls: string }> = {
  observation: { label: "Observed", cls: "obs" },
  unresolved: { label: "Not settled", cls: "open" },
  "data-quality": { label: "Records defect", cls: "rec" },
};

function Card({ c }: { c: SummaryCard }) {
  const k = KIND[c.kind];
  return (
    <article className={"sumcard " + k.cls}>
      <header>
        <span className={"sumkind " + k.cls}>{k.label}</span>
        {!!c.amount && <span className="sumamt">{sar(c.amount)}</span>}
      </header>
      <h3>{c.title}</h3>
      <p className="sumobs">{c.observed}</p>

      {c.reading && (
        <p className="sumread">
          <span className="k">{c.kind === "data-quality" ? "Why it matters" : "What it may mean"}</span>
          {c.reading}
        </p>
      )}

      {c.alternatives.length > 0 && (
        <details className="sumalt">
          <summary>
            The same evidence also reads {c.alternatives.length} other way
            {c.alternatives.length === 1 ? "" : "s"}
          </summary>
          <ul>
            {c.alternatives.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <p className="sub">
            One matter, one amount. These are readings of the same evidence, not separate money.
          </p>
        </details>
      )}

      <footer>
        {c.decision ? (
          <span className="sub" style={{ color: "var(--brand)" }}>
            {c.decision === "accepted" ? "Confirmed by you"
              : c.decision.replace(/-/g, " ") + " by you"}
          </span>
        ) : (
          c.confidence && <span className="sub">{c.confidence} confidence</span>
        )}
        {!!c.hypothesis_ids.length && (
          <span className="mono">{c.hypothesis_ids.join(" · ")}</span>
        )}
      </footer>
    </article>
  );
}

/** The investigation in a handful of cards — the primary view of this module. */
export default function InvestigationSummary({ id, rev }: { id: string; rev?: number }) {
  const [d, setD] = useState<Data | null>(null);

  useEffect(() => {
    setD(null);
    getInvestigationSummary(id).then(setD).catch(() => {});
  }, [id, rev]);

  if (!d) return <p className="muted">Investigating…</p>;

  const t = d.totals;

  return (
    <>
      <div className="modulehead">
        <h2 className="display">What the evidence shows</h2>
        <span
          className="sub"
          title="Agents propose typed tests; a deterministic adjudicator settles them. No model states a figure, and no model reaches a conclusion."
        >
          {t.observations} observed
          {!!t.unresolved && ` · ${t.unresolved} not settled`}
          {!!t.record_defects && ` · ${t.record_defects} records defect`}
          {!!t.not_supported && ` · ${t.not_supported} tested, not supported`}
        </span>
        {!!t.at_stake && (
          <span className="sub modulehead-act num">{sar(t.at_stake)} at stake</span>
        )}
      </div>

      <div>
        {!d.cards.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            Nothing was raised against the documents on file. Where a test could not be run the
            reason is in the detail below — a column that is not there cannot be tested, and
            saying so beats an answer computed from nothing.
          </p>
        ) : (
          <>
            <div className="sumcards">
              {d.cards.map((c) => (
                <Card key={c.key} c={c} />
              ))}
            </div>

            <p className="detail-note" style={{ marginTop: 14 }}>
              Each amount is counted once against the evidence it rests on. Nothing here is a
              proposed adjustment — only what you confirm below reaches the report.
            </p>
          </>
        )}
      </div>
    </>
  );
}
