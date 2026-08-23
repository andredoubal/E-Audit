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

const BAND: Record<string, string> = {
  Strong: "pri-low",
  Moderate: "pri-medium",
  Limited: "pri-medium",
  Insufficient: "status",
};

function Card({ c }: { c: SummaryCard }) {
  const k = KIND[c.kind];
  return (
    <article className={"sumcard " + k.cls}>
      <header>
        <span className={"sumkind " + k.cls}>{k.label}</span>
        <h3>{c.title}</h3>
        {!!c.amount && <b className="sumamt">{sar(c.amount)}</b>}
      </header>

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
        {c.confidence && (
          <span className={"pill " + (BAND[c.confidence] || "status")}>
            {c.confidence} confidence
          </span>
        )}
        {c.decision ? (
          <span className="pill pri-low">{c.decision.replace(/-/g, " ")} by you</span>
        ) : (
          <span className="sub">requires your validation</span>
        )}
        {!!c.hypothesis_ids.length && (
          <span className="sub mono">{c.hypothesis_ids.join(" · ")}</span>
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

  if (!d) {
    return (
      <div className="panel">
        <div className="panel-head">
          <h2>Investigation summary</h2>
        </div>
        <div className="panel-body">
          <span className="muted">Investigating…</span>
        </div>
      </div>
    );
  }

  const t = d.totals;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Investigation summary</h2>
        <span
          className="pill status"
          title="Agents propose typed tests; a deterministic adjudicator settles them. No model states a figure, and no model reaches a conclusion."
        >
          ∑ Adjudicated (no AI)
        </span>
      </div>

      <div className="panel-body">
        {!d.cards.length ? (
          <p className="detail-note" style={{ margin: 0 }}>
            Nothing was raised against the documents on file. Where a test could not be run the
            reason is in the detail below — a column that is not there cannot be tested, and
            saying so beats an answer computed from nothing.
          </p>
        ) : (
          <>
            <div className="sumbar">
              <span>
                <b>{t.observations}</b> observed
              </span>
              {!!t.unresolved && (
                <span>
                  <b>{t.unresolved}</b> not settled
                </span>
              )}
              {!!t.record_defects && (
                <span>
                  <b>{t.record_defects}</b> records defect{t.record_defects === 1 ? "" : "s"}
                </span>
              )}
              {!!t.not_supported && (
                <span className="muted">
                  <b>{t.not_supported}</b> tested, not supported
                </span>
              )}
              {!!t.at_stake && (
                <span className="sumbar-amt">
                  <b>{sar(t.at_stake)}</b> at stake
                </span>
              )}
            </div>

            <div className="sumcards">
              {d.cards.map((c) => (
                <Card key={c.key} c={c} />
              ))}
            </div>

            <p className="detail-note">
              Each amount is counted once against the evidence it rests on, so nothing here is
              the same money twice — but this is <b>not a proposed adjustment</b>. Everything
              above is an observation for you to validate; what you conclude is yours to write at
              the foot of this page, and only what you accept reaches the report.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
