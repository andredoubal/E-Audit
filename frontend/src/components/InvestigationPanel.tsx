import { useEffect, useState } from "react";
import {
  getInvestigationState,
  runInvestigation,
  type HypothesisStatus,
  type InvestigationState,
  type StoredHypothesis,
} from "../api";
import ConfidenceBadge, { BAND_CLASS } from "./ConfidenceBadge";
import CitationNote from "./CitationNote";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const STATUS_PILL: Record<HypothesisStatus, string> = {
  supported: "pri-low",
  "partially-supported": "pri-medium",
  refuted: "status",
  inconclusive: "pri-medium",
  "pending-info": "pri-medium",
};
const STATUS_WORD: Record<HypothesisStatus, string> = {
  supported: "supported by the evidence",
  "partially-supported": "partly supported",
  refuted: "refuted",
  inconclusive: "cannot be tested",
  "pending-info": "waiting on the taxpayer",
};

/** What the agents proposed and how the engine settled it — the evidence behind the summary.
 *
 *  The auditor's ruling is not here. It used to be, once per hypothesis, which told the auditor
 *  they owed a separate decision on every piece of evidence; it is now one section at the foot
 *  of the page, where the position is actually taken. What a decision *was* still shows here,
 *  because a verdict is read differently once someone has ruled on it. */
export default function InvestigationPanel({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<InvestigationState | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);

  useEffect(() => {
    if (!id) return;
    setD(null);
    setOpen(null);
    getInvestigationState(id).then(setD).catch(() => {});
  }, [id, rev]);

  const rerun = async () => {
    if (!id) return;
    setRerunning(true);
    try {
      setD(await runInvestigation(id, "auditor-requested"));
    } catch {
      /* ignored — the existing view stays usable */
    } finally {
      setRerunning(false);
    }
  };

  const live = (d?.hypotheses ?? []).filter((h) => !h.stale);
  const stale = (d?.hypotheses ?? []).filter((h) => h.stale);
  const latest = d?.runs?.[d.runs.length - 1];

  /** One finding: a summary line, and the derivation behind a click.
   *
   *  It was all open at once — claim, why, verdict, citation, test, decision, ask-the-taxpayer
   *  — so twelve of them ran to nine screens and the list stopped being a summary. What is
   *  worth seeing at a glance is what was found, how strongly, and for how much. */
  const row = (h: StoredHypothesis) => {
    const isOpen = open === h.hypothesis_id;
    const decided = h.decision?.decision;
    return (
      <div className={"hyp" + (h.stale ? " stale" : "") + (isOpen ? " open" : "")}
           key={h.hypothesis_id}>
        <button className="hyp-summary"
                onClick={() => setOpen(isOpen ? null : h.hypothesis_id)}
                aria-expanded={isOpen}>
          <span className="hyp-mark">{isOpen ? "▾" : "▸"}</span>
          <span className="hyp-ids">
            <code>{h.hypothesis_id}</code>
            <span className="agent">{h.agent}{h.stale && " · no longer proposed"}</span>
          </span>
          <span className="hyp-claim">{h.claim}</span>
          <span className="hyp-right">
            <span className={"pill " + STATUS_PILL[h.status]}>{STATUS_WORD[h.status]}</span>
            {h.confidence?.band && (
              <span className={"pill " + (BAND_CLASS[h.confidence.band] || "status")}>
                {h.confidence.band} confidence
              </span>
            )}
            {!!h.amount && <span className="amt2">{sar(h.amount)}</span>}
            {decided && (
              <span className="pill status" title="You have already ruled on this">
                {decided.replace(/-/g, " ")}
              </span>
            )}
          </span>
        </button>

        {isOpen && (
          <div className="hyp-detail">
            {h.why && (
              <div className="hyp-why">
                <b>Why raised</b> {h.why}
              </div>
            )}

            <div className={"verdict verdict-" + h.status}>
              <b>{STATUS_WORD[h.status]}</b>
              {h.explanation ? " — " + h.explanation : ""}
            </div>

            <ConfidenceBadge confidence={h.confidence} />

            <div className="hyp-test">
              <div>
                <span className="k">Test run</span>
                <code>{h.test.kind}</code>
                <span className="sub"> on the {h.test.box} box</span>
              </div>
              {!!Object.keys(h.test.params || {}).length && (
                <div>
                  <span className="k">Against</span>
                  <code>
                    {Object.entries(h.test.params)
                      .map(([k, v]) => `${k}=${String(v)}`)
                      .join(", ")}
                  </code>
                </div>
              )}
              <div>
                <span className="k">First seen</span>
                run {h.first_seen_run} · last re-tested run {h.last_seen_run}
              </div>
              {h.outcome_code && (
                <div>
                  <span className="k">Reports as</span>
                  <code>{h.outcome_code}</code>
                </div>
              )}
            </div>

            <CitationNote c={h.regulatory} />

            {h.superseded_status && (
              <div className="callout warn" style={{ margin: "8px 0 0" }}>
                Previously <b>{h.superseded_status.replace(/-/g, " ")}</b>; re-adjudicated in run{" "}
                {h.superseded_at_run} against the evidence then on file.
              </div>
            )}

            {h.contradictions.map((c) => (
              <div className="callout warn" style={{ margin: "8px 0 0" }} key={c}>
                {c}
              </div>
            ))}

            {h.decision && (
              <div className="decision">
                <span className="pill pri-low">
                  {h.decision.decision.replace(/-/g, " ")} by you
                </span>
                {h.decision.needs_reconfirmation && (
                  <div className="callout warn" style={{ margin: "8px 0 0" }}>
                    <b>Re-confirm this.</b> The verdict moved after you decided — your ruling was
                    made against <code>{h.decision.decided_on_status}</code>.
                  </div>
                )}
                {h.decision.comment && (
                  <div className="sub decision-note">“{h.decision.comment}”</div>
                )}
              </div>
            )}

            {h.status === "pending-info" && (
              <div className="callout warn" style={{ margin: "8px 0 0" }}>
                <b>Waiting on the taxpayer.</b>{" "}
                {h.needs_info_note || "Information has been requested to settle this."} Re-run the
                investigation once it arrives.
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AGENTS</span>
          <h2>Investigation</h2>
        </div>
        <span
          className="pill status"
          title="Agents propose typed tests; a deterministic adjudicator settles them. No model states a figure, and no model decides."
        >
          ∑ Adjudicated (no AI)
        </span>
      </div>
      <div className="ai-body">
        {!d ? (
          <span className="muted">Investigating…</span>
        ) : (
          <>
            {latest && <p className="inv-conc">{latest.conclusion}</p>}

            <div className="inv-round">
              {d.runs.length} run{d.runs.length === 1 ? "" : "s"} · {d.counts.total} hypotheses ·{" "}
              {d.counts.decided} decided · {d.counts.accepted} accepted
              {d.counts.needs_reconfirmation > 0 && (
                <>
                  {" · "}
                  <b>{d.counts.needs_reconfirmation} need re-confirming</b>
                </>
              )}
              <button
                className="linklike"
                style={{ marginLeft: 12 }}
                onClick={rerun}
                disabled={rerunning}
                title="Re-adjudicate every hypothesis against the evidence now on file"
              >
                {rerunning ? "re-running…" : "↻ investigate again"}
              </button>
            </div>

            {live.map(row)}

            {stale.length > 0 && (
              <>
                <div className="inv-round" style={{ marginTop: 14 }}>
                  No longer proposed — kept because the question was asked
                </div>
                {stale.map(row)}
              </>
            )}

            {!d.hypotheses.length && (
              <p className="detail-note">
                No hypothesis was raised. Nothing in the evidence on file matched a test the
                roster can run.
              </p>
            )}

            <p className="detail-note" style={{ margin: "12px 0 0" }}>
              Every verdict above was settled by the engine against the case's own figures. The
              audit conclusion is the auditor's: only what you accept reaches the report.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
