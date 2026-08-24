import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import ModuleHandoff from "../components/ModuleHandoff";
import RoundCard from "../components/RoundCard";
import { getLoop, getThreads, runInvestigation, type LoopState, type ThreadState } from "../api";

/** Everything said to the taxpayer, and everything they sent back. */
export default function Correspondence() {
  const { id = "" } = useParams();
  const [loop, setLoop] = useState<LoopState | null>(null);
  const [threads, setThreads] = useState<ThreadState | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    getLoop(id).then(setLoop).catch((e) => setErr(String(e)));
    getThreads(id).then(setThreads).catch(() => {});
  }, [id]);
  useEffect(load, [load]);

  // A round is a thread. `InformationRequest` still holds the column specification behind
  // round 1 — that is what step 3 checks against — but what the auditor counts as a round is
  // one exchange with the taxpayer, which is exactly what a thread is.
  const rounds = threads?.threads ?? [];
  const shown = rounds.length ? rounds : [null];
  const outstanding = loop?.assessment
    ? loop.assessment.items.filter((i) => i.state !== "received").length
    : 0;
  const docs = rounds.reduce((n, t) => n + t.documents.length, 0);

  // Finishing correspondence is not a state to store — it is the moment the investigation
  // should be run again over everything that has arrived since it last ran. Saying so, and
  // doing it, is what makes the handoff real rather than a link with a confident label.
  const carries = docs
    ? `${docs} document${docs === 1 ? "" : "s"} on file`
      + (outstanding ? ` · ${outstanding} still outstanding` : " · nothing outstanding")
    : "Nothing filed on this case yet";
  const caution = !docs
    ? "There is nothing for the investigation to run on yet. Drop the chain and the taxpayer's "
      + "files into the round above first."
    : outstanding
      ? "The investigation will run over the evidence on file, and open. "
        + `${outstanding} item${outstanding === 1 ? " is" : "s are"} still outstanding — `
        + "they stay on this round, and step 4 drafts the chase for them."
      : "The investigation will run over the evidence on file, and open.";

  return (
    <>
      <CaseTabs id={id} />
      <div className="page">
      <div className="modulehead">
        <h2 className="display">Round {Math.max(rounds.length, 1)} — {
          rounds.length > 1 ? "the enquiry so far" : "opening request"
        }</h2>
        {outstanding > 0 && (
          <span className="pill pri-high">{outstanding} outstanding</span>
        )}
      </div>
      {err && <p className="error">{err}</p>}

      {threads?.missing_attachments?.map((m) => (
        <div className="callout warn" key={`${m.thread_id}-${m.message_seq}`}>
          <b>Round {m.thread_seq}: a reply mentions an attachment, and none is filed.</b>{" "}
          {m.detail}
        </div>
      ))}

      {!!threads?.retestable.length && (
        <div className="callout ok">
          <b>New evidence has arrived.</b>{" "}
          {threads.retestable.length} hypothes
          {threads.retestable.length === 1 ? "is" : "es"} waiting on the taxpayer can now be
          re-tested — <Link to={`/cases/${id}/investigation`}>re-run the investigation</Link> to
          settle {threads.retestable.length === 1 ? "it" : "them"}.
        </div>
      )}

      {shown.map((t, i) => (
        <RoundCard
          /* Keyed by round number, not thread id. The first email filed on a round is what
             creates its thread, so keying on the id remounted the card at exactly that moment
             and threw away the result of the upload the auditor had just done. */
          key={t?.seq ?? i + 1}
          id={id}
          thread={t}
          seq={t?.seq ?? 1}
          assessment={i === 0 ? loop?.assessment : undefined}
          hasFormalRequest={i === 0 && (loop?.round ?? 0) > 0}
          onChanged={load}
        />
      ))}

      <div className="roundcard soon">
        <div className="round-head">
          <span className="round-n">Round {shown.length + 1}</span>
          <span className="round-origin">
            Opens from the investigation — when a hypothesis cannot be settled on the evidence
            held, requesting information from the taxpayer starts the next round here.
          </span>
          <span className="pill status">coming soon</span>
        </div>
        <div className="rstep">
          <p className="detail-note" style={{ margin: 0 }}>
            The same four steps, against whatever the next question turns out to be. Raise it
            from a hypothesis on the{" "}
            <Link to={`/cases/${id}/investigation`}>Investigation</Link> tab.
          </p>
        </div>
      </div>

      <ModuleHandoff
        label="Confirm and move to Investigation"
        to={`/cases/${id}/investigation`}
        carries={carries}
        caution={caution}
        onConfirm={docs ? () => runInvestigation(id, "new-evidence") : undefined}
      />
    </div>
    </>
  );
}
