import { useEffect, useState, type ReactNode } from "react";
import { useParams, Link } from "react-router-dom";
import TaxpayerBrief from "../components/TaxpayerBrief";
import AiNarration from "../components/AiNarration";
import NextBestAction from "../components/NextBestAction";
import InvestigationPanel from "../components/InvestigationPanel";
import ZatcaPanel from "../components/ZatcaPanel";
import FindingsPanel from "../components/FindingsPanel";
import CalculationPanel from "../components/CalculationPanel";
import CaseTabs from "../components/CaseTabs";
import AuditorAssessment from "../components/AuditorAssessment";
import VatRegisters from "../components/VatRegisters";
import InvestigationTabs, { type InvTab } from "../components/InvestigationTabs";
import DataTab from "../components/DataTab";
import ReconciliationDashboard from "../components/ReconciliationDashboard";
import AuditorFindingsTab from "../components/AuditorFindingsTab";
import { getDashboard, type ReconDashboard } from "../api";
import ReconciliationPanel from "../components/ReconciliationPanel";
import RegulatoryCoverage from "../components/RegulatoryCoverage";
import WorkstreamTabs, { type Workstream } from "../components/WorkstreamTabs";
import InvestigationSummary from "../components/InvestigationSummary";
import Collapsible from "../components/Collapsible";
import CaseContextPanel from "../components/CaseContextPanel";
import TaxpayerResponsePanel from "../components/TaxpayerResponsePanel";

/** One step in the narrowing from the population to the qualifying set. */
interface FunnelStep {
  seq: number;
  kind: "population" | "exclude" | "defer" | "qualified";
  rule: string | null;
  stage?: string;
  label: string;
  count: number;
  amount: number;
  detail?: Detail;
}
interface CompositionRow {
  type_code: number;
  label: string;
  count: number;
  amount: number;
  detail?: Detail;
}
interface EvidenceRow {
  code: string;
  label: string;
  amount: number;
  doc_name: string;
  detail?: Detail;
}
type Detail = Record<string, any>;
interface BoxResult {
  box: string;
  declared: number;
  expected_vat: number;
  expected_base: number;
  difference: number;
  evidence_total: number;
  evidence: EvidenceRow[];
  rounding_total?: number;
  unexplained: number;
  materiality: number;
  band: string;
  state: string;
  funnel: FunnelStep[];
  composition: CompositionRow[];
  declared_detail?: Detail;
  difference_detail?: Detail;
  invoices_considered: number;
  population_lines: number;
  counted_lines: number;
  evidence_invoices: Detail[];
}
/** Where the figures came from. */
interface Provenance {
  population_source?: "document" | "e-invoice";
  population_document?: string;
  population_complete?: boolean;
  population_caveat?: string;
  population_gaps?: string[];
}
interface Combined {
  total_exposure: number;
  state: string;
  output_state: string;
  input_state: string;
  output_unexplained: number;
  input_unexplained: number;
  finding_boxes: string[];
}
interface Recon extends BoxResult, Provenance {
  case_id: string;
  taxpayer: string;
  purchase?: BoxResult;
  zero_rated?: BoxResult;
  combined?: Combined;
  prior_period_correction_declared?: number;
}

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const STATE_LABEL: Record<string, string> = {
  "potential-finding": "Potential finding",
  supported: "Supported — no finding",
  unresolved: "Unresolved",
};
const STATE_CLASS: Record<string, string> = {
  "potential-finding": "pri-high",
  supported: "pri-low",
  unresolved: "pri-medium",
};

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [onClose]);
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

function InvoiceTable({ invoices }: { invoices: Detail[] }) {
  if (!invoices?.length) return <p className="muted">No underlying invoices.</p>;
  return (
    <div className="tablescroll">
      <table className="inv-table">
        <thead>
          <tr>
            <th>Invoice UUID</th>
            <th>Type</th>
            <th>Issue</th>
            <th>Delivery</th>
            <th style={{ textAlign: "right" }}>Base</th>
            <th style={{ textAlign: "right" }}>VAT</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((iv) => (
            <tr key={iv.uuid}>
              <td className="mono">{iv.uuid}</td>
              <td>
                {iv.type}
                {iv.status !== "cleared" && <span className="sub"> · {iv.status}</span>}
              </td>
              <td className="mono">{iv.issue_date}</td>
              <td className="mono">{iv.delivery_date || "—"}</td>
              <td className="mono" style={{ textAlign: "right" }}>{sar(iv.base)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{sar(iv.tax_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The rows a comparison found on one side only, or recorded differently on each.
 *
 *  The only attribution the engine claims, and it claims it because it can: these are named
 *  references carrying named amounts, joined across two populations. A total-grain comparison
 *  reaches no such table, and says so instead of offering one. */
function ContributionTable({ detail }: { detail: Detail }) {
  const rows = (detail.contributions ?? []) as any[];
  if (!rows.length) return <p className="muted">No rows are attributable to this difference.</p>;
  return (
    <>
      <p className="detail-note">{detail.note}</p>
      <div className="tablescroll">
        <table className="inv-table">
          <thead>
            <tr>
              <th>Reference</th>
              <th>Where</th>
              <th style={{ textAlign: "right" }}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c, n) => (
              <tr key={(c.reference || "") + n}>
                <td className="mono">{c.reference || "(no reference)"}</td>
                <td>{c.note}</td>
                <td className="mono" style={{ textAlign: "right" }}>{sar(c.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DetailBody({ detail, amount }: { detail?: Detail; amount?: number }) {
  if (!detail) return <p className="muted">No further detail.</p>;
  if (detail.type === "recon-contributions") return <ContributionTable detail={detail} />;
  const kv = (rows: [string, ReactNode][]) => (
    <div className="kv">
      {rows.map(([k, v]) => (
        <div key={k}>
          <span className="k">{k}</span>
          <span className="v">{v ?? "—"}</span>
        </div>
      ))}
    </div>
  );

  if (detail.type === "declared")
    return (
      <>
        {kv([
          ["Box", `${detail.box_label} (${detail.box_code})`],
          ["Declared VAT", sar(detail.vat_amount)],
          ["Declared base", detail.base_amount != null ? sar(detail.base_amount) : "—"],
          ["Own adjustment", sar(detail.adjustment || 0)],
          ["Return form", detail.form_number],
          ["Version", detail.data_version],
          ["Submitted", detail.submission_date],
        ])}
        <p className="detail-note">{detail.note}</p>
      </>
    );

  if (detail.type === "difference")
    return (
      <>
        {kv([
          ["Expected (qualifying documents)", sar(detail.expected)],
          ["Declared on the return", sar(detail.declared)],
          ["Difference", <b>{sar(detail.difference)}</b>],
          ["Accounted for by evidence", sar(detail.evidence_total)],
          ["Left unexplained", <b>{sar(detail.unexplained)}</b>],
          ["Materiality threshold", sar(detail.materiality)],
          ["Band", detail.band],
          ["Verdict", STATE_LABEL[detail.state] || detail.state],
        ])}
        <p className="detail-note">{detail.note}</p>
      </>
    );

  if (detail.type === "response")
    return (
      <>
        {kv([
          ["Accounts for", <b>{sar(Math.abs(detail.total))}</b>],
          ["Document", detail.doc_name || "—"],
          ["Source", "Taxpayer-supplied evidence"],
        ])}
        <p className="detail-note">{detail.note}</p>
      </>
    );

  // population | qualified | rule | structural | composition → note (+ rule card) + the documents
  return (
    <>
      {detail.type === "rule" && detail.rule && (
        <div className="rulecard">
          <div className="rc-top">
            <span className="rc">{detail.rule.code}</span>
            <span className="fam">{detail.rule.family}</span>
            <Link to="/rules" className="rc-link">
              open in rulebook →
            </Link>
          </div>
          <div className="rc-title">{detail.rule.title}</div>
          <div className="rc-meta">
            {detail.rule.explains_gap} · {detail.rule.severity}
          </div>
        </div>
      )}
      {detail.formula && (
        <div className="formula">
          <span className="k">Computation</span>
          <code>{detail.formula}</code>
        </div>
      )}
      <p className="detail-note">{detail.note}</p>
      {kv([
        ["Invoices", detail.count],
        ["Line total", amount != null ? sar(amount) : sar(detail.total)],
      ])}
      <InvoiceTable invoices={detail.invoices} />
    </>
  );
}

/** How the population narrowed to the qualifying set. */
function Funnel({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  const start = d.funnel.find((f) => f.kind === "population");
  const endStep = d.funnel.find((f) => f.kind === "qualified");
  const steps = d.funnel.filter((f) => f.kind === "exclude" || f.kind === "defer");
  const max = Math.max(start?.count ?? 1, 1);

  const row = (f: FunnelStep, remaining: number) => (
    <div
      className={"frow clickable " + f.kind}
      key={f.seq}
      role="button"
      tabIndex={0}
      onClick={() => open(f.label, f.detail, f.amount)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(f.label, f.detail, f.amount)}
    >
      <div className="fcount">
        {f.kind === "exclude" || f.kind === "defer" ? "−" : ""}
        {f.count}
      </div>
      <div className="flbl">
        {f.rule && <span className="rc">{f.rule}</span>}
        {f.label}
        <span className="rowhint">›</span>
      </div>
      <div className="ftrack">
        <div className={"fbar " + f.kind} style={{ width: (remaining / max) * 100 + "%" }} />
      </div>
      <div className={"famt " + f.kind}>{sar(f.amount)}</div>
    </div>
  );

  let remaining = start?.count ?? 0;
  return (
    <div className="funnel">
      {start && row(start, remaining)}
      {steps.map((f) => {
        remaining -= f.count;
        return row(f, remaining);
      })}
      {endStep && row(endStep, endStep.count)}
      {d.composition.length > 0 && (
        <div className="fcomp">
          {d.composition.map((c) => (
            <button
              key={c.type_code}
              className="fchip"
              onClick={() => open(c.label, c.detail, c.amount)}
            >
              <b>{c.count}</b> {c.label.toLowerCase()}
              <span className={c.amount < 0 ? "neg" : ""}>
                {c.amount < 0 ? "−" : ""}
                {sar(c.amount)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Expected vs declared, and what is left. */
function Compare({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  const risky = d.state === "potential-finding";
  return (
    <div className="compare">
      <button className="cmp" onClick={() => open("Qualifying e-invoices", d.funnel.find((f) => f.kind === "qualified")?.detail, d.expected_vat)}>
        <span className="cl">Expected</span>
        <span className="cn">{sar(d.expected_vat)}</span>
        <span className="cs">{d.counted_lines} qualifying documents</span>
      </button>
      <span className="cop">−</span>
      <button className="cmp" onClick={() => open("Declared by the taxpayer", d.declared_detail, d.declared)}>
        <span className="cl">Declared</span>
        <span className="cn">{sar(d.declared)}</span>
        <span className="cs">as filed</span>
      </button>
      <span className="cop">=</span>
      <button
        className={"cmp result " + (risky ? "risk" : d.state === "supported" ? "ok" : "warn")}
        onClick={() => open("Difference", d.difference_detail, d.difference)}
      >
        <span className="cl">Difference</span>
        <span className="cn">
          {d.difference < 0 ? "−" : ""}
          {sar(d.difference)}
        </span>
        <span className="cs">{STATE_LABEL[d.state] || d.state}</span>
      </button>
    </div>
  );
}

/** Taxpayer evidence — the only thing that can account for a difference after the fact. */
function Evidence({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  if (!d.evidence?.length) return null;
  return (
    <div className="evidence">
      <h4>Accounted for by taxpayer evidence</h4>
      {d.evidence.map((e) => (
        <button key={e.code} className="erow" onClick={() => open(e.label, e.detail, e.amount)}>
          <span className="rc">{e.code}</span>
          <span className="elbl">{e.label}</span>
          <span className="eamt">−{sar(e.amount)}</span>
        </button>
      ))}
      <div className="erow total">
        <span className="elbl">Still unexplained</span>
        <span className="eamt" style={{ color: d.state === "supported" ? "var(--low)" : "var(--high)" }}>
          {sar(d.unexplained)}
        </span>
      </div>
    </div>
  );
}

export default function Investigation() {
  const { id } = useParams();
  const [d, setD] = useState<Recon | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [rev, setRev] = useState(0);
  const [modal, setModal] = useState<{ title: string; detail?: Detail; amount?: number } | null>(null);
  // Sales and purchases are separate audits — opposite risks, different evidence, different
  // provisions — so the workstream is a property of the screen rather than a filter buried in
  // a panel. Sales first because output VAT is where most cases start.
  const [workstream, setWorkstream] = useState<Workstream>("sales");
  // The four layers of the chain, and which one you are looking at. Landing on the first is
  // deliberate: a dataset read wrongly corrupts every figure in the three tabs after it, in a
  // way no reconciliation can detect, because by then the reading has already been made.
  const [tab, setTab] = useState<InvTab>("data");
  const [dash, setDash] = useState<ReconDashboard | null>(null);
  const [inv, setInv] = useState<{ hypotheses: { decision: { decision: string } | null;
                                                 status: string; outcome_code: string }[] } | null>(null);

  // Blanking the page is right when the *case* changes — the old case's figures must not sit
  // on screen under a new case's name. It is wrong on a refresh of the same case: `!d` falls
  // through to the loading branch, which unmounts `CaseTabs` and the assistant docked inside
  // it. Recording a decision therefore closed the assistant and threw away the question it had
  // just been handed, which is precisely what Challenge exists to open.
  useEffect(() => { setD(null); setErr(null); }, [id]);

  useEffect(() => {
    if (!id) return;
    // A response for the case you have just navigated away from must not land on this one.
    let live = true;
    fetch(`/api/cases/${id}/reconcile`)
      .then((r) => {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      })
      .then((j) => { if (live) { setD(j); setErr(null); } })
      .catch((e) => { if (live) setErr(String(e)); });
    getDashboard(id).then((j) => { if (live) setDash(j); }).catch(() => {});
    fetch(`/api/cases/${id}/investigation`)
      .then((r) => r.json())
      .then((j) => { if (live) setInv(j); })
      .catch(() => {});
    return () => { live = false; };
  }, [id, rev]);

  if (err)
    return (
      <div className="page">
        <div className="panel">
          <div className="notice err">Could not reconcile this case — {err}</div>
        </div>
      </div>
    );
  if (!d)
    return (
      <div className="page">
        <p className="muted">Reconstructing from e-invoices…</p>
      </div>
    );

  const open = (title: string, detail?: Detail, amount?: number) => setModal({ title, detail, amount });
  const bump = () => setRev((r) => r + 1);
  const cstate = d.combined?.state ?? d.state;
  const inputFinding = d.combined?.input_state === "potential-finding";

  // Badges are absent rather than zero. A tab that always carries a number teaches the eye
  // that the number means nothing.
  const exceptionCount = dash
    ? dash.exceptions.filter((e) => e.kind !== "comparison-not-possible").length
    : undefined;
  const hyps = inv?.hypotheses ?? [];
  const undecided = hyps.filter((h) => !h.decision && h.status !== "refuted" && h.outcome_code);
  const confirmed = hyps.filter((h) => h.decision?.decision === "accepted");
  const counts = {
    ...(exceptionCount ? { reconciliation: { n: exceptionCount, hot: exceptionCount > 0,
                                             title: "exceptions the figures raise" } } : {}),
    ...(undecided.length ? { ai: { n: undecided.length, hot: true,
                                   title: "matters awaiting your decision" } } : {}),
    ...(confirmed.length ? { auditor: { n: confirmed.length,
                                        title: "findings you have confirmed" } } : {}),
  };

  return (
    <>
      <CaseTabs id={id!} />
      <div className="page">
      {/* The case's own verdict, and the second box when it carries one. The design took the
          exposure figure out of the case header; these are not that — they are what the engine
          concluded, and an auditor opening the module should see it before the detail. */}
      <div className="casestate">
        <span className={"pill " + (STATE_CLASS[cstate] || "status")}>
          {STATE_LABEL[cstate] || cstate}
        </span>
        {inputFinding && d.combined && (
          <span className="pill pri-high" title="Input-VAT over-claim on the purchases box">
            + input over-claim {sar(d.combined.input_unexplained)}
          </span>
        )}
        {d.population_source === "document" && d.population_document && (
          <span className="sub">
            reconciled from <b>{d.population_document}</b>
            {d.population_complete === false && " — treat the figures as a floor"}
          </span>
        )}
      </div>

      <InvestigationTabs active={tab} onSelect={setTab} counts={counts} />

      {/* ---------------------------------------------------------------- 1 · what arrived */}
      {tab === "data" && <DataTab id={id!} rev={rev} onChanged={bump} />}

      {/* ---------------------------------------------------- 2 · what the arithmetic shows */}
      {tab === "reconciliation" && (
        <>
          <ReconciliationDashboard id={id!} rev={rev} />

          {/* The registers, kept as the plain three-figure reading of the box: what the
              listing itself states, what was declared, and the gap — with no qualification
              rule between them, because reading a listing's own arithmetic is not a
              qualification judgement and must not borrow one. */}
          <VatRegisters id={id!} rev={rev} onChanged={bump}
                        onInvoices={(title, invoices, note) =>
                          open(title, { type: "invoice-list", invoices, note })} />

          <WorkstreamTabs id={id!} rev={rev} active={workstream} onSelect={setWorkstream} />

          {/* The declarative comparison registry — every comparison this evidence supports,
              and every one it does not. */}
          <ReconciliationPanel id={id!} workstream={workstream} rev={rev}
                               onDrill={(title, detail) => open(title, detail as Detail)} />

          {/* Qualification: which documents belong in a box at all. A separate question from
              the six pairings above — those compare populations, this decides membership —
              and the funnel is a partition of the population, never a bridge. */}
          <div className="panel">
            <div className="panel-head">
              <h2>Which documents belong in {d.box}</h2>
              <button
                className="linklike"
                onClick={() => open("E-invoices on file", { type: "invoice-list", invoices: d.evidence_invoices, count: d.invoices_considered, note: "Every sale e-invoice held for this taxpayer, before any rule is applied." })}
              >
                {d.invoices_considered} e-invoices on file ›
              </button>
            </div>
            {d.population_source === "document" && (
              <div className={"provenance" + (d.population_complete ? "" : " warn")}>
                <span className="ct">source</span>
                Built from <b>{d.population_document}</b> — the listing the taxpayer supplied, not
                the Authority&rsquo;s e-invoice feed.
                {!d.population_complete && <div className="prov-caveat">{d.population_caveat}</div>}
              </div>
            )}
            <Funnel d={d} open={open} />
            <Compare d={d} open={open} />
            <Evidence d={d} open={open} />
            <div className="panel-note">
              <span className="ct">∑ computed</span> The rules decide which documents belong in this box and this period;
              the qualifying ones are then summed. Nothing is totalled and later adjusted, so there is no figure here
              &ldquo;before&rdquo; the rules. Click any line for the documents behind it.
            </div>
          </div>

          {d.purchase && (
            <div className="panel">
              <div className="panel-head">
                <h2>Which documents belong in standard-rated purchases</h2>
                <span
                  className={"pill " + (STATE_CLASS[d.purchase.state] || "status")}
                  style={{ fontSize: 12, padding: "5px 12px" }}
                >
                  {STATE_LABEL[d.purchase.state] || d.purchase.state}
                </span>
              </div>
              <Funnel d={d.purchase} open={open} />
              <Compare d={d.purchase} open={open} />
              <Evidence d={d.purchase} open={open} />
              <div className="panel-note">
                <span className="ct">∑ computed</span> The same order on the purchases side. Here an over-claim — declaring
                more input VAT than the qualifying invoices support — is the revenue risk, so a negative difference is the
                one to look at.
              </div>
            </div>
          )}

          {d.zero_rated && (
            <div className="panel">
              <div className="panel-head">
                <h2>Which documents belong in zero-rated domestic sales</h2>
                <span
                  className={"pill " + (STATE_CLASS[d.zero_rated.state] || "status")}
                  style={{ fontSize: 12, padding: "5px 12px" }}
                >
                  {STATE_LABEL[d.zero_rated.state] || d.zero_rated.state}
                </span>
              </div>
              <Funnel d={d.zero_rated} open={open} />
              <Compare d={d.zero_rated} open={open} />
              <Evidence d={d.zero_rated} open={open} />
              <div className="panel-note">
                <span className="ct">∑ computed</span> A second box, qualified the same way — scoped
                to zero-rated (0%) lines instead of standard-rated. No timing or credit-note rules
                are wired for this box yet, so this is a first, direct comparison of declared against
                what the records on file support.
              </div>
            </div>
          )}

          {/* The Authority's own invoice records, matched deterministically. Renders nothing
              at all with no dataset loaded, rather than reporting a comparison never run. */}
          <ZatcaPanel id={id!} rev={rev} />

          {/* The auditor's own arithmetic, checked by Python against the uploaded documents.
              A calculation, so it belongs with the calculations. */}
          <CalculationPanel id={id} onChanged={bump} />
        </>
      )}

      {/* --------------------------------------------- 3 · what it might mean, still proposed */}
      {tab === "ai" && (
        <>
          <div className="notice">
            Everything on this tab is <b>proposed</b>. An agent raises a hypothesis in
            exploratory language and the engine settles it deterministically over the rows —
            but nothing here is a conclusion of the audit until you confirm it on the next tab,
            and nothing unconfirmed reaches the audit report.
          </div>

          <WorkstreamTabs id={id!} rev={rev} active={workstream} onSelect={setWorkstream} />

          <InvestigationSummary id={id!} rev={rev} />

          {/* The ruling sits with what it rules on. An auditor reads a matter and decides on
              it in the same place; sending them to another tab to record what they have just
              concluded is how a decision gets postponed and then forgotten. What they confirm
              here appears on the next tab, which is the only one the audit report reads. */}
          <AuditorAssessment id={id!} rev={rev} onChanged={bump} part="matters" />

          {/* Which provisions the evidence brings into scope — independent of whether anything
              differs, which is what makes "reconciled, and a concern remains" reachable. */}
          <RegulatoryCoverage id={id!} workstream={workstream} rev={rev} />

          <Collapsible
            title="Every hypothesis, and how it was settled"
            note="why it was raised, the figures behind it, the law it rests on, and the source records"
          >
            <InvestigationPanel id={id} rev={rev} />
            <FindingsPanel id={id} rev={rev} />
            <AiNarration id={id} rev={rev} />
            <NextBestAction id={id} rev={rev} />
            <TaxpayerResponsePanel
              id={id}
              difference={d.unexplained}
              priorPeriodDeclared={d.prior_period_correction_declared}
              onChanged={bump}
            />
            <CaseContextPanel id={id!} />
            <TaxpayerBrief id={id} />
          </Collapsible>
        </>
      )}

      {/* -------------------------------------------------- 4 · what the auditor has decided */}
      {tab === "auditor" && <AuditorFindingsTab id={id!} rev={rev} onChanged={bump} />}

      {modal && (
        <Modal title={modal.title} onClose={() => setModal(null)}>
          {modal.detail?.type === "invoice-list" ? (
            <>
              <p className="detail-note">{modal.detail.note}</p>
              <InvoiceTable invoices={modal.detail.invoices} />
            </>
          ) : (
            <DetailBody detail={modal.detail} amount={modal.amount} />
          )}
        </Modal>
      )}
      </div>
    </>
  );
}
