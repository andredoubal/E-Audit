/** The four stages of the investigation, in the order the work is actually done.
 *
 *  This is not a filter over one page. Each tab is a different layer of the same chain, and the
 *  chain only runs one way:
 *
 *      DATA → CALCULATION → OBSERVATION → HYPOTHESIS → REGULATORY → AI FINDING → AUDITOR FINDING
 *
 *  Tab 1 is what arrived. Tab 2 is what the arithmetic shows, with no explanation attached to
 *  it. Tab 3 is what the AI proposes those figures might mean, still proposed. Tab 4 is what
 *  the auditor has decided, and it is the only one the audit report reads.
 *
 *  Keeping them apart is the whole design. On one page an observation and a finding sit in the
 *  same column and read as the same kind of claim, which is exactly the conflation that puts an
 *  unreviewed model sentence under the Authority's letterhead.
 */
export type InvTab = "data" | "reconciliation" | "ai" | "auditor";

const TABS: { key: InvTab; label: string; sub: string }[] = [
  { key: "data", label: "Data & E-Invoices", sub: "what arrived, and what it is" },
  { key: "reconciliation", label: "Reconciliation", sub: "what the figures show" },
  { key: "ai", label: "AI Findings", sub: "proposed, not concluded" },
  { key: "auditor", label: "Auditor Findings", sub: "what you have decided" },
];

export default function InvestigationTabs({ active, onSelect, counts }: {
  active: InvTab;
  onSelect: (t: InvTab) => void;
  /** A badge per tab, when there is something to count. Absent rather than zero: a tab that
   *  always shows a number teaches the auditor the number means nothing. */
  counts?: Partial<Record<InvTab, { n: number; hot?: boolean; title?: string }>>;
}) {
  return (
    <div className="invtabs" role="tablist">
      {TABS.map((t, i) => {
        const c = counts?.[t.key];
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={active === t.key}
            className={"invtab" + (active === t.key ? " on" : "")}
            onClick={() => onSelect(t.key)}
          >
            <span className="invtab-n num">{i + 1}</span>
            <span className="invtab-text">
              <b>{t.label}</b>
              <small>{t.sub}</small>
            </span>
            {c !== undefined && (
              <span className={"invtab-badge num" + (c.hot ? " hot" : "")} title={c.title}>
                {c.n}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
