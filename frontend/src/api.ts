import type { AiSource } from "./ai/ai";

const BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

async function putJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

/* ------------------------------------------------- the auditor's standing AI instructions
   One per case, reaching every module. Steers wording and emphasis; it cannot reach a figure,
   a verdict or a test — those are computed in Python before any sentence is written. */

export interface CaseInstructions {
  case_id: string;
  text: string;
  /** Paused instructions are kept, not deleted — a different act from clearing them. */
  enabled: boolean;
  updated_at: string;
  updated_by: string;
  max_length: number;
}

/* ---------------------------------------------- approve or challenge what we concluded
   Every check here is defensible and every one of them can be wrong. A challenge is recorded
   against the item with a reason, and it changes something: a challenged gap stops being
   chased. */

export type ReviewVerdict = "approved" | "challenged";

export interface ItemReview {
  verdict: ReviewVerdict;
  /** Required on a challenge — "the auditor disagreed" alone is not actionable. */
  note: string;
  by: string;
  at: string;
}

export type ReviewKind = "completeness-item" | "zatca-mismatch";

export const saveReview = (
  id: string, item_kind: ReviewKind, item_key: string,
  verdict: ReviewVerdict | "", note = "",
) => putJSON<{ case_id: string; reviews: Record<string, ItemReview> }>(
  `/cases/${id}/reviews`, { item_kind, item_key, verdict, note });

export const getInstructions = (id: string) =>
  getJSON<CaseInstructions>(`/cases/${id}/instructions`);

export const saveInstructions = (id: string, text: string, enabled = true) =>
  putJSON<CaseInstructions>(`/cases/${id}/instructions`, { text, enabled });

export interface PriorityScore {
  score: number;
  band: string;
  driver: string;
  at_stake: number;
  deadline_days: number | null;
  prior_findings: number;
  signals: { exposure: number; deadline: number; history: number; quickwin: number };
}
export interface CaseRow {
  case_id: string;
  taxpayer: string;
  vat_no: string;
  sector: string;
  period: string;
  reason: string;
  risk: string;
  referral_priority: string;
  status: string;
  scenario: string;
  priority: PriorityScore;
}

/** One case's own header facts. The list carries these too, but a header that waits for the
 *  whole queue to load is a header that flashes empty on every case you open. */
export interface CaseDetail {
  case_id: string;
  status: string;
  reason: string;
  period: string;
  taxpayer: { name: string; vat_no: string; sector: string };
}

export const getCaseDetail = (id: string) => getJSON<CaseDetail>(`/cases/${id}`);

/* ---- manual case creation — the only route a case exists through, since there is no
   live risk-engine integration in this PoC. */
export interface NewCaseTaxpayerIn {
  name: string;
  vat_registration_number: string;
  ind_sector?: string;
  economic_activities?: { isic: string; description: string; primary: boolean }[];
  contact_phone?: string;
  contact_email?: string;
  contact_address?: string;
  audited_before?: boolean;
  audited_before_note?: string;
}
export interface NewCaseIn {
  case_id?: string;
  period_from: string;   // YYYY-MM-DD
  period_to: string;
  creation_date?: string;
  creation_reason?: string;
  audit_manager?: string;
  audit_supervisor?: string;
  audit_officer?: string;
  taxpayer: NewCaseTaxpayerIn;
}
export const createCase = (body: NewCaseIn) => postJSON<{ case_id: string }>("/cases", body);

export type RuleKind = "explanation" | "mistake" | "risk";

export interface RuleRow {
  code: string;
  family: string;
  title: string;
  explains_gap: string;
  gap_band: string;
  severity: string;
  severity_band: string;
  root_cause_code: string;
  enabled: boolean;
  /** what kind of object this rule is: explains a difference, accuses a mistake, or flags risk */
  rule_kind: RuleKind;
  /** where it sits in the evaluation precedence (population → … → risk) */
  stage: string;
  /** which class of difference it describes (T/S/D/A/R taxonomy) */
  reason_code: string;
  reason_label: string;
  /** true when the live engine acts on it — toggling it changes which documents qualify */
  wired: boolean;
}

/* ---- investigation (app/agents) --------------------------------------------
   Agents propose typed tests; a deterministic adjudicator settles them against the
   engine. Nothing here is model output, which is why it renders without an API key. */
export type AdjudicationStatus = "confirmed" | "refuted" | "insufficient-evidence";

export interface Hypothesis {
  id: string;
  agent: string;
  claim: string;
  /** what the agent saw on the case file that made this worth testing */
  why: string;
  /** the outcome in the Authority's vocabulary this becomes if confirmed */
  outcome_code: string;
  reason_code: string;
  test: { kind: string; box: string; params: Record<string, unknown> };
  evidence_refs: string[];
  confidence: "high" | "medium" | "low";
}

/** A confirmed hypothesis, worded by the Authority's own vocabulary. This — never an
 *  agent's exploratory `claim` — is what reaches the report and the taxpayer letter. */
export interface Finding {
  code: string;
  statement: string;
  amount: number;
  effect: "increases-output" | "disallows-input" | "documentation";
  direction: string;
  agent: string;
  hypothesis_id: string;
  /** the evidence this rests on; findings sharing a basis are readings of one amount */
  basis: string;
  why: string;
  explanation: string;
  detail: Record<string, any>;
}
export interface Exposure {
  increases_output: number;
  disallows_input: number;
  documentation_at_risk: number;
  total: number;
  count: number;
  distinct_bases: number;
}
export interface Adjudication {
  hypothesis_id: string;
  status: AdjudicationStatus;
  amount: number;
  detail: Record<string, unknown>;
  explanation: string;
}
export interface CaseFileEntry {
  seq: number;
  round: number;
  kind: "fact" | "hypothesis" | "adjudication" | "objection" | "conclusion";
  agent: string;
  payload: Record<string, any>;
}
export interface Investigation {
  case_id: string;
  rounds: number;
  entries: CaseFileEntry[];
  hypotheses: Hypothesis[];
  adjudications: Adjudication[];
  leading: string | null;
  conclusion: string;
  unexplained: number;
  source: string;
  findings: Finding[];
  exposure: Exposure;
}

export interface ScopeItem {
  item: string;
  detail?: string;
  note?: string;
  reason_code?: string;
  reason_label?: string;
}
export interface ScopeCard {
  headline: string;
  in_scope: ScopeItem[];
  out_of_scope: ScopeItem[];
  tax_point_note: string;
}

export interface Health {
  status: string;
  taxpayers: number;
  cases: number;
  rules: number;
}

export interface ExecOverview {
  open_cases: number;
  exposure_total: number;
  difference_total: number;
  accounted_total: number;
  auto_clearable: number;
  auto_clearable_pct: number;
  needs_action: number;
  findings: number;
  to_review: number;
}

/* ---- the case dossier (app/dossier) ----------------------------------------
   Everything ZATCA already holds on this taxpayer and period. The auditors start a case by
   investigating internal data and only then decide what is genuinely missing; today that
   means opening several systems. `sources[].held` is what lets the planner drop a request
   mechanically rather than relying on the auditor to remember what the Authority has. */
export interface Activity {
  isic: string;
  description: string;
  primary?: boolean;
}
export interface RelatedParty {
  name: string;
  vat_no: string;
  relation: string;
}
export interface TaxpayerProfile {
  id: number;
  name: string;
  vat_no: string;
  legal_form: string;
  bp_type: string;
  sector: string;
  size: string;
  primary_activity: Activity;
  activities: Activity[];
  resident: boolean;
  vat_group_rep: boolean;
  accounting_method: string;
  registered_from: string | null;
  registered_years: number | null;
  deregistered: string | null;
  einvoicing_onboarded: string | null;
  employees: number | null;
  branches: number;
  pos_registered: boolean;
  importer: boolean;
  exporter: boolean;
  related_parties: RelatedParty[];
  compliance: Record<string, number>;
  audit_history: {
    closed_cases: number;
    findings: number;
    total_assessed: number;
    last_outcome: string | null;
    root_causes: string[];
  };
}
export interface RiskSignal {
  code: string;
  label: string;
  value: number;
  weight: number;
}
export interface Referral {
  held: boolean;
  structured: boolean;
  indicator_code: string;
  indicator_label: string;
  description?: string;
  narrative: string;
  score: number | null;
  threshold?: number;
  signals: RiskSignal[];
  model_version?: string;
  generated_at?: string | null;
  consult_first?: string[];
}
export interface DossierSource {
  key: string;
  label: string;
  held: boolean;
  count: number | null;
  as_of: string | null;
}
export interface Dossier {
  case_id: string;
  period_from: string;
  period_to: string;
  status: string;
  audit_type: string;
  sla_due: string | null;
  taxpayer: TaxpayerProfile;
  referral: Referral;
  sources: DossierSource[];
  blocks: Record<string, any>;
}

/* ---- precedent (app/precedent) ---------------------------------------------
   What comparable closed cases turned out to be, and which evidence actually closed them.
   Deterministic retrieval and a Python tally — no model, so the ranked list is stable. */
export interface Tally {
  key: string;
  count: number;
  pct: number;
}
export interface EvidenceStat {
  key: string;
  label: string;
  requested: number;
  decisive: number;
  decisive_rate: number;
}
export interface PrecedentMatch {
  case_id: string;
  similarity: number;
  reasons: string[];
  sector: string;
  size: string;
  result: string;
  root_cause: string;
  rounds: number;
  assessed: number;
  note: string;
}
export interface PrecedentSummary {
  case_id: string;
  indicator: string;
  indicator_label: string;
  comparable: number;
  widened: boolean;
  outcomes: Tally[];
  explained_by: Tally[];
  caused_by: Tally[];
  evidence: EvidenceStat[];
  effort: {
    median_rounds?: number | null;
    max_rounds?: number | null;
    median_days_to_close?: number | null;
    single_round_pct?: number | null;
  };
  assessed: { findings?: number; median?: number | null; total?: number };
  recurrence: { cases: number; findings: number; root_causes: string[]; case_ids: string[] } | null;
  matches: PrecedentMatch[];
}
export interface SuggestedItem {
  key: string;
  label: string;
  kind: string;
  decisive_rate: number;
  requested_in: number;
  decisive_in: number;
  held_internally: string;
  recommend: boolean;
  why: string;
}
export interface PrecedentBriefing {
  agent: string;
  summary: PrecedentSummary;
  narrative: string[];
  hypotheses: Hypothesis[];
  suggested_items: SuggestedItem[];
}

/* ---- the case lifecycle (app/casefile) --------------------------------------
   Five stages, derived from the case's own data rather than stored, so the rail cannot drift
   from reality. No stage advances by itself — every gate is a human decision. */
export type StageState = "done" | "active" | "waiting" | "pending" | "skipped";
export interface LifecycleStage {
  key: string;
  label: string;
  state: StageState;
  owner: string;
  summary: string;
  next_action: string;
  detail: Record<string, any>;
}
export interface Lifecycle {
  case_id: string;
  stages: LifecycleStage[];
  current: string;
  current_label: string;
  waiting_on: string;
  next_action: string;
  complete: boolean;
  /** the auto-clear claim: this case resolved without any request to the taxpayer */
  no_contact_needed: boolean;
  /** every stage that is open right now — an audit is not a wizard, and a case that has
   *  gone back for another document is legitimately in two places at once */
  active: string[];
  /** the review is proceeding while something is still outstanding with the taxpayer —
   *  the normal shape of this work, and not a claim that the case was sent back */
  open_with_taxpayer_during_review: boolean;
}

/* ---- the request/response loop (app/requests) ------------------------------- */
export interface PlannedItem {
  key: string;
  label: string;
  kind: string;
  description: string;
  required_columns: string[];
  mandatory_columns: string[];
  expected_format: string;
  addresses: string[];
  include: boolean;
  reason: string;
  rationale: string;
  decisive_rate: number | null;
  requested_in: number;
  hypothesis_id: string;
}
export interface RequestPlan {
  case_id: string;
  indicator: string;
  held_internally: string[];
  items: PlannedItem[];
  dropped: PlannedItem[];
  notes: string[];
}
export type GapKind =
  | "missing-item"
  | "wrong-document"
  | "missing-column"
  | "empty-mandatory-field"
  | "wrong-period"
  | "arithmetic-mismatch"
  | "wrong-format"
  | "unrequested-document"
  | "too-vague";
export interface Gap {
  id?: number;
  kind: GapKind;
  severity: "blocking" | "advisory";
  detail: string;
  citation: string;
  item_label: string;
  source: string;
  request_item_id: number | null;
  document_id: number | null;
}
export interface LoopItem {
  id: number;
  seq: number;
  key: string;
  kind: string;
  label: string;
  description: string;
  required_columns: string[];
  mandatory_columns: string[];
  expected_format: string;
  rationale: string;
  hypothesis_id: string;
  status: "outstanding" | "received" | "satisfied" | "waived";
  period: string;
}
export interface LoopRound {
  seq: number;
  status: string;
  subject: string;
  issued_at: string | null;
  due_at: string | null;
  answered_at: string | null;
  body: string;
  body_source: string;
  items: LoopItem[];
  gaps: Gap[];
}
export interface LoopDocument {
  id: number;
  filename: string;
  format: string;
  round: number;
  request_item_id: number | null;
  /** replaced by a later upload against the same item — history, not evidence */
  superseded: boolean;
  received_at: string | null;
  columns: string[];
  raw_headers: string[];
  row_count: number;
  stated_totals: Record<string, number>;
  period_from: string | null;
  period_to: string | null;
  note: string;
}
/** One of the four words an auditor actually uses about a requested item.
 *
 *  `incomplete` and `needs-review` are deliberately not the same thing: the first is a defect
 *  the taxpayer has to fix, the second is the checker saying it cannot decide. A chase letter
 *  follows only the first. */
export type ItemState = "received" | "missing" | "incomplete" | "needs-review";

export interface ItemAssessment {
  request_item_id: number | null;
  label: string;
  kind: string;
  state: ItemState;
  state_label: string;
  reason: string;
  documents: string[];
  blocking: number;
  advisory: number;
  kinds: string[];
  /** What a review is stored against — stable across recomputation, unlike the row id. */
  key: string;
  /** The auditor's own verdict on this row, if they have given one. */
  review: ItemReview | null;
  /** Still chased. A challenged row is not: the gap stays on file, the letter stops asking. */
  chased: boolean;
}

export interface Assessment {
  items: ItemAssessment[];
  summary: Record<ItemState, number> & { challenged?: number; approved?: number };
  /** Rows still being chased — challenges excluded. */
  outstanding?: number;
}

export interface LoopState {
  case_id: string;
  round: number;
  status: string;
  complete: boolean;
  rounds: LoopRound[];
  documents: LoopDocument[];
  blocking: number;
  assessment?: Assessment;
  draft?: Draft;
}
export interface Draft {
  text: string;
  source: AiSource | "none";
  verified?: boolean;
  mode?: string;
  violations?: string[];
  note?: string;
}

export const listCases = () => getJSON<CaseRow[]>("/cases");
export const listRules = () => getJSON<RuleRow[]>("/rules");
export const getHealth = () => getJSON<Health>("/health");
export const getOverview = () => getJSON<ExecOverview>("/overview");
export const getScope = () => getJSON<ScopeCard>("/scope");
export const getInvestigation = (id: string) => getJSON<Investigation>(`/cases/${id}/investigate`);

/* ---------------------------------------------------------------- the persisted investigation
   `getInvestigation` above recomputes and returns; nothing it produces survives the response,
   which is why an auditor could read a hypothesis but never rule on one. These work over the
   stored view: the same pipeline, with its conclusions kept so a decision has something to
   attach to and a re-run has something to compare against. */

export type HypothesisStatus =
  | "supported"
  | "partially-supported"
  | "refuted"
  | "inconclusive"
  | "pending-info";

export type DecisionKind =
  | "accepted"
  | "rejected"
  | "needs-more-investigation"
  | "irrelevant"
  | "needs-more-info";

export interface ConfidenceSignal {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  note: string;
}

/** The score exists and is inspectable; the band is what is shown. A percentage headline would
 *  read as a calibrated probability the engine cannot support. */
export interface Confidence {
  score: number;
  band: "Strong" | "Moderate" | "Limited" | "Insufficient" | "";
  signals: ConfidenceSignal[];
}

export interface AuditorDecisionView {
  decision: DecisionKind;
  comment: string;
  decided_at: string;
  decided_on_status: string;
  /** set when a later run moved the verdict under a decision already made */
  needs_reconfirmation: boolean;
}

export interface StoredHypothesis {
  /** the provision this would rest on if accepted; never absent, may be `not-found` */
  regulatory?: Citation;
  hypothesis_id: string;
  agent: string;
  claim: string;
  why: string;
  outcome_code: string;
  reason_code: string;
  test: { kind: string; box: string; params: Record<string, unknown> };
  status: HypothesisStatus;
  superseded_status: string;
  superseded_at_run: number | null;
  amount: number;
  explanation: string;
  detail: Record<string, unknown>;
  confidence: Confidence;
  contradictions: string[];
  needs_info_note: string;
  first_seen_run: number;
  last_seen_run: number;
  /** the roster stopped proposing it; kept on the file rather than deleted */
  stale: boolean;
  decision: AuditorDecisionView | null;
}

export interface InvestigationRunView {
  seq: number;
  trigger: string;
  note: string;
  hypothesis_count: number;
  changed_count: number;
  conclusion: string;
  unexplained: number;
  started_at: string;
}

export interface InvestigationState {
  case_id: string;
  runs: InvestigationRunView[];
  hypotheses: StoredHypothesis[];
  counts: { total: number; decided: number; accepted: number; needs_reconfirmation: number };
  last_run?: { seq: number; changed_count: number };
}

/** One matter the investigation found, as the summary states it.
 *
 *  A card is one *basis*, not one hypothesis: a listing above the return reads four ways off
 *  one test over one file, so the excess is stated once and the other readings sit under
 *  `alternatives`. `observed` is what the engine measured; `reading` is what it would report as
 *  **if the auditor accepts it** — an observation is not a determination. */
export interface SummaryCard {
  key: string;
  kind: "observation" | "unresolved" | "data-quality";
  title: string;
  observed: string;
  reading: string;
  alternatives: string[];
  amount: number;
  confidence: string;
  hypothesis_ids: string[];
  agents: string[];
  outcome_code: string;
  decision: string;
  needs_info: string;
}

export interface InvestigationSummary {
  cards: SummaryCard[];
  totals: {
    at_stake: number;
    observations: number;
    unresolved: number;
    record_defects: number;
    not_supported: number;
    decided: number;
  };
  runs: number;
}

export const getInvestigationSummary = (id: string) =>
  getJSON<InvestigationSummary>(`/cases/${id}/investigation/summary`);

/** The auditor's assessment of the investigation. `text` is theirs once they write; until then
 *  it is `draft`, which the engine produced from what it settled. */
export interface AssessmentView {
  text: string;
  draft: string;
  original: string;
  edited: boolean;
  written_by: string;
  updated_at: string;
  source: string;
  verified: boolean;
  facts: string;
  revised?: boolean;
}

export const getAssessment = (id: string) => getJSON<AssessmentView>(`/cases/${id}/assessment`);

export const saveAssessment = (id: string, text: string) =>
  putJSON<AssessmentView>(`/cases/${id}/assessment`, { text });

export const reviseAssessment = (id: string, instruction: string) =>
  postJSON<AssessmentView>(`/cases/${id}/assessment/revise`, { instruction });

export interface AuditorFindingView {
  seq: number;
  statement: string;
  amount: number;
  outcome_code: string;
  note: string;
  basis: string;
  created_at?: string;
}

export const getInvestigationState = (id: string) =>
  getJSON<InvestigationState>(`/cases/${id}/investigation`);

export const runInvestigation = (id: string, trigger = "auditor-requested", note = "") =>
  postJSON<InvestigationState>(`/cases/${id}/investigation/run`, { trigger, note });

/** Take a ruling back. The hypothesis stays; the auditor's position on it goes. */
export const undecideHypothesis = async (id: string, hypothesisId: string) => {
  const r = await fetch(`${BASE}/cases/${id}/hypotheses/${hypothesisId}/decision`,
                        { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as InvestigationState;
};

export const decideHypothesis = (
  id: string,
  hypothesisId: string,
  decision: DecisionKind,
  comment = "",
) =>
  postJSON<InvestigationState>(`/cases/${id}/hypotheses/${hypothesisId}/decision`, {
    decision,
    comment,
  });

export const addAuditorFinding = (
  id: string,
  body: { statement: string; outcome_code?: string; amount?: number; note?: string },
) => postJSON<AuditorFindingView>(`/cases/${id}/auditor-findings`, body);

export const listAuditorFindings = (id: string) =>
  getJSON<AuditorFindingView[]>(`/cases/${id}/auditor-findings`);
export const getDossier = (id: string) => getJSON<Dossier>(`/cases/${id}/dossier`);
export const getPrecedent = (id: string) => getJSON<PrecedentBriefing>(`/cases/${id}/precedent`);
export const getPlan = (id: string) => getJSON<RequestPlan>(`/cases/${id}/plan`);
export const getLoop = (id: string) => getJSON<LoopState>(`/cases/${id}/requests`);
export const getFollowup = (id: string) => getJSON<Draft>(`/cases/${id}/followup`);
export const getLifecycle = (id: string) => getJSON<Lifecycle>(`/cases/${id}/lifecycle`);
export const getVerdict = (id: string) => getJSON<Draft>(`/cases/${id}/verdict`);

const post = async <T>(path: string): Promise<T> => {
  const r = await fetch(BASE + path, { method: "POST" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
};

export const openRound = (id: string) => post<LoopState>(`/cases/${id}/requests`);
export const issueRound = (id: string, seq: number) =>
  post<LoopState>(`/cases/${id}/requests/${seq}/issue`);
export const recheck = (id: string) => post<LoopState>(`/cases/${id}/requests/check`);

/** Upload a file the taxpayer sent. The response comes back with the gaps already recomputed. */
export const uploadDocument = async (
  id: string,
  file: File,
  itemId?: number,
): Promise<LoopState> => {
  const body = new FormData();
  body.append("file", file);
  if (itemId != null) body.append("item_id", String(itemId));
  const r = await fetch(`${BASE}/cases/${id}/documents`, { method: "POST", body });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

/** The seeded deficient response, so the upload path can be demonstrated live. */
export const demoResponseFileUrl = `${BASE}/demo/response-file`;

export const reseedDemo = async (): Promise<{ status: string; message: string }> => {
  const r = await fetch(BASE + "/admin/reseed", { method: "POST" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const setRuleEnabled = async (code: string, enabled: boolean) => {
  const r = await fetch(`${BASE}/rules/${code}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const deleteRule = async (code: string) => {
  const r = await fetch(`${BASE}/rules/${code}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export interface LetterExtraction {
  explains_gap: boolean;
  category: string;
  summary: string;
  quote: string;
  proposed_amount: number;
  confidence: string;
  caveat: string;
  source: string;
}

export const readLetter = async (id: string, text: string): Promise<LetterExtraction> => {
  const r = await fetch(`${BASE}/cases/${id}/read-letter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

/* ---- the post-receipt workflow -------------------------------------------
   Planning is out of scope: a case starts when the taxpayer's documents arrive.
   These cover recovering the request spec from the email that was sent, checking
   the auditor's own arithmetic, and the drafts that go back out. */

export interface ParsedRequestItem {
  key: string;
  label: string;
  required_columns: string[];
  mandatory_columns: string[];
  /** the phrase in the email that produced this match, so the parse can be checked */
  cue: string;
  source: "keyword" | "model" | "auditor";
  confidence: "high" | "medium" | "low";
}
export interface ParsedRequest {
  items: ParsedRequestItem[];
  period_from: string | null;
  period_to: string | null;
  due_phrase: string;
  columns_stated: Record<string, string[]>;
  /** asks the parser could not place — for the auditor to resolve, never guessed */
  unmatched: string[];
  source: string;
  needs_confirmation: boolean;
  catalog: { key: string; label: string; kind: string; description: string;
             required_columns: string[] }[];
  /** Present when the spec was read from a filed chain rather than from one message. */
  messages_read?: ChainMessageRead[];
  outbound_read?: number;
  /** The taxpayer's own messages are read for the record, never for what was asked for. */
  inbound_skipped?: number;
  /** Two messages naming different periods: reported, never silently resolved. */
  period_note?: string;
}

/** What one message in the chain contributed to the merged spec. */
export interface ChainMessageRead {
  seq: number;
  direction: "outbound" | "inbound";
  subject: string;
  items: string[];
  note: string;
}

/** One filed email, or one that could not be read. Reported per file so a single bad
 *  attachment does not lose the rest of the drop. */
export interface FiledEmail {
  filename: string;
  ok: boolean;
  subject?: string;
  sender?: string;
  recipient?: string;
  sent_at?: string;
  direction?: "outbound" | "inbound";
  filed?: string[];
  skipped?: string[];
  note?: string;
}

export type CalcStatus = "agree" | "disagree" | "not-checkable" | "ok";

export interface CalcQuerySpec {
  op: string;
  column?: string;
  document?: string;
  filters?: { column: string; op: string; value?: unknown }[];
}
export interface CalcResultDetail {
  status: string;
  value: number | null;
  matched: number;
  scanned: number;
  column: string;
  document: string;
  query: string;
  rows: Record<string, any>[];
  note: string;
}
export interface CalcAnswer {
  status: CalcStatus;
  answer: number | null;
  understood: string;
  note: string;
  detail: CalcResultDetail | Record<string, never>;
  source: string;
}
export interface AuditorCalculation {
  id: number;
  seq: number;
  label: string;
  method: string;
  stated: number;
  document: string;
  query: string;
  understood: string;
  status: CalcStatus;
  computed: number | null;
  delta: number;
  explanation: string;
  source: string;
  detail: Record<string, any>;
}
export interface CalcListing {
  calculations: AuditorCalculation[];
  documents: { filename: string; columns: string[]; row_count: number }[];
}

export interface StepEmail {
  step: "response-check" | "closure";
  kind: "follow-up" | "verdict";
  title: string;
  /** why this draft exists — a draft appears only when it has something to say */
  trigger: string;
  text: string;
  source: string;
  violations?: string[];
  /** The engine's own draft, kept so an edited letter can be restored. */
  generated?: string;
  /** The auditor rewrote it — so the verifier's badge no longer describes this text. */
  edited?: boolean;
  edited_at?: string;
}
export interface StepEmails {
  case_id: string;
  emails: StepEmail[];
  findings: Finding[];
  exposure: Exposure;
}

/** Save the letter as the auditor wrote it. An empty body restores the generated draft. */
export const saveLetter = (
  id: string, kind: "follow-up" | "verdict", body: string, generated = "",
) => putJSON<StepEmails>(`/cases/${id}/letters/${kind}`, { body, generated });

export const parseRequestEmail = (id: string, text: string) =>
  postJSON<ParsedRequest>(`/cases/${id}/request-email/parse`, { text });

/** Read the spec from every message on the round, merged — see `requests/chain.py`. */
export const parseRequestChain = (id: string) =>
  postJSON<ParsedRequest>(`/cases/${id}/request-email/from-chain`, {});

export const askCalc = (id: string, question: string, spec?: CalcQuerySpec) =>
  postJSON<CalcAnswer>(`/cases/${id}/calc/ask`, { question, spec });

export const checkCalc = (
  id: string,
  body: { label: string; method?: string; stated_amount: number;
          document_name?: string; spec?: CalcQuerySpec },
) => postJSON<AuditorCalculation>(`/cases/${id}/calc/check`, body);

export const listCalcs = (id: string) => getJSON<CalcListing>(`/cases/${id}/calc`);

export const deleteCalc = (id: string, calcId: number) =>
  fetch(`/api/cases/${id}/calc/${calcId}`, { method: "DELETE" }).then((r) => r.json());

export const getStepEmails = (id: string) => getJSON<StepEmails>(`/cases/${id}/emails`);

/* ---------------------------------------------------------------- the audit report
   Built from what the auditor accepted, not from every hypothesis the engine confirmed —
   so a case with nothing accepted honestly reports no finding. The Word and printable
   renders come from one HTML render server-side (see backend/app/reporting/render.py). */

export interface ReportTrace {
  statement: string;
  carries_amount: boolean;
  amount: number;
  code: string;
  hypothesis_id: string;
  agent: string;
  basis: string;
  why: string;
  explanation: string;
  evidence: {
    document: string;
    rows: number | null;
    examples: unknown[];
    listing_total?: number | null;
    declared?: number | null;
  };
  source: string;
  confidence_band: string;
  decided_at: string;
  decided_by: string;
  auditor_comment: string;
  regulatory: Citation;
  reads_as: string;
}

export interface ReportField {
  label: string;
  value: string;
  note: string;
  held: boolean;
  trace: ReportTrace[];
  /** "<section>::<label>" — what an edit is saved against. */
  key: string;
  editable: boolean;
  /** The auditor wrote this line; `original` is what it replaced, so it can be put back. */
  edited: boolean;
  original: string;
  edited_at?: string;
  edited_by?: string;
}

export interface ReportSection {
  title: string;
  fields: ReportField[];
}

export interface AuditReportDoc {
  title: string;
  case_id: string;
  taxpayer: string;
  sections: ReportSection[];
  completeness: { fields: number; filled: number; outstanding: number };
  /** How many fields the auditor has written themselves. */
  edited_fields?: number;
}

export const getAuditReport = (id: string) =>
  getJSON<AuditReportDoc>(`/cases/${id}/audit-report`);

/** Write one field in the auditor's own words. An empty value reverts it to the engine's.
 *  Returns the whole report so the completeness tally and the download stay in step. */
export const saveReportField = (id: string, key: string, value: string, original = "") =>
  putJSON<AuditReportDoc>(`/cases/${id}/audit-report/fields`, { key, value, original });

/** Served as application/msword — styled HTML that Word opens and can edit, not a native
 *  .docx binary. Honest about what it is; good enough for a draft an auditor works on. */
export const auditReportDocUrl = (id: string) => `/api/cases/${id}/audit-report.doc`;
/** The same render with a print stylesheet — the browser's own print-to-PDF does the rest. */
export const auditReportHtmlUrl = (id: string) => `/api/cases/${id}/audit-report.html`;

/* ---------------------------------------------------------------- the correspondence trail
   One enquiry is open at a time and closed ones are kept, so a case shows its whole history
   without leaving "which conversation does this upload answer" ambiguous. */

export interface ThreadMessage {
  seq: number;
  direction: "outbound" | "inbound";
  sender: string;
  recipient: string;
  subject: string;
  body: string;
  drafted_by: "auditor" | "ai-assisted" | "ai-drafted" | "taxpayer";
  audit_stage: string;
  in_reply_to_seq: number | null;
  sent_at: string;
  created_at: string;
}

export interface ThreadDocument {
  id: number;
  filename: string;
  file_format: string;
  rows: number;
  columns: number;
}

export interface CorrespondenceThread {
  id: number;
  seq: number;
  subject: string;
  status: "open" | "closed";
  origin: "initial" | "investigation-request" | "clarification";
  /** set when this enquiry exists because a hypothesis could not be settled without it */
  origin_hypothesis_id: string;
  opened_at: string;
  closed_at: string;
  messages: ThreadMessage[];
  documents: ThreadDocument[];
}

export interface Retestable {
  hypothesis_id: string;
  claim: string;
  documents: string[];
  note: string;
}

export interface ThreadState {
  case_id: string;
  threads: CorrespondenceThread[];
  open_thread_id: number | null;
  /** parked hypotheses whose enquiry has since received something */
  retestable: Retestable[];
  unfiled_documents: { id: number; filename: string }[];
  /** replies that claim an attachment with nothing filed against the enquiry */
  missing_attachments: {
    thread_id: number;
    thread_seq: number;
    message_seq: number;
    detail: string;
  }[];
}

export const getThreads = (id: string) => getJSON<ThreadState>(`/cases/${id}/threads`);

/** The VAT return against the taxpayer's own invoice registers.
 *
 *  Deliberately not part of `/reconcile`: that endpoint answers which documents *qualify* for a
 *  box and every figure in it has been through the rules. These three numbers have had no rule
 *  act on them — the listing's own arithmetic, the return's own figure, and the gap. */
export interface RegisterInsight {
  key: string;
  headline: string;
  detail: string;
  count: number;
  amount: number;
  invoices: Record<string, unknown>[];
  ask: string;
}

export interface Register {
  direction: "sale" | "purchase";
  title: string;
  box_label: string;
  box_code: string;
  note: string;
  /** False when no listing is on file. Then there is no difference — there is a missing file. */
  comparable: boolean;
  not_comparable_note: string;
  document: { filename: string; rows: number; columns: string[] } | null;
  invoice_count: number;
  credit_note_count: number;
  register_total: number;
  declared: number;
  difference: number;
  materiality: number;
  risk: string;
  risk_label: string;
  invoices: Record<string, unknown>[];
  insights: RegisterInsight[];
}

export interface RegistersView {
  case_id: string;
  period_from: string;
  period_to: string;
  return_on_file: boolean;
  registers: Register[];
}

/* ---------------------------------------------------------------- stage 0: evidence
 * What arrived, read for what it is rather than for what it is called. Everything below
 * keys off this — which comparisons are possible, which controls are testable. */
export interface DatasetRole {
  role: string;
  column: string;
  side: string;
  confidence: "high" | "medium" | "low";
  why: string;
  shape: string;
}

export interface QualityFlag {
  code: string;
  detail: string;
  count: number;
  column: string;
  severity: "advisory" | "blocking";
  rows: number[];
}

export interface DatasetProfile {
  filename: string;
  document_id: number;
  provenance: "taxpayer" | "authority";
  dataset_type: string;
  dataset_label: string;
  workstream: string;
  confidence: "high" | "medium" | "low" | "confirmed";
  why: string;
  alternatives: string[];
  record_count: number;
  column_count: number;
  columns: string[];
  roles: DatasetRole[];
  unmapped_columns: string[];
  date_min: string | null;
  date_max: string | null;
  currencies: string[];
  quality_flags: QualityFlag[];
  transformations: { column: string; row_number: number; original: string;
                     normalised: string; transformation: string; reason: string }[];
  overridden: boolean;
  /** What the profiler read, kept beside an auditor's correction so it stays reviewable. */
  read_as?: { dataset_type: string; label: string; confidence: string; why: string };
}

export interface EvidenceState {
  case_id: string;
  period_from: string;
  period_to: string;
  datasets: DatasetProfile[];
  by_workstream: { sales: string[]; purchases: string[] };
  available_types: string[];
  needs_attention: {
    unclassified: string[];
    low_confidence: string[];
    blocking_quality: (QualityFlag & { filename: string })[];
  };
  known_types: { key: string; label: string; workstream: string }[];
}

export const getEvidence = (id: string) => getJSON<EvidenceState>(`/cases/${id}/evidence`);

export const setDatasetType = (id: string, filename: string, datasetType: string,
                               note = "", workstream = "") =>
  putJSON<EvidenceState>(`/cases/${id}/evidence/override`,
                         { filename, dataset_type: datasetType, workstream, note });

/* ---------------------------------------------------------------- stage 1: reconciliation */
export interface ReconContribution {
  side: "a" | "b" | "both";
  reference: string;
  amount: number;
  row_number: number | null;
  note: string;
}

export interface ReconResult {
  id: string;
  /** the pairwise comparison that now owns this question, if one does */
  superseded_by?: string;
  title: string;
  workstream: "sales" | "purchases";
  metric: string;
  metric_label: string;
  status: string;
  status_label: string;
  attention: number;
  value_a: number;
  value_b: number;
  variance: number;
  variance_pct: number;
  residual: number;
  label_a: string;
  label_b: string;
  source_a: string;
  source_b: string;
  grain: "total" | "transaction";
  note: string;
  method: string;
  explanation: string;
  causes: { cause: string; label: string; amount: number; side: string; detail: string }[];
  contributions: ReconContribution[];
  tolerance: { name: string; allowance: number; note: string };
  period: Record<string, any>;
  conventions: { side: string; source: string; convention: string; note: string }[];
  quality_notes: string[];
  blocked_by: string[];
  needs: string[];
}

export interface WorkstreamSummary {
  total: number;
  by_status: Record<string, number>;
  runnable: number;
  unexplained_count: number;
  largest_unexplained: number;
  largest_unexplained_from: string;
  not_summed_because: string;
  needs: string[];
}

export interface ReconState {
  case_id: string;
  period_from: string;
  period_to: string;
  return_on_file: boolean;
  workstreams: { sales: WorkstreamSummary; purchases: WorkstreamSummary };
  results: ReconResult[];
}

export const getReconciliations = (id: string) =>
  getJSON<ReconState>(`/cases/${id}/reconciliations`);

/* ---------------------------------------------------------------- stage 2: the regulations */
export interface ControlAssessment {
  control_id: string;
  title: string;
  topic: string;
  applies_to: string;
  article: number;
  paragraph: string;
  requirement: string;
  conditions: string[];
  exceptions: string[];
  evidence_required: { dataset_types?: string[]; roles?: string[] };
  testability: "deterministic" | "ai-assisted" | "manual";
  related: number[];
  source_note: string;
  status: string;
  status_label: string;
  attention: number;
  scope_reason: string;
  detail: string;
  outcome: { result?: string; detail?: string; count?: number; total?: number;
             rows?: number[]; files?: string[] };
  citation: { state: string; article: number; label?: string; title?: string;
              chapter?: string; text?: string; english_current?: boolean;
              last_amended_year?: number | null; note?: string };
  missing_evidence: string[];
}

export interface RegulatoryState {
  review_status: string;
  review_note: string;
  facts: {
    dataset_types: string[]; roles_present: string[];
    vat_treatments: string[]; boxes_filed: string[];
    provenance: Record<string, string[]>;
  };
  summary: {
    assessed: number;
    by_status: Record<string, number>;
    coverage: { controls: number; articles_total: number; articles_covered: number;
                articles_uncovered: number; review_status: string; review_note: string;
                by_testability: Record<string, number> };
    superseded_citations: number;
  };
  controls: ControlAssessment[];
}

export const getRegulatoryControls = (id: string) =>
  getJSON<RegulatoryState>(`/cases/${id}/regulatory-controls`);

export const getRegisters = (id: string) =>
  getJSON<RegistersView>(`/cases/${id}/registers`);

/** Open the next round. `origin` is what the trail shows the auditor about why it exists —
 *  a round raised from the investigation that files itself as an opening request tells them
 *  the wrong story about their own case. */
export const openThread = (
  id: string,
  subject = "",
  origin: "initial" | "investigation-request" | "clarification" = "initial",
) => postJSON<ThreadState>(`/cases/${id}/threads`, { subject, origin });

export const recordReply = (id: string, body: string, subject = "") =>
  postJSON<ThreadState>(`/cases/${id}/threads/reply`, { body, subject });

/** The loop: park a hypothesis and ask the taxpayer for what would settle it. */
export const requestInformation = (id: string, hypothesisId: string, note = "") =>
  postJSON<{ thread: ThreadState; draft: Draft; hypothesis_id: string }>(
    `/cases/${id}/hypotheses/${hypothesisId}/request-info`,
    { note },
  );

// ---------------------------------------------------------------- ZATCA's own invoice records

/** One disagreement between the two populations, produced by a named deterministic rule.
 *
 *  `vat_at_stake` is set only by the rules that genuinely carry money, and is read per rule
 *  rather than summed across them — an omitted invoice and a restated one describe different
 *  money, and one total would describe neither. */
export interface ZatcaMismatch {
  code: string;
  category: string;
  severity: "blocking" | "advisory";
  detail: string;
  ref: string;
  field: string;
  listing_value: string;
  zatca_value: string;
  citation: string;
  vat_at_stake: number;
}

export interface ZatcaState {
  /** false when only one side is present — with one, every record would look unmatched */
  comparable: boolean;
  note: string;
  listing_count: number;
  zatca_count: number;
  matched_count: number;
  listing_name: string;
  zatca_name: string;
  mismatches: ZatcaMismatch[];
  categories: { category: string; count: number; blocking: number; vat_at_stake: number }[];
  blocking: number;
  rules: { code: string; category: string; severity: string; note: string }[];
  dataset: {
    id: number;
    filename: string;
    format: string;
    source: string;
    uploaded_at: string;
    row_count: number;
    columns: string[];
    note: string;
  } | null;
}

export const getZatca = (id: string) => getJSON<ZatcaState>(`/cases/${id}/zatca`);

export const uploadZatca = async (id: string, file: File): Promise<ZatcaState> => {
  const body = new FormData();
  body.append("file", file);
  const r = await fetch(`${BASE}/cases/${id}/zatca`, { method: "POST", body });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const removeZatca = async (id: string): Promise<ZatcaState> => {
  const r = await fetch(`${BASE}/cases/${id}/zatca`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

// ---------------------------------------------------------------- the case assistant

/** One turn. `action` is the entry from the closed set this turn ran; `did` is set only when
 *  the turn actually changed something, so an answer reads differently from an action. */
export interface CaseMessage {
  seq: number;
  role: "auditor" | "assistant";
  content: string;
  action: string;
  source: string;
  did: string;
  created_at: string;
}
export interface AssistantState {
  case_id: string;
  messages: CaseMessage[];
  actions: { key: string; label: string; hint: string }[];
}

export const getAssistant = (id: string) =>
  getJSON<AssistantState>(`/cases/${id}/assistant`);

export const askAssistant = (id: string, question: string, action = "") =>
  postJSON<AssistantState>(`/cases/${id}/assistant`, { question, action });

export const clearAssistant = async (id: string): Promise<AssistantState> => {
  const r = await fetch(`${BASE}/cases/${id}/assistant`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

/** Drop a forwarded email onto the round: the message joins the chain, and any spreadsheets
 *  attached to it are filed as received documents without a second upload. */
export const uploadEmail = async (
  id: string,
  file: File,
): Promise<ThreadState & { filed: string[]; skipped: string[]; note: string }> => {
  const body = new FormData();
  body.append("file", file);
  const r = await fetch(`${BASE}/cases/${id}/threads/email`, { method: "POST", body });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status}`);
  return r.json();
};

/** A whole chain in one drop. Filed in sent order, with a result line per file. */
export const uploadEmails = async (
  id: string,
  files: File[],
): Promise<ThreadState & {
  results: FiledEmail[]; read: number; unreadable: number; filed: string[];
}> => {
  const body = new FormData();
  for (const f of files) body.append("files", f);
  const r = await fetch(`${BASE}/cases/${id}/threads/emails`, { method: "POST", body });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `${r.status}`);
  return r.json();
};

// ---------------------------------------------------------------- the regulatory basis

/** The provision a finding rests on.
 *
 *  `state` is the field to read before quoting anything:
 *  - `found` — in the corpus, numbering confirmed, English wording current
 *  - `needs-validation` — the English edition (2021) predates the current Arabic, so the
 *    wording shown is superseded. Article 14 is in this state and founds six of twelve outcomes
 *  - `not-found` — no provision identified. Stored and shown, never silence */
export interface Citation {
  state: "found" | "needs-validation" | "not-found";
  outcome_code: string;
  article: number | null;
  label: string;
  title: string;
  chapter: string;
  /** editorial gloss of what the article establishes — the article's own text is `text` */
  establishes: string;
  consequence: string;
  text: string;
  english_current: boolean;
  last_amended_year: number | null;
  supporting: { article: number; label: string; title: string }[];
  note: string;
}

export interface RegulatoryCoverage {
  loaded: boolean;
  article_count: number;
  english_edition_year: number;
  amended_since_english_edition: number[];
  outcomes_total: number;
  outcomes_with_basis: number;
  outcomes_without_basis: string[];
  problems: string[];
}

export const getRegulatoryCoverage = () =>
  getJSON<RegulatoryCoverage>("/regulatory/coverage");

// ---------------------------------------------------------------- reconciliation dashboard
/** One side of a comparison. `present: false` means the source is not on the case at all —
 *  which is not the same as a total of zero, and is why `total` is nullable. */
export interface CompareSide {
  source: "return" | "register" | "e-invoices";
  label: string;
  origin: string;
  total: number | null;
  count: number | null;
  counted: number | null;
  present: boolean;
}

export interface TreatmentRow {
  treatment: string;
  label: string;
  a_total: number | null;
  b_total: number | null;
  a_count: number;
  b_count: number;
  variance: number | null;
  variance_pct: number | null;
  status: string;
  status_label: string;
}

export interface MatchRow {
  status: string;
  status_label: string;
  reference: string;
  a_records: string[];
  b_records: string[];
  a_amount: number | null;
  b_amount: number | null;
  delta: number | null;
  detail: string;
}

export interface Comparison {
  code: string;
  workstream: "sales" | "purchases";
  title: string;
  question: string;
  metric: string;
  metric_label: string;
  a: CompareSide;
  b: CompareSide;
  runnable: boolean;
  blocked_by: string[];
  needs: string[];
  variance: number | null;
  variance_pct: number | null;
  status: string;
  status_label: string;
  attention: number;
  tolerance: { name: string; absolute: number; percentage: number; note: string; allowance: number };
  treatments: TreatmentRow[];
  matches: MatchRow[];
  /** What the engine wants said about this comparison — e.g. that the totals nearly agree
   *  while the records inside them do not, because they offset each other. Engine-authored,
   *  neutrality-checked, and the reason a status can differ from what the headline suggests. */
  notes: string[];
}

export interface ReconObservation {
  id: string;
  workstream: string;
  pairing: string;
  text: string;
  amount: number | null;
  count: number | null;
  records: string[];
  source_files: string[];
}

export interface ReconException {
  id: string;
  workstream: string;
  pairing: string;
  reconciliation: string;
  category: string;
  kind: string;
  metric: string;
  /** one comparison, one shape of disagreement, one set of records — two exceptions sharing
   *  a basis are one matter and are never added together */
  basis: string;
  a_label: string;
  b_label: string;
  a_value: number | null;
  b_value: number | null;
  variance: number | null;
  variance_pct: number | null;
  affected_count: number;
  records: string[];
  source_files: string[];
  observation: string;
  /** the same matter measured in another metric, not a second matter */
  also_measured: {
    metric: string; metric_label: string;
    a_value: number | null; b_value: number | null;
    variance: number | null; variance_pct: number | null; observation: string;
  }[];
}

export interface Kpi {
  key: string;
  label: string;
  value: number;
  unit: "sar" | "count";
  note: string;
  source: string;
}

export interface DatasetSummary {
  source_dataset: string;
  source_file: string;
  direction: string;
  count: number;
  fields_available: string[];
  unreadable_rows: Record<string, number[]>;
  unreadable_counts: Record<string, number>;
  notes: string[];
}

export interface WorkstreamDash {
  kpis: Kpi[];
  unavailable: { what: string; why: string }[];
  sources: {
    return_on_file: boolean;
    register: DatasetSummary | null;
    einvoices: DatasetSummary | null;
  };
  summary: {
    comparisons_total: number;
    comparisons_run: number;
    with_variance: number;
    exceptions: number;
    largest_exception: number;
    largest_exception_is: string;
    not_summed_because: string;
    needs: string[];
  };
}

export interface ReconDashboard {
  case_id: string;
  period_from: string;
  period_to: string;
  workstreams: Record<"sales" | "purchases", WorkstreamDash>;
  comparisons: Comparison[];
  observations: ReconObservation[];
  exceptions: ReconException[];
}

export const getDashboard = (id: string) =>
  getJSON<ReconDashboard>(`/cases/${id}/dashboard`);
