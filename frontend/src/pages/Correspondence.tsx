import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import RoundCard from "../components/RoundCard";
import CaseAssistant from "../components/CaseAssistant";
import { getLoop, getThreads, type LoopState, type ThreadState } from "../api";

/** Everything said to the taxpayer, and everything they sent back.
 *
 *  One round, four steps, in the order they happen: the email chain goes out, documents come
 *  back, the two are compared, and whatever is still missing becomes the next email. The page
 *  is deliberately nothing else — earlier versions carried seven panels, two of which asked for
 *  the same thing in different words, and an auditor had to work out which one they were
 *  supposed to be filling in.
 *
 *  **Round 1 is the only round that exists by default.** A second round means the investigation
 *  could not settle something on the evidence held and went back to the taxpayer for more, so it
 *  is opened from the Investigation tab and never from here. That keeps the loop legible: a
 *  round on this page is always a question somebody actually needed answered.
 */
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

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Taxpayer correspondence</h1>
          <p className="sub">{id} · what we asked for, and what arrived</p>
        </div>
        <div className="chips">
          <span className={"pill " + (outstanding ? "pri-high" : "pri-low")}>
            Round {Math.max(rounds.length, 1)}
          </span>
          {outstanding > 0 && (
            <span className="pill pri-high">{outstanding} outstanding</span>
          )}
        </div>
      </header>

      <CaseTabs id={id} />
      {err && <p className="error">{err}</p>}

      {/* A reply that claims an attachment with nothing behind it reads, in the trail, exactly
          like an answered request — so both sides wait. */}
      {threads?.missing_attachments?.map((m) => (
        <div className="callout warn" key={`${m.thread_id}-${m.message_seq}`}>
          <b>Round {m.thread_seq}: a reply mentions an attachment, and none is filed.</b>{" "}
          {m.detail}
        </div>
      ))}

      {/* The loop, surfaced where the answer lands. */}
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

      {/* The next round, shown as the placeholder it is. An auditor should be able to see that
          the loop exists and where it comes from without having to discover it by accident on
          another tab — and a round with no question behind it is not a round. */}
      <div className="roundcard soon">
        <div className="round-head">
          {/* `shown`, not `rounds`: a case with no thread yet still shows a Round 1 card, and
              counting the threads made the placeholder underneath it "Round 1" as well. */}
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

      <CaseAssistant id={id} />
    </>
  );
}
