import { useEffect, useState } from "react";
import { getLifecycle, type Lifecycle } from "../api";

const MARK: Record<string, string> = {
  done: "✓",
  active: "▶",
  waiting: "⧗",
  pending: "",
  skipped: "—",
};

/** Where the case is in the five-stage run, and whose move it is. */
export default function LifecycleRail({ id }: { id: string }) {
  const [d, setD] = useState<Lifecycle | null>(null);
  useEffect(() => {
    setD(null);
    getLifecycle(id).then(setD).catch(() => {});
  }, [id]);
  if (!d) return null;

  return (
    <div className="rail">
      <div className="rail-track">
        {d.stages.map((s) => (
          <div key={s.key} className={"rail-stage " + s.state} title={s.summary}>
            <span className="rs-mark">{MARK[s.state]}</span>
            <span className="rs-label">{s.label}</span>
          </div>
        ))}
      </div>
      <div className="rail-note">
        {d.no_contact_needed && (
          <span className="pill pri-low">Cleared without contacting the taxpayer</span>
        )}
        {d.open_with_taxpayer_during_review && (
          <span className="rail-revisit">
            ⇄ Review under way with items still outstanding with the taxpayer
          </span>
        )}
        <span className="sub">
          <b>{d.current_label}</b>
          {d.next_action ? ` — ${d.next_action}` : ""}
          {d.waiting_on === "taxpayer" && " (waiting on the taxpayer)"}
          {(d.active?.length ?? 0) > 1 && ` · ${d.active.length} stages open`}
        </span>
      </div>
    </div>
  );
}
