import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  decideHypothesis,
  getInvestigationState,
  requestInformation,
  runInvestigation,
  type DecisionKind,
  type HypothesisStatus,
  type InvestigationState,
  type StoredHypothesis,
} from "../api";
import ConfidenceBadge from "./ConfidenceBadge";
import CitationNote from "./CitationNote";
import DecisionControls from "./DecisionControls";

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

/** What the agents proposed, what the engine settled, and what the auditor decided. */
export default function InvestigationPanel({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<InvestigationState | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);
  const [askNote, setAskNote] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    if (!id) return;
    setD(null);
    setOpen(null);
    getInvestigationState(id).then(setD).catch(() => {});
  }, [id, rev]);

  const decide = async (hid: string, decision: DecisionKind, comment: string) => {
    if (!id) return;
    setBusy(hid);
    try {
      setD(await decideHypothesis(id, hid, decision, comment));
    } catch {
      /* the panel keeps its last good state rather than blanking on a failed write */
    } finally {
      setBusy(null);
    }
  };

  // The loop. An investigation that cannot settle a hypothesis on what it holds should say
  // what it needs rather than present itself as finished — so this parks the hypothesis, opens
  // an enquiry carrying its id, and hands the auditor a draft to edit and send.
  const askTaxpayer = async (hid: string) => {
    if (!id) return;
    setBusy(hid);
    try {
      await requestInformation(id, hid, askNote.trim());
      setAsking(null);
      setAskNote("");
      nav(`/cases/${id}/correspondence`);
    } catch {
      setD(await getInvestigationState(id));
    } finally {
      setBusy(null);
    }
  };

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

  const row = (h: StoredHypothesis) => {
    const isOpen = open === h.hypothesis_id;
    return (
      <div className={"hyp" + (h.stale ? " stale" : "")} key={h.hypothesis_id}>
        <div>
          <div className="hid">{h.hypothesis_id}</div>
          {h.reason_code && <span className="rc">{h.reason_code}</span>}
        </div>
        <div>
          <div className="agent">
            {h.agent}
            {h.stale && " · no longer proposed"}
          </div>
          {h.claim}

          {h.why && (
            <div className="hyp-why">
              <b>Why raised</b> {h.why}
            </div>
          )}

          <div className={"verdict verdict-" + h.status}>
            <b>{STATUS_WORD[h.status]}</b>
            {h.explanation ? " — " + h.explanation : ""}
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

          <button
            className="linklike hyp-more"
            onClick={() => setOpen(isOpen ? null : h.hypothesis_id)}
          >
            {isOpen ? "hide the test" : "how it was tested"}
          </button>
          {isOpen && (
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
          )}

          <DecisionControls
            decision={h.decision}
            busy={busy === h.hypothesis_id}
            claim={h.claim}
            onDecide={(dec, comment) => decide(h.hypothesis_id, dec, comment)}
          />

          {h.status === "pending-info" ? (
            <div className="callout warn" style={{ margin: "8px 0 0" }}>
              <b>Waiting on the taxpayer.</b>{" "}
              {h.needs_info_note || "Information has been requested to settle this."} Re-run the
              investigation once it arrives.
            </div>
          ) : asking === h.hypothesis_id ? (
            <div className="decision open">
              <input
                className="decision-comment"
                placeholder="What do you need from the taxpayer, and why?"
                value={askNote}
                onChange={(e) => setAskNote(e.target.value)}
              />
              <div className="resp-actions">
                <button className="btn" onClick={() => askTaxpayer(h.hypothesis_id)}
                        disabled={busy === h.hypothesis_id}>
                  {busy === h.hypothesis_id ? "Opening…" : "Draft the request"}
                </button>
                <button className="linklike" onClick={() => setAsking(null)}>cancel</button>
              </div>
            </div>
          ) : (
            <button className="linklike" style={{ marginTop: 7 }}
                    onClick={() => { setAsking(h.hypothesis_id); setAskNote(""); }}>
              ✉ Request information from the taxpayer
            </button>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          <span className={"pill " + STATUS_PILL[h.status]}>
            {h.status.replace(/-/g, " ")}
          </span>
          <ConfidenceBadge confidence={h.confidence} />
          {!!h.amount && <div className="amt2">{sar(h.amount)}</div>}
        </div>
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
