# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## What this is

**E-AUDIT** is an AI-powered **VAT Audit Agent for ZATCA** (the Saudi Zakat, Tax
and Customs Authority), built as a stakeholder demo / proof-of-concept.

It begins **when the taxpayer's documents arrive**. Planning is deliberately out of
scope: the client does not supply risk-engine output, a pre-computed reconciliation,
a taxpayer-history feed or a corpus of similar cases, and the request has already
gone out in the auditor's own words before the app sees the case. Everything the
PoC needs is in the files the taxpayer sent.

Two jobs, in order:

1. **Did we get what we asked for?** The auditor drops in the email chain as files; each
   message is parsed (`requests/email_file.py`), merged into a checkable spec
   (`requests/from_email.py` + `requests/chain.py`) which they confirm. The uploaded
   spreadsheets are compared against it — missing items, missing columns, blank mandatory
   fields, period coverage, totals that do not foot — and the chase email is drafted from
   the gaps alone.
2. **What does it mean?** The engine decides which uploaded lines *qualify* for the
   box and the period, sums them into an **expected** return, and compares that with
   what was **declared**. Five agents then propose findings for a deterministic
   adjudicator to settle, and the verdict email and audit report are drafted from
   whatever the auditor accepts.

Both the **output** (standard-rated sales) and **input** (standard-rated purchases)
VAT boxes are qualified and compared separately.

**Two things survived the scope cut**, because the work needs them and they live on
the Intake page rather than in the dossier: the registration's **economic activities**
(revenue matching none of them is the undisclosed secondary-activity outcome, which is
unreachable without the list) and the **audit history** (a repeat of a prior root cause
is the first thing an auditor checks).

Planning, precedent retrieval, risk-engine ingestion and the request planner are
**dormant, not deleted** — `app/precedent/`, `app/risk_indicators.py` and
`app/requests/planner.py` still work and are still tested. Scope has moved twice; they
are cheap to keep and expensive to rebuild.

## The outcome vocabulary (do not paraphrase these)

> An agent raises an outcome **code**. The Authority's own sentence is what gets
> written down.

`app/outcomes.py` holds the auditors' fifteen finding statements verbatim, de-duplicated
to **twelve** distinct outcomes (their 6 and 15 are identical; 8 and 14 differ by two
words; 1 states as non-deductibility what 8/14 state as exclusion). `client_refs` records
the mapping and `test_outcomes.py` asserts all fifteen are covered.

Nothing is phrased ad hoc at a call site. An agent's `claim` is exploratory language
written to be tested and **never goes outbound**; only the vocabulary statement reaches a
report or a taxpayer letter. Outcome statements carry no digits — the amount is computed
by the adjudicator and travels alongside, never interpolated into the sentence.

## Findings rest on evidence, not on tests

A confirmed hypothesis with an `outcome_code` becomes a `Finding` (`agents/findings.py`).
Each one carries a **basis** declared by the adjudicator: the evidence it rests on.

This is not bookkeeping. A sales listing above the return is simultaneously "higher than
declared", "not disclosed", "does not correspond" and — with no trial balance — the
fourth variant, all from **one test over one file**. Summing them reported SAR 1,854,000
against a real excess of SAR 618,000, and the taxpayer letter stated the same figure four
times. So `exposure()` counts each basis once, documentation risk excludes evidence
already producing an adjustment, and the letter states each amount once with the
alternative readings named beneath it.

The basis comes from the *adjudicator*, not the test name: `trial-balance-absent`
delegates to `listing-vs-declared` and must share its basis or the excess is counted twice.

## Qualify, then sum (do not invert this)

> The rules decide **which documents count**. They do not subtract from a total,
> and they never "explain a gap".

Every e-invoice line is walked through the rule stages *before* anything is
added up (`pipeline/run.py`). A line either **qualifies** for this box and this
period, or it does not — and if it does not, exactly one rule is on record as
the reason. Only the survivors are summed:

```
Σ qualifying lines        = expected
expected − declared       = difference
difference − evidence     = unexplained      (evidence = what the taxpayer showed)
```

There is deliberately **no pre-qualification total**. A "reconstructed from
e-invoices" figure taken before the rules run would correspond to nothing real:
it would have to include documents the rules place in another period and exclude
documents the rules admit, purely so a waterfall could be drawn from it. A
clearance-lag invoice was never in the period, so it is not a deduction — it is
a line in the **funnel** that says why it is not there.

The funnel is therefore a *partition of the population*, not a bridge:
population → one step per rule that set documents aside (count + amount) →
qualifying count and amount. `Composition` then says what the qualifying set is
made of, by document type. `compose()` in `pipeline/run.py` builds both; the UI
shows the funnel as the hero and the three-way comparison beneath it.

## The core invariant (do not break this)

> The **deterministic Python core computes every number.** Claude writes
> **language only** and never introduces a figure.

- The engine (`backend/app/recon_engine.py`) produces every amount and count, and
  the conclusion (`state`).
- Claude emits **no digits** — only placeholder tokens, which the engine
  substitutes with its exact values. The vocabulary is deliberately short and
  lives in `_SCALAR_KEYS` / `placeholder_values()`: `{{declared}}`,
  `{{expected}}`, `{{difference}}`, `{{evidence_total}}`, `{{unexplained}}`,
  `{{materiality}}`, `{{qualifying_count}}`, `{{population_count}}`, plus
  `{{step.OUT-07}}` / `{{step.OUT-07.count}}` for each funnel step and
  `{{evidence.CODE}}` for each item of taxpayer evidence. A rule that sets no
  documents aside has **no token at all** — there is no amount for it to name.
- Every drafted sentence is checked by `verify_claims` / `verify_conclusion`
  (`backend/app/llm/verify.py`) **before display**; on failure there is a
  corrective retry, then an honest deterministic fallback with a status badge.
- **Outbound letters** (request, follow-up, verdict) quote *documents* rather
  than reconciliation scalars, so the placeholder model does not fit them.
  `verify_correspondence` enforces the same rule in substance: every numeric
  literal in the draft must already appear in the engine-authored facts block.
  Claude may repeat a figure it was handed; it may not introduce one.
- **One exception:** the taxpayer-letter reader (`llm.read_letter`) returns the
  single figure the *letter itself states*, as a **draft** the auditor confirms
  in the UI before it is committed.

All model access is funneled through the single boundary `backend/app/llm/service.py`,
which delegates the actual call to `backend/app/llm/provider.py` — the only file that
imports `litellm`. The active model, its provider, and any endpoint override are pure
configuration (`EAUDIT_LLM_MODEL`, e.g. `anthropic/claude-opus-5` or `openai/gpt-4o`;
`EAUDIT_LLM_BASE_URL` for an in-VPC gateway) — swapping provider or model never touches
`service.py`, the agents, the prompts, or the frontend. `service.py` calls two
provider-neutral functions (`provider.stream_text`, `provider.parse_structured`) and never
sees an SDK object or a provider name; the two Anthropic-specific extras the app relies on
(`thinking` extended reasoning, `cache_control` prompt caching) are applied or stripped
inside `provider.py` based on which provider the configured model targets. An
`embedding_model` config field exists (`EAUDIT_EMBEDDING_MODEL`) for a future
embedding-based retrieval feature, independently configurable from the generation model —
it is currently unused, since `precedent/` is deterministic structured-field scoring, not
vector search.

Every deterministic fallback is **complete, sendable output**, not a stub —
degrading to it costs polish, never correctness. That is why the whole app,
including the letters and the investigation, works with no API key.

## Privacy / safety

- **Synthetic demo data only.** The hosted model is called only when
  `settings.data_is_synthetic` is true (see `availability()` in `service.py`).
- The real taxpayer name is pseudonymized (`"Taxpayer A"`) before egress and
  restored for display. The `purchase` and `combined` sub-results are excluded
  from the model context.
- **Never commit real secrets.** `.env` is git-ignored; `.env.example` holds a
  placeholder key. Put your real `ANTHROPIC_API_KEY` in `.env`.

## Stack & layout

React + TypeScript (Vite) · FastAPI · PostgreSQL (schemas `core` + `recon`).

```
backend/app/
  outcomes.py          # the auditors' finding statements — the ONLY outbound wording
  casefile/            # the lifecycle machine (derived, never stored)
  dossier/             # everything ZATCA already holds, assembled in one call
  precedent/           # deterministic retrieval + tally over labelled closed cases
  regulatory/          # the law behind a finding:
                       #   extract_en.py   article boundaries from an image marker + green title
                       #   extract_ar.py   article numbers, and what was amended after 2021
                       #   build.py        both editions joined into a reviewable JSON corpus
                       #   basis.py        which article founds which outcome (reviewed, not retrieved)
                       #   lookup.py       found / needs-validation / not-found
  requests/            # the request/response loop:
                       #   catalog.py      what an auditor can ask for
                       #   email_file.py   read a forwarded .eml / .msg — headers, body, attachments
                       #   from_email.py   recover the spec from one message
                       #   chain.py        merge the spec across a whole chain of them
                       #   planner.py      DORMANT — planning is out of scope
                       #   extract.py      xlsx/csv -> columns, rows, stated totals (every sheet)
                       #   completeness.py requested vs received, deterministically
                       #   threads.py      the correspondence trail + the loop back
                       #   service.py      drives the rounds; recomputes gaps each pass
  pipeline/            # predicates.py (Python ⇄ SQL algebra) + rules.py + run.py
                       #   source.py       lines from an uploaded listing, not the feed
                       #   reconciliation.py  declarative matching against ZATCA's records
  recon_engine.py      # qualify -> expected -> compare with declared (output & input VAT)
  rule_taxonomy.py     # explanation/mistake/risk + precedence stage + difference reason codes
  risk_indicators.py   # the risk-engine vocabulary + which internal source to consult first
  scope.py             # what this PoC reconciles, and what it deliberately leaves out
  priority.py          # composite case prioritization (exposure/deadline/history/quick-win)
  agents/              # contracts, adjudicator, orchestrator (rounds), correspondence
                       #   roster.py          the four agents
                       #   document_tests.py  how each is settled over the rows
                       #   findings.py        confirmed -> the Authority's wording
                       #   calculation.py     the closed query algebra
                       #   calc_language.py   read the stated method without a model
                       #   calc_service.py    ask / check, persisted
                       #   confidence.py      the banded signal composite
                       #   investigation_service.py  runs, persists, merges by key
                       #   zatca_service.py   holds the Authority's extract; compares on demand
                       #   zatca_tests.py     what a mismatch is worth, per basis
  reporting/           # audit_report.py — the Authority's own template, section by section
                       #   edits.py        the auditor's own words, overlaid on the engine's
                       #   render.py       one HTML render serving Word and print
  api/routes.py        # FastAPI endpoints
  models/              # core.py, dossier.py, casework.py, config_tables.py, recon.py
  llm/                 # the ONLY model boundary: service, provider, prompts, verify, schemas
  seed/                # scenarios.py + dossier_seed.py + corpus.py + casework_seed.py
frontend/src/
  pages/               # Overview, Intake, Dossier, Casework, Reconciliation, Rules
  components/          # lifecycle rail, case tabs, AI panels, funnel, findings,
                       # calculations, step emails
  api.ts, ai/          # typed API + SSE streaming helpers
docs/                  # VAT Mistakes Rulebook (66 rules) + rendered page
portal.html            # standalone no-backend build of the workbench (see below)
```

**The sidebar is what is global; the tabs are what is inside a case.** An auditor lands on
**Cases** — the queue, with the priority score and the *Add case* button — and opening one
shows its three modules: **Taxpayer Correspondence** (what we asked, what arrived),
**Investigation** (what the evidence shows), **Audit Report** (what you concluded).

That split is load-bearing rather than cosmetic. The three modules were briefly in the sidebar
pointing at a hard-coded case id, so "Correspondence" opened the demo case whichever case you
were actually working — a link that lied about where it went. Only `Cases` and `Rulebook` are
application-wide; everything else needs to know which case it is about, so it lives on
`CaseTabs`. Opening a case goes to its first module; `Dossier` stays routable at its own path
but is off the tab bar, being a dormant planning-era screen.

## The agents (and what they may not do)

`app/agents/roster.py`. The auditors named three and left the fourth to us; the fourth is
**Evidence & Coverage**, because five of their fifteen statements are its territory. A fifth,
**ZATCA Reconciliation**, is the only one whose evidence is not the taxpayer's.

| Agent | Owns |
|---|---|
| **Regulations** | not entitled to deduct · valid tax invoice conditions · valid credit note conditions |
| **Data Entry** | decimal shift, transposition, out-of-character magnitude |
| **Calculation** | listing exceeds declared · POS/bank exceeds declared · undisclosed sales · unreproduced auditor figures |
| **Evidence & Coverage** | missing supporting documentation · lack of cooperation · documents do not correspond · no trial balance · **undisclosed secondary activity** |
| **ZATCA Reconciliation** | invoices the Authority holds that the listing omits · invoices both sides record differently |

Every one obeys the original contract: it returns a `Hypothesis` carrying **language only**
plus a typed `TestSpec`, and `agents/document_tests.py` settles it deterministically over the
uploaded rows. **No agent states a figure and no agent reaches a conclusion.**

Two fields carry weight:

- **`why`** — the observation that triggered the hypothesis. An auditor has to defend a finding
  to a taxpayer, and "an agent proposed it" is not a defence, so the trigger is recorded next to
  the claim and shown beside the verdict.
- **`outcome_code`** — the vocabulary entry this becomes *if confirmed*. The only route from an
  agent to the words in a report.

**An agent proposes nothing when its preconditions are absent.** Silence is correct behaviour:
a hypothesis that can only ever return "insufficient evidence" wastes the auditor's attention.
"Insufficient evidence" is itself a real verdict — a column that is not there cannot be tested,
and saying so beats a confident answer computed from nothing.

**There is one keying specialist.** `detectors.data_entry_forensics` is out of the roster
because the new Data Entry agent is the same specialist under the name the auditors gave it;
running both put duplicate DE-01s on the case file. `test_roster.py` checks the *combined*
roster for id collisions — each roster was unique on its own, which is how that got through.

**Which roster is live follows the population.** On a case built from an uploaded listing
(`population_source == "document"` — the current scope) the four named agents are the whole
roster. `detectors.reconstruction_analyst` and `detectors.historical_pattern` reason about the
e-invoice feed and the return history, the planning-era inputs, so against a spreadsheet they
have nothing to say — and they carry no `outcome_code`, so a confirmed one produces an agent
name on the screen and no finding under it. They stay live on the feed path, gated in
`orchestrator.investigate` rather than deleted. `detectors.recomputation` runs on **both**
paths: it checks *our* arithmetic, and a case that looks settled because a figure was
transcribed wrongly is exactly the case that must not be waved through.

### The Authority's own invoice records

`pipeline/reconciliation.py` + `agents/zatca_service.py` + `agents/zatca_tests.py`. Optional:
a case with no dataset loaded behaves exactly as it did before.

**The matching is deterministic and is not an agent.** Joining two invoice populations is a
closed problem — normalise the reference, join, diff the fields, count what is on one side and
not the other. A model would make it slower, unreproducible and unauditable, and it would put a
model in front of a figure. The rules are declared the way `pipeline/rules.py` declares
qualification rules: a `ReconRule` names the shape it applies to (`pair` / `unmatched` / `group`
/ `row` / `population`), a predicate and how to describe itself, and may be narrowed to one
`side`. Twelve of them cover omission, value, timing, period, party, duplicates, missing
identifiers and sequence breaks. Adding a comparison is one entry in `RULES`.

**One side is not a comparison.** With only a listing, or only a dataset, every record on the
side that exists matches nothing — and reporting all of them as unmatched would be a fabricated
finding carrying a fabricated amount. `compare()` refuses and names the missing side.

Three details that each exist because the obvious version is wrong:

- **References match normalised and display as written.** `INV-001` and `inv 001` are the same
  invoice, so formatting is not a mismatch — but the auditor has to find the row in their own
  spreadsheet, and `INV001` is not a string that occurs in it.
- **Two rules never describe one disagreement.** A date difference across a month end is ZR-06's
  and not also ZR-05's; a numbering hole is not reported when unnumbered rows already explain it.
- **The amount is read per rule, never summed across them.** An invoice absent from the listing
  is money additional to everything the listing totals; a restated figure is a movement within
  it. The two hypotheses therefore carry **different bases** (`zatca-unmatched`, `zatca-values`),
  which is what stops `exposure()` counting one excess twice.

The agent's part is only the judgement the matcher cannot make: whether a population of
unmatched invoices is worth putting to the taxpayer as undisclosed sales, and whether disagreeing
figures are worth putting as a records defect. It reaches the vocabulary by the same route as
everything else — `SAL-UNDISCLOSED` and `SAL-MISMATCH` — and states no figure.

**The dataset is one row, and the comparison is derived.** `ZatcaDataset` is deliberately not a
`ReceivedDocument` (that table is what the *taxpayer* sent, and this would be checked against
request items nobody asked for) and deliberately not one row per invoice (the listing lives as
extracted content on its document row, and a second exploded copy would be a second truth). A
second upload replaces the first. The comparison itself is recomputed on demand, like the
lifecycle — a pure function of two files, so there is no stale mismatch to reconcile.

## The investigation is remembered, and the auditor decides

Until Phase A the investigation was computed and thrown away: `GET /cases/{id}/investigate`
re-ran the pipeline on every request and returned it without storing a row. Fine for a
read-only display, impossible for anything else — an auditor cannot rule on a hypothesis that
does not exist between page loads, and a report written next week cannot trace a sentence back
to reasoning discarded on render.

`models/investigation.py` gives it a memory. Three rules shape it:

- **A hypothesis is identified by what it claims, not by when it ran.** The natural key is
  `(case_id, hypothesis_id)`, which works because the agents use stable ids (`RG-S1`, `CA-01`)
  rather than minting fresh ones per run. A re-run merges into the same row.
- **A verdict that moves says so.** `superseded_status` keeps the previous one beside the new
  one, and any `AuditorDecision` made before the ground shifted is flagged for re-confirmation
  rather than silently surviving. A refuted hypothesis is never deleted, and one the roster
  stops proposing is marked stale — what was investigated is part of the file.
- **Only what the auditor accepts is a finding.** `AuditorDecision` records accept / reject /
  needs-more-investigation / irrelevant / needs-more-info; `AuditorFinding` holds what the
  auditor saw that no agent has a test for. The AI proposes, the engine settles, the auditor
  decides — and that distinction is visible in the data model, not just the wording.

**Iteration comes from running again, not from a longer pipeline.** `orchestrator.investigate()`
is unchanged and still single-pass; `agents/investigation_service.py` wraps it. The loop
(investigate → ask the taxpayer → investigate again) is legible because each pass leaves an
`InvestigationRun` row behind.

### Confidence is banded, and separate from materiality

`agents/confidence.py` computes a 0–100 composite over seven named signals — data completeness,
documentary evidence, cross-source consistency, regulatory support, independent validation,
contradictory evidence, outstanding information — and the score is kept. **What is shown is a
band** (Strong / Moderate / Limited / Insufficient), because "65% confident" reads as a
calibrated probability nothing here can support, and in a dispute it would be quoted back as
though it had been measured. The signal breakdown is published so the band can be argued with:
"you say limited confidence because there is no trial balance" is a useful conversation in a way
that "you say 65" is not.

No model touches the number — every signal is read from engine output, same division of labour
as everywhere else. And confidence is never merged with the amount beside it: a hypothesis can
be strongly supported and worth very little, or weakly supported and worth a great deal.

## The chain goes in as files, and the headers are the point

`requests/email_file.py` + `requests/chain.py`. Step 1 of a round used to be a textarea: paste
what you sent, and the parser reads it. That works, and it is wrong in four ways that only became
visible once the messages arrived as files instead.

**A pasted message has no sender**, so the parser could not tell the Authority's request from the
taxpayer's reply. That matters because *"please find the sales analysis attached"* matches the
sales-analysis cue exactly as squarely as *"please provide a detailed sales analysis"* does — so
the taxpayer's own reply could create a request item, which is the taxpayer asking themselves for
something and then being chased for it. Only ZATCA's messages define the request; inbound ones go
on the trail and are never read for the spec.

**A pasted message has no date**, so the trail was stamped with the day the auditor got round to
uploading it — putting the request and the chase weeks apart on the same date. `sent_at` now comes
from the `Date` header, is left null when there isn't one, and the display says *sent* or *filed*
accordingly rather than presenting a guess as a fact.

**A pasted message has no attachments.** That is the step that actually costs a round when it is
done by hand: the auditor is holding the words and the spreadsheets together, and the one that
gets missed is the one nobody notices until both sides have waited a month.

**And one email is not the request.** The opening request goes out, half of it comes back, and the
auditor writes again naming what is still outstanding and the column they forgot. Read only the
first message and the spec is missing what was added later; read only the last and it is missing
everything already sent. So `chain.py` reads message by message and merges: items union with the
earliest cue kept (that is the ask the auditor will look for when checking the reading), columns
union (taking only the last message's list would silently drop the seven in the opening request),
the **first** period stated stands with any disagreement *reported* rather than resolved — a
second period is either a typo or a widened scope and a parser cannot know which — and the
**last** deadline wins, because a chase granting ten more working days replaces the date rather
than adding to it.

Files are dropped in any order and filed in sent order; one unreadable file is a line in the
result rather than a rejected upload; and `POST /cases/{id}/threads/emails` shares `_file_email`
with the single-file endpoint so the two cannot drift on direction, dates or attachments.

## The correspondence trail, and the loop back to the taxpayer

`models/correspondence.py` + `requests/threads.py`. Until this existed, an outbound letter was
regenerated on every page load and never stored, so the case file could not say what had actually
been sent — and an investigation that could not settle a hypothesis had no way to ask.

**One thread is open at a time; closed ones accumulate.** A case therefore shows its whole
history — the opening request, the chase, the round that came out of something the investigation
found — without ever leaving "which enquiry does this upload answer" ambiguous. A document filed
against the wrong request is a completeness check answering the wrong question, which is worse
than not having the check. Opening a thread *closes* the previous one rather than refusing: an
auditor with a new question should not have to tidy up the last one first.

**The loop is `threads.open_for_hypothesis()`.** An investigation that cannot settle a hypothesis
on the evidence held is not finished and must not present itself as finished, so:

1. the hypothesis is parked as `pending-info` with the auditor's note — a status that stops an
   unanswered question being read as a settled verdict;
2. a thread opens carrying `origin_hypothesis_id`, seeded with a drafted request that **asks**
   and reaches no conclusion (`fb_information_request` — deterministic, so it works with no key);
3. when a document arrives *on that thread*, `retestable()` says which hypotheses can now be
   settled — compared against the thread, not the case, because a file uploaded for a different
   enquiry is not an answer to this one;
4. re-running the investigation merges into the same rows by natural key and clears the park.

Uploads are accepted whenever a thread is open, with or without a formal `InformationRequest`
behind them. Requiring an issued round rejected exactly the documents this loop exists to
collect.

Every message records **who wrote it** (`auditor` / `ai-assisted` / `ai-drafted` / `taxpayer`).
A letter the auditor wrote, one they approved from a draft, and the taxpayer's own reply are three
different kinds of evidence about a case, and a trail that flattened them would mislead. The
taxpayer's words are kept verbatim: their account of their own records is evidence of what they
say, not of what is true.

### The completeness review, beyond "a file exists"

Four checks were added to `completeness.py`, each because of a specific way the old one was wrong:

- **Every worksheet is read** (`extract.py`). Reading only the first sheet meant a workbook with
  a cover tab in front of the data reported *none* of the requested columns — a false "they did
  not send it", the most expensive way to be wrong, because it costs the taxpayer a round trip
  over a file they already supplied. The primary sheet is now chosen by how many recognised
  columns it carries, then by rows — item-agnostic, because extraction is format work and must
  not know what was asked for — and `other-worksheet` names the tab when the columns are
  elsewhere.
- **`sparse-column`** — a non-mandatory column present but blank on more than half the rows.
  Advisory: nobody asked for every row to be populated, but a supplier VAT number on four rows
  of ninety is present without being usable, and better said this round than discovered in the
  analysis.
- **`missing_attachments`** — a taxpayer reply that says "attached" with nothing filed against
  the enquiry. A silent failure: in the trail it reads exactly like an answered request, so both
  sides wait. The check claims only that the words and the files disagree.

`completeness.assessment()` then presents the same gaps in **four words an auditor uses** —
Received / Missing / Incomplete / Needs auditor review. It is presentation over the existing
rows, derived fresh every time, so a fixed gap changes the word with no state to reconcile. The
distinction that earns its place is **incomplete** against **needs auditor review**: the first is
a defect the taxpayer must fix, the second is the checker admitting it cannot decide. A chase
letter written from the second asks for something that was already sent.

## The report is a draft a person signs

`reporting/edits.py` + `models/reporting.py`. Two things had to be true before the Audit Report
tab was a place an auditor could actually work, and neither was.

**The report and the letter have to say the same thing.** The report was built from the findings
the auditor accepted; the verdict letter was built from `investigate_case` — the engine's own
verdicts. On the seeded case that put a banner reading *"no finding has been confirmed yet"*
directly above a letter to the taxpayer asserting eight findings and most of a million riyals of
tax. Both now read `investigation_service.confirmed_findings`. A related defect sat one level
down: the letter's closing paragraph was chosen from `recon["state"]` alone, so with nothing
accepted it still said *"the Authority will proceed on the basis set out above"*. The computed
difference is a fact the letter may report; on its own it may not carry a proposal, and
`fb_verdict` now says the review is not concluded instead. The verdict is also always drafted,
where it used to appear only once there was something to assert — a panel that vanishes leaves
an auditor unable to tell an application with no letter for them from one that failed.

**Every field is editable, and the edit reaches the document.** `[for the auditor to complete]`
is an instruction — rulings, penalties, a meeting date are judgements the tool has no business
making — and the report named the gap while offering no way to close it. `ReportFieldEdit` is
keyed `(case_id, "<section>::<label>")`; `edits.apply()` overlays the rows in `_audit_report`,
the one place the JSON view, the Word download and the printable page all pass through. That
placement is the design: an edit visible on screen but not in the download would mean the
auditor sends the version they had already corrected.

Three rules keep the editing honest:

- **Nothing here computes.** These are the auditor's words, so the core invariant is untouched —
  the engine still owns every figure. What is new is a third author, and the file records which
  one wrote each line, in the Word file as well as on screen.
- **What was replaced is kept.** `original` travels with the field and with `LetterDraft`, so an
  override is visible and reversible. An override nobody can detect is not an override.
- **An empty save reverts.** Clearing a box restores the engine's value rather than blanking the
  line, and a rewritten letter loses its verifier badge — that badge describes what the checker
  saw, and the checker never saw the auditor's words.

`LetterDraft` is deliberately not a `CorrespondenceMessage`: that table is the trail of what was
actually *said*, and filing an unsent draft there would make the case file claim a letter went
out while it is still being written.

## The law behind a finding

`app/regulatory/` + `corpus/`. A finding an auditor can defend has three parts, and until this
landed the application produced only the first and third:

> what the evidence shows · **why that matters in law** · what follows

`SAL-HIGHER` is not a finding because a spreadsheet totals more than a box. It is a finding
because **Article 14** imposes VAT on taxable supplies made in the course of an economic
activity, so supplies the records evidence and the return omits are output tax that was due.
Article 14 founds six of the twelve outcomes; `basis.py` maps all twelve.

**The mapping is reviewed, not retrieved.** Which provision a finding rests on is a legal
judgement, and asking a model to pick one per case would answer differently on two runs over
identical evidence — the one property a tax authority cannot defend. So it is written down,
validated against the corpus at load time, and a code with no entry resolves to `not-found`
rather than to whatever ranks first. `establishes` is an editorial gloss so the finding reads as
a sentence; the article's own text travels with every citation because a paraphrase is what an
auditor checks *against the source*, not something to rely on.

**Three things about these documents that the code exists to handle:**

- **The English article numbers are images.** Visually every article opens *ARTICLE
  THIRTY-SEVEN. RELATED PERSONS*, but only the title half is text — the number is a ~10pt
  picture at the left margin, and pdfplumber, its word-level API and pypdf all return the title
  with the number silently gone. So `extract_en.py` segments on *structure* (that image marker
  plus green title text) and takes the number from position.
- **The number is confirmed by the other edition.** Arabic headers carry the number in words,
  so `extract_ar.py` parses them and `build.py` only trusts a number both editions agree on.
  They agree on all 79.
- **The English is out of date, and says so itself.** It is ZATCA's self-declared *unofficial
  translation*, Eighth Edition of November 2021; the Arabic carries amendments to November
  2024. **31 of 79 articles** are therefore shown in superseded wording — Article 14 among
  them. Those resolve to `needs-validation` with a note naming the amendment year, so
  superseded text is never quoted as the current rule.

The corpus is a **JSON file committed to the repository**, not a database built at startup:
somebody has to be able to read what the application believes Article 14 says without running
anything, and `git diff` has to show it when that changes. Rebuild with
`python -m app.regulatory.build`.

`HypothesisRegulatoryRef` rows are written on every run — including `not-found` ones, because a
missing row and "nobody looked" are indistinguishable. The regulatory leg of the confidence
composite reads from the same lookup, so it is live rather than the flat zero it scored before.


## The auditor's own arithmetic

`app/agents/calculation.py` answers questions off the uploaded documents and checks figures the
auditor worked out by hand. **The model never does arithmetic**: a described method is
translated into a `CalcQuery` from a closed algebra, and Python executes it. A misread method
therefore surfaces as a visible wrong query, never as a wrong number wearing the engine's
authority.

The input is a sentence, because that is how the auditors said they work — *"I calculated X, Y,
Z. This is what I got. Can you check it?"* Reading it has two passes:

- **`calc_language.read_method` first.** A total of a named column over a named file is a cue
  table, not judgement. It also lifts the figure out of the sentence (`stated_amount_in`), so
  nothing has to be retyped into a separate box. This is what keeps the feature alive with no
  API key — the alternative was a dead panel, not a degraded one.
- **`llm.parse_calculation` for the rest.** Only what the first pass declines.

Four refusals matter more than any of that:

- A method carrying a **condition** the deterministic pass cannot express — "for January only",
  "excluding the credit notes", "over SAR 50,000" — is **declined outright**, never flattened to
  a bare aggregation. Totalling the whole file and then reporting the auditor's *correct* figure
  as a disagreement is the most expensive mistake this agent can make.
- A method outside the algebra is reported **not-checkable** rather than approximated by a query
  that answers something else.
- With several documents on a case and none named, the agent **asks which** rather than
  defaulting to the largest table. Answering a sales question off the purchase listing is
  precisely the error this agent exists to catch.
- An auditor-supplied query is used verbatim and never sent to a model — there is nothing to
  interpret, and interpreting it anyway would only add a way to get it wrong.

A cell with nothing readable in it is **skipped, not counted as zero** — the same rule the
population follows — and the explanation says how many were skipped. An auditor comparing
against their own sheet cannot otherwise tell that "over all 22 rows" involved 19.

## Where the lines come from

`app/pipeline/source.py`. The taxpayer's uploaded listing **is** the population; the e-invoice
feed is the fallback for cases with no upload. What a spreadsheet cannot say is stated rather
than assumed:

- **No clearance status** — every row is `reported`, never `cleared`.
- **Usually no delivery date**, so the tax-point rules simply never match. They are not assumed
  satisfied; the funnel shows no timing step, which is the honest reading. A listing that *does*
  carry delivery dates fires them normally.
- **No counterparty class**, so the government-platform rule cannot fire.

Fewer rules can act on a listing than on an e-invoice feed, so the expected figure sits closer
to the raw total. That is a property of the evidence, not a weakness in the engine.

A row with no readable VAT amount is **skipped, not summed as zero** — a blank cell is a
completeness defect the checker already reports, and counting it as nothing would quietly shrink
the expected figure. The UI names the document the figures came from, and when the response
still has blocking gaps the figure is labelled a **floor** rather than a settled expected
return.

## The rule taxonomy (do not collapse this back)

The rulebook's 66 entries are three different kinds of object, and the engine
depends on the distinction:

- **explanation** — a legitimate reason a document does not belong in this box or
  this period (credit notes, tax-point timing). Changes **which documents
  qualify**, and so changes the expected figure itself.
- **mistake** — a taxpayer error. Becomes a **finding**.
- **risk** — a behavioural or data-quality signal. Feeds **prioritisation only**,
  and must never change which documents qualify.

Each rule also carries a `stage` (its place in the population → identity → status
→ tax-point → category → adjustment → aggregation → timing → materiality → risk
precedence) and a `reason_code` describing *which class of difference* it is about.
Reason codes describe the phenomenon; `kind` carries the verdict.

Rules are declared in `pipeline/rules.py`, not hard-coded in the engine.
**Wiring a rule into the live engine means appending one `QualificationRule`** —
the engine, the API's `wired` flag and the UI's "● live" badge all follow from it.
Guarded by `backend/tests/test_rules.py`.

A rule may be **scoped** by `direction`, `sectors` or `counterparty_class`,
because the expected relationship is not the same for every taxpayer — a
government supply may not be recognised until it clears the procurement platform,
months after the transaction period (OUT-11). The scope lives *inside* the
predicate, so it travels into `sql_when()`: a scope applied only in Python would
mean the batch path silently ran the rule on every taxpayer, which is the one bug
the predicate algebra exists to prevent. `test_pipeline.py` asserts the two agree.

## Two standalone HTML files (they are not the same thing)

- **`portal.html`** — a working re-implementation of the deterministic core in JavaScript.
  Toggling a rule there re-runs `qualify()` and moves the expected figure. It is the offline
  *product*, and it is currently several passes behind (see the drift note below).
- **`demo.html`** — a **static walkthrough**, generated from live API responses by
  `python -m app.demo_page`. Nothing in it recomputes and the controls do not act; the page says
  so at the top. It exists so someone can see how the application looks now without standing up
  Postgres, the API and Vite. Regenerate it whenever the UI changes — being generated is what
  stops it drifting into describing a product that no longer exists.

## The standalone portal

`portal.html` is a single self-contained build of the workbench — no backend, no
database, no build step. It ports `theme.css` verbatim and re-implements the
deterministic core in JavaScript over the seeded demo data, so the qualification
funnel, the rulebook toggles, the four agents, the findings and the taxpayer-response
loop all still recompute in the browser — toggling a rule re-runs `qualify()` and moves
the expected figure, and a figure you record is recomputed from the embedded rows the
same way Python recomputes it.
Its AI panels show the same deterministic fallbacks the app renders with no API
key.

Uploading is the one thing a static file cannot do, so the received documents are embedded
**with their rows** — which is what lets the source seam, the agents and the calculation
panel all work offline.

Its rule is **port what the user can change, embed what they cannot.** The
reconciliation, priority, investigation and the lifecycle rail all move when a
rule is toggled or a taxpayer response is recorded, so they are ported to JS. The
dossier, precedent and the seeded correspondence round cannot move without a
backend — there is nothing to upload and no corpus to re-search — so the Python
output is embedded exactly. That is precision, not a shortcut, and the split
should stay explicit.

If you change the engine, the seed data or the rule taxonomy, regenerate it — the
JS port is validated field-by-field against the Python engine's output (currently
12,713 comparisons, 0 failures).

> **Known drift, as of the imports/RCM/zero-rated/prior-period/rounding/POS scope
> expansion:** the Python engine changed (a new zero-rated qualification path, the
> rounding adjustment, the confirmed-evidence categories, the POS request-state check)
> and `portal.html` has **not** been re-ported — by explicit scope decision for that
> pass, not an oversight. There is no regeneration script for this port; it is a
> hand-written JS mirror, kept in sync manually. Re-port before relying on
> `portal.html` for a demo that needs any of those six items.
>
> **The same applies to everything from the three-module pass** — the correspondence trail
> and the Investigation→Correspondence loop, the four-way completeness presentation,
> multi-sheet extraction, persisted hypotheses with auditor decisions and confidence bands,
> and the ZATCA reconciliation. None of it is ported. Several of these need a backend by
> nature (there is nothing to upload and no dataset to load), so the split the port has
> always kept — port what the user can change, embed what they cannot — puts them on the
> embed side or out of scope entirely.

**Manual case creation ("Add Case") is ported, but not the same feature.** `portal.html`
has no database, so a case created there is written to that browser's `localStorage`
instead — visible only in the browser that created it, gone if that storage is cleared,
and never seen by another auditor or another device. The real app's version is a
database row every auditor with access to the deployment can see. "Reset demo" clears the
locally created cases the same way re-seeding drops the real database's. This is the
capability boundary the standalone build was always going to have for this feature; the
form and the case-creation logic (case-ID generation, taxpayer reuse by VAT, the fallback
wiring into the audit report's `[not held]` fields) are the real, hand-ported JS mirror.

## Running locally

**1. Database** (Postgres on port **5433**):

```bash
docker compose up -d
```

**2. Backend** (FastAPI on port **8000**):

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows; use bin/activate on macOS/Linux
pip install -r requirements.txt
python -m app.seed.seed                            # drop, create, load 65 rules + demo cases
# LiteLLM reads the credential env var for whichever provider EAUDIT_LLM_MODEL names
# (ANTHROPIC_API_KEY by default) from the environment for AI features:
export $(grep -v '^#' ../.env | xargs)             # or set the vars however you prefer
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Config comes from environment variables (`EAUDIT_` prefix, see
`app/config.py`); the defaults already match `docker-compose.yml`, so only
`ANTHROPIC_API_KEY` needs to be supplied for the AI layer. Without it, the AI
features degrade gracefully to deterministic drafts.

**3. Frontend** (Vite on port **5174**):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5174.

### Gotchas

- Ports **5433** (Postgres), **8000** (API), **5174** (Vite) are chosen to avoid
  common local collisions (5432/5173).
- The Vite dev proxy targets **`http://127.0.0.1:8000`**, not `localhost`, to
  avoid a Windows IPv6 (`::1`) resolution issue — keep it that way.
- Re-seeding (`python -m app.seed.seed`, or the in-app **Reset demo** button)
  drops and recreates all tables. Synthetic data only.

## Conventions

- Branding is **ZATCA**. Keep the app ZATCA-themed; do not introduce other
  brands.
- Frontend build check: `npm run build` (runs `tsc --noEmit` + Vite build).
- Backend syntax check: `python -m compileall -q app`.
- Guard tests: `pytest backend/tests` (500 at last count). Three layers, and they answer
  different questions — keep them apart:
  - **unit** (`test_roster.py`, `test_pipeline.py`, `test_calculation.py`, …) — is this piece
    right, on a fixture built to isolate it?
  - **SIT** (`test_sit_agents.py`) — do all four agents behave over realistic KSA VAT material?
    Every scenario asserts what must *not* be raised as well as what must.
  - **UAT** (`test_uat_journey.py`, `test_uat_edge_cases.py`) — can an auditor do the job, over
    HTTP, with no API key? The journey walk plus the awkward cases a stakeholder reaches for.
  `test_uat_journey.py` needs `httpx` (`pip install -r backend/requirements-dev.txt`); it skips
  rather than fails without it.
- When editing the engine, remember: **the numbers live in Python, the words
  live in Claude.** If a change would have Claude produce a figure, route the
  figure through a placeholder instead — or, for outbound letters, put it in the
  facts block so `verify_correspondence` will accept it being repeated.
- **Qualify, then sum.** If a change would introduce a total taken before the
  rules run, or word a rule as subtracting from one, it is the wrong shape — the
  rule decides which documents are in the box, and the sum follows.
- **Deterministic first, model second.** Anything checkable is a check: column
  presence, blank fields, period coverage, whether a total adds up. Only
  genuinely judgement-shaped questions go to a model, and they are checked after.

## Inputs still needed from the auditors

- ~~The **audit report template**~~ — supplied. `app/reporting/audit_report.py` builds its six
  sections in the template's own order. A field the case cannot answer says which kind of gap it
  is: `[not held]` for something ZATCA holds in another system, `[for the auditor to complete]`
  for a judgement the tool has no business making. Filling either from a guess would put an
  invented fact under the Authority's letterhead.
- A **real (redacted) information request** — it defines `required_columns`, and
  the completeness checker is only as good as that spec.
- ~~The regulations articles~~ — supplied. Both editions of the Implementing Regulations are
  in `corpus/raw/`, and `app/regulatory/` turns them into the citations findings rest on. What
  is still outstanding is narrower: `agents/document_tests.py:BLOCKED_TERMS` is still twelve
  substrings rather than a lookup against Article 50's own sub-clauses, and the article's
  exceptions (re-supply, statutory obligation, the restricted-vehicle carve-outs) are not
  modelled at all — which is why that test reports "needs review against the article" rather
  than a disallowance.
- A **real (redacted) request email.** `requests/from_email.py` is written against a
  conventional one; the cue table is only as good as the phrasing auditors actually use.
