import { useCallback, useEffect, useState } from "react";
import { getReconciliations, getRegulatoryControls,
         type ReconState, type RegulatoryState } from "../api";

const sar = (n: number) =>
  "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

export type Workstream = "sales" | "purchases";

const LABEL: Record<Workstream, string> = { sales: "Sales", purchases: "Purchases" };
const SUB: Record<Workstream, string> = {
  sales: "Output VAT — what was supplied",
  purchases: "Input VAT — what was claimed",
};

/** Sales and purchases as two workstreams, with what each one comes to.
 *
 *  Separate because they are separate audits: an under-declared sale and an over-claimed
 *  purchase are opposite risks, resting on different evidence, tested against different
 *  provisions. A single merged view makes the auditor do that separation in their head on
 *  every screen.
 *
 *  Each card states the two things that decide where attention goes — how much could be
 *  compared at all, and how much of what was compared is unexplained — plus the regulatory
 *  concerns, which are deliberately counted apart from the variances. A case can have one
 *  without the other, and that is the whole point of the split. */
export default function WorkstreamTabs({ id, rev, active, onSelect }: {
  id: string;
  rev?: number;
  active: Workstream;
  onSelect: (w: Workstream) => void;
}) {
  const [recon, setRecon] = useState<ReconState | null>(null);
  const [reg, setReg] = useState<RegulatoryState | null>(null);

  const load = useCallback(() => {
    getReconciliations(id).then(setRecon).catch(() => {});
    getRegulatoryControls(id).then(setReg).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const concerns = (w: Workstream) =>
    (reg?.controls ?? []).filter(
      (c) => (c.applies_to === w || c.applies_to === "both")
        && c.status === "applicable-potential-concern").length;

  return (
    <div className="wstabs">
      {(["sales", "purchases"] as Workstream[]).map((w) => {
        const s = recon?.workstreams?.[w];
        const n = concerns(w);
        return (
          <button key={w} className={"wstab" + (active === w ? " on" : "")}
                  onClick={() => onSelect(w)} aria-pressed={active === w}>
            <span className="wstab-head">
              <b>{LABEL[w]}</b>
              <small>{SUB[w]}</small>
            </span>
            {s ? (
              <span className="wstab-stats">
                <span className="wstat">
                  <b className="num">{s.runnable}<i>/{s.total}</i></b>
                  <span>comparisons run</span>
                </span>
                <span className={"wstat" + (s.unexplained_count ? " hot" : "")}>
                  <b className="num">{s.unexplained_count}</b>
                  <span>unexplained</span>
                </span>
                <span className={"wstat" + (n ? " hot" : "")}>
                  <b className="num">{n}</b>
                  <span>regulatory concerns</span>
                </span>
              </span>
            ) : (
              <span className="wstab-stats"><span className="sub">reading…</span></span>
            )}
            {!!s?.largest_unexplained && (
              <span className="wstab-foot num">
                largest difference {sar(s.largest_unexplained)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
