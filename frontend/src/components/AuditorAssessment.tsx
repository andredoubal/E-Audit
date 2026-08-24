import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  decideHypothesis,
  undecideHypothesis,
  getAssessment,
  getInvestigationSummary,
  requestInformation,
  saveAssessment,
  type AssessmentView,
  type InvestigationSummary,
  type SummaryCard,
} from "../api";
import { askAbout } from "../ai/ask";
import { Sparkles } from "./Icon";
import ModuleHandoff from "./ModuleHandoff";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

/** Instructions an auditor actually gives, offered as a starting point rather than a menu.
 *
 *  They go to the case assistant, which rewrites the assessment against the same engine-authored
 *  facts and the same verifier the first draft passed through — so an instruction can change how
 *  something is put, and cannot change a figure. */
const STEERS = [
  "Treat the largest difference as a timing difference and say why.",
  "Rewrite this using only what I have confirmed.",
  "Drop the matters where the evidence is insufficient.",
  "Say it in plainer language for a taxpayer with no adviser.",
];

/** What the auditor does with one matter. Three words, in one place, once.
 *
 *  These used to be five options on every hypothesis, which said the tool expected a separate
 *  ruling on each piece of evidence. It does not: the auditor reads the investigation and takes
 *  a position, and the only thing the report needs from them is which matters they confirm. */
/** "" reopens a matter — a ruling you cannot take back is one an auditor will not make. */
type Ruling = "accepted" | "rejected" | "needs-more-info" | "needs-more-investigation" | "";

/** Challenge sits between confirming and dismissing, because that is where the doubt sits.
 *
 *  Dismiss is a verdict: the matter is not supported and the file records that. Challenge is
 *  the auditor saying they do not accept the engine's reading *as it stands* and want to put it
 *  to the assistant first — which is a real position, and one the tool previously had no word
 *  for. It reuses `needs-more-investigation`, already in the decision vocabulary and already
 *  excluded from the report, so nothing new has to be defined or migrated. */
const RULINGS: { key: Exclude<Ruling, "">; label: string; hint: string; tone?: string }[] = [
  { key: "accepted", label: "Confirm", tone: "confirm",
    hint: "Carry this into the audit report as a finding" },
  { key: "needs-more-investigation", label: "Challenge", tone: "challenge",
    hint: "You do not accept this reading as it stands — records the challenge and opens the "
          + "assistant with the matter already in hand" },
  { key: "rejected", label: "Dismiss", hint: "Not supported — kept on file with your reason" },
  { key: "needs-more-info", label: "Ask the taxpayer",
    hint: "Cannot be settled on what is on file — opens an enquiry with a drafted request" },
];

const RULED: Record<string, string> = {
  accepted: "Confirmed",
  rejected: "Dismissed",
  "needs-more-info": "Waiting on more",
  "needs-more-investigation": "Challenged by you",
  irrelevant: "Not relevant",
};

/** What the auditor is disputing, handed over so they do not have to retype it.
 *
 *  `observed` is the adjudicator's own sentence about what was measured, and it carries the
 *  figure — so the question quotes the engine rather than composing a number of its own. */
const challengeQuestion = (c: SummaryCard) =>
  `I am challenging this finding: “${c.title}”.`
  + (c.observed ? ` The investigation says: “${c.observed}”.` : "")
  + (c.reading ? ` It would report as: “${c.reading}”.` : "")
  + " Talk me through what it rests on, and whether it holds.";

function Matter({ c, busy, onRule }: {
  c: SummaryCard;
  busy: boolean;
  onRule: (c: SummaryCard, decision: Ruling) => void;
}) {
  if (!c.hypothesis_ids[0]) return null;
  const challenged = c.decision === "needs-more-investigation";
  return (
    <div className={"matter"
                    + (c.decision === "accepted" ? " ruled" : "")
                    + (c.decision === "rejected" ? " dismissed" : "")
                    + (challenged ? " challenged" : "")}>
      <div className="matter-what">
        <b>{c.title}</b>
        {!!c.amount && <span className="matter-amt">{sar(c.amount)}</span>}
      </div>
      {c.decision ? (
        <div className="matter-act">
          <span className="matter-state"
                style={{ color: c.decision === "accepted" ? "var(--brand)"
                                : challenged ? "var(--accent-text)" : "var(--faint)" }}>
            {RULED[c.decision] || c.decision}
          </span>
          {/* The conversation is where a challenge is actually worked out, and an auditor who
              closed the panel needs it back without undoing their own ruling to get it. */}
          {challenged && (
            <button className="linklike" disabled={busy}
                    onClick={() => askAbout(challengeQuestion(c))}>
              ask the assistant about it
            </button>
          )}
          <button className="linklike" disabled={busy} style={{ color: "var(--faint)" }}
                  onClick={() => onRule(c, "")}>
            undo
          </button>
        </div>
      ) : (
        <div className="matter-act">
          {RULINGS.map((r) => (
            <button key={r.key} className={"btn-ghost" + (r.tone ? " " + r.tone : "")}
                    title={r.hint} disabled={busy} onClick={() => onRule(c, r.key)}>
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The auditor's own conclusion — drafted from the investigation, owned by the person signing.
 *
 *  One section, at the end, rather than a decision control on every card. The draft states no
 *  figure the engine did not compute; from there it is a document, and what the auditor writes
 *  replaces what the engine wrote with the original kept beside it. */
export default function AuditorAssessment({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged?: () => void;
}) {
  const [d, setD] = useState<AssessmentView | null>(null);
  const [sum, setSum] = useState<InvestigationSummary | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState("");
  const nav = useNavigate();

  const load = useCallback(() => {
    getAssessment(id).then((a) => { setD(a); setDraft(a.text); }).catch(() => {});
    getInvestigationSummary(id).then(setSum).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const commit = async (text: string) => {
    setBusy(true);
    setErr("");
    try {
      const next = await saveAssessment(id, text);
      setD(next);
      setDraft(next.text);
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save that.");
    } finally {
      setBusy(false);
    }
  };

  // "Ask the taxpayer" is the loop, not a third verdict: it parks the matter as waiting,
  // opens an enquiry carrying the hypothesis id, and drafts the request from the engine's own
  // account of what is missing. Recording it as a decision and stopping there would leave the
  // auditor to write that letter themselves, which is the round this exists to save.
  const rule = async (c: SummaryCard, decision: Ruling) => {
    const hid = c.hypothesis_ids[0];
    setBusy(true);
    setErr("");
    try {
      if (decision === "") {
        await undecideHypothesis(id, hid);
        load();
        onChanged?.();
        return;
      }
      if (decision === "needs-more-info") {
        await requestInformation(id, hid, "");
        nav(`/cases/${id}/correspondence`);
        return;
      }
      await decideHypothesis(id, hid, decision, "");
      // A challenge that only opened a chat would be a note nobody reads — the same reason the
      // completeness rows record theirs. So the ruling goes on the file first, and *then* the
      // conversation opens with the matter already written into it.
      if (decision === "needs-more-investigation") askAbout(challengeQuestion(c));
      load();
      onChanged?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not record that.");
    } finally {
      setBusy(false);
    }
  };

  if (!d) return null;

  // Only matters with a hypothesis behind them can be ruled on: a records defect from the
  // matcher is a fault in the file, not a proposition to accept or dismiss.
  const matters = (sum?.cards ?? []).filter((c) => c.hypothesis_ids.length);
  const confirmed = matters.filter((c) => c.decision === "accepted");
  const confirmedTotal = confirmed.reduce((n, c) => n + c.amount, 0);

  return (
    <>
    <div className="panel assess">
      <div className="panel-head">
        <h3 className="display">Your assessment</h3>
        <span className="sub">only what you confirm reaches the report</span>
        <span className="sub num" style={{ marginLeft: "auto" }}>
          {confirmed.length
            ? `${confirmed.length} confirmed · ${sar(confirmedTotal)}`
            : "nothing confirmed yet"}
        </span>
      </div>

      <div className="panel-body">
        {err && <div className="callout warn">{err}</div>}

        {!!matters.length && (
          <div className="matters">
            {matters.map((c) => (
              <Matter key={c.key} c={c} busy={busy} onRule={rule} />
            ))}
          </div>
        )}

        <div className="assess-doc">
          <div className="assess-doc-head">
            <b>The assessment</b>
            <span className="sub">
              {d.edited
                ? `your words${d.updated_at ? ` · last changed ${d.updated_at.slice(0, 10)}` : ""}`
                : "drafted from the investigation — yours to edit"}
            </span>
            {d.edited && <span className="pill status">edited</span>}
            {saved && <span className="pill pri-low">Saved</span>}
          </div>

          {editing ? (
            <>
              <textarea
                className="assess-input"
                rows={16}
                value={draft}
                disabled={busy}
                onChange={(e) => setDraft(e.target.value)}
              />
              <div className="row-actions">
                <button className="btn" disabled={busy} onClick={() => commit(draft)}>
                  {busy ? "Saving…" : "Save assessment"}
                </button>
                <button className="linklike" disabled={busy}
                        onClick={() => { setDraft(d.text); setEditing(false); }}>
                  cancel
                </button>
                {d.edited && (
                  <button className="linklike danger" disabled={busy} onClick={() => commit("")}>
                    restore the engine's draft
                  </button>
                )}
              </div>
            </>
          ) : (
            <>
              <pre className="assess-text">{d.text}</pre>
              <div className="row-actions">
                <button className="btn-ghost" onClick={() => setEditing(true)}>
                  Edit the assessment
                </button>
              </div>
            </>
          )}
        </div>

        <div className="assess-ai">
          <span className="ai-chip"><Sparkles size={13} /></span>
          <b>Or tell the assistant what to change</b>
          <div className="assess-steers">
            {STEERS.map((s) => (
              <button key={s} className="btn-ghost" onClick={() => askAbout(s)}>
                {s}
              </button>
            ))}
          </div>
          <p className="detail-note" style={{ marginBottom: 0 }}>
            It rewrites the assessment against the same figures the engine computed, checked the
            same way — an instruction can change how something is put, and cannot introduce a
            number. The assessment stays yours: whatever comes back, you edit it here.
          </p>
        </div>
      </div>
    </div>

    {/* The end of the module. The confirming happened above, matter by matter; this says what
        those rulings come to and takes the auditor to the report they produce. Nothing is
        confirmed *by* this button — which is why it states the count even when it is nought,
        rather than moving on quietly and letting the report be the one to break the news. */}
    <ModuleHandoff
      label="Confirm and draft audit report"
      to={`/cases/${id}/report`}
      carries={confirmed.length
        ? `${confirmed.length} matter${confirmed.length === 1 ? "" : "s"} confirmed`
          + ` · ${sar(confirmedTotal)}`
        : "Nothing confirmed yet"}
      caution={confirmed.length
        ? "Only what you have confirmed reaches the audit report and the letter to the taxpayer."
          + " The rest stays on the file as investigated and not pursued."
        : "The report will record that no finding was established, which is the honest reading"
          + " of an investigation nobody has ruled on. Confirm a matter above to carry it"
          + " through."}
    />
    </>
  );
}
