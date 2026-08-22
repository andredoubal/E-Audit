import { useState } from "react";
import { askAbout } from "../ai/ask";
import type { ItemReview } from "../api";

/** Approve or challenge one thing the application worked out. */
export default function ReviewControls({ review, label, context, busy, onReview }: {
  review: ItemReview | null;
  /** What is being reviewed, for the assistant's opening question. */
  label: string;
  /** One line of detail — the reason the check gave — so the assistant has the case, not a name. */
  context?: string;
  busy?: boolean;
  onReview: (verdict: "approved" | "challenged" | "", note: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");

  const ask = () => askAbout(
    `I am challenging this: “${label}”.`
    + (context ? ` The check says: “${context}”.` : "")
    + (review?.note ? ` My reason: ${review.note}` : "")
    + " Help me work out whether it is right.");

  if (open) {
    return (
      <div className="review open">
        <textarea
          className="review-note"
          rows={2}
          autoFocus
          value={note}
          placeholder="What is wrong with this? e.g. the column is there, headed “VAT no.”"
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { setOpen(false); setNote(""); } }}
        />
        <div className="review-row">
          <button className="btn small" disabled={busy || !note.trim()}
                  onClick={() => { onReview("challenged", note.trim()); setOpen(false); setNote(""); }}>
            Record the challenge
          </button>
          <button className="linklike" onClick={() => { setOpen(false); setNote(""); }}>
            cancel
          </button>
          <span className="sub">A challenge needs a reason — it goes on the case file.</span>
        </div>
      </div>
    );
  }

  if (review) {
    const challenged = review.verdict === "challenged";
    return (
      <div className={"review done " + review.verdict}>
        <span className={"pill " + (challenged ? "pri-medium" : "pri-low")}>
          {challenged ? "Challenged by you" : "Approved by you"}
        </span>
        {challenged && review.note && <span className="review-why">“{review.note}”</span>}
        <div className="review-row">
          {challenged && (
            <button className="linklike" onClick={ask}>ask the assistant about it</button>
          )}
          <button className="linklike" disabled={busy} onClick={() => onReview("", "")}>
            undo
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="review">
      <button className="btn small ghost" disabled={busy}
              onClick={() => onReview("approved", "")}>
        Approve
      </button>
      <button className="btn small warn" disabled={busy} onClick={() => setOpen(true)}>
        Challenge
      </button>
    </div>
  );
}
