import { useState } from "react";
import type { Confidence } from "../api";

/** How much weight a hypothesis can bear — shown as a band, never as a bare percentage. */
export const BAND_CLASS: Record<string, string> = {
  Strong: "pri-low",
  Moderate: "pri-medium",
  Limited: "pri-high",
  Insufficient: "status",
};

export default function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const [open, setOpen] = useState(false);
  if (!confidence?.band) return null;

  const met = confidence.signals.filter((s) => s.value >= 1);
  const missing = confidence.signals.filter((s) => s.value < 1);

  return (
    <div className="conf">
      <button
        className={"pill " + (BAND_CLASS[confidence.band] || "status")}
        onClick={() => setOpen(!open)}
        title="What this rests on — click to see which signals were met"
      >
        {confidence.band} confidence
      </button>
      {open && (
        <div className="conf-detail">
          <p className="detail-note" style={{ margin: "0 0 8px" }}>
            A weighted read of seven signals, computed by the engine — not a probability. The
            composite is {confidence.score}/100; what it is made of matters more than the number.
          </p>
          {missing.length > 0 && (
            <>
              <div className="conf-h">Not satisfied</div>
              <ul className="conf-list">
                {missing.map((s) => (
                  <li key={s.key}>
                    <b>{s.label}</b>
                    <span className="sub">{s.note}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {met.length > 0 && (
            <>
              <div className="conf-h">Satisfied</div>
              <ul className="conf-list met">
                {met.map((s) => (
                  <li key={s.key}>
                    <b>{s.label}</b>
                    <span className="sub">{s.note}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
