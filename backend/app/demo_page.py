"""Build a single-file visual demo of the workbench.

Not `portal.html`. That file is a working re-implementation of the deterministic core in
JavaScript — toggle a rule there and the expected figure moves. This is the other thing: a
**static walkthrough** of how the application looks now, with the seeded case's real output
baked in, for showing someone the shape of the product without standing up Postgres, the API
and Vite first.

It is generated rather than hand-written, from live API responses, so it cannot quietly drift
into describing a product that no longer exists — regenerate it and it tells the truth again.
Nothing here recomputes: the numbers are the engine's, captured at build time, and the page says
so rather than implying an engine is running behind it.

    python -m app.demo_page            # reads the running API on :8000
"""
from __future__ import annotations

import html
import json
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8000/api"
CASE = "CASE-2025-0481"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo.html"
THEME = ROOT / "frontend" / "src" / "theme.css"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
        return json.loads(r.read().decode())


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _put(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _delete(path: str) -> None:
    req = urllib.request.Request(f"{API}{path}", method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=30).close()
    except Exception:                                    # noqa: BLE001
        pass


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def sar(n) -> str:
    try:
        return f"SAR {abs(float(n)):,.0f}"
    except (TypeError, ValueError):
        return ""


# ------------------------------------------------------------------ the case list

def case_list(cases: list, open_case: str) -> str:
    """Where an auditor starts: every case they hold, and the way to add one.

    The three modules are a *case's* tabs, not the application's. Landing on them would be
    landing in the middle of one file with no way to see the others, which is not how the work
    begins — you pick up a case, and the modules are what is inside it.
    """
    rows = []
    for c in cases:
        p = c.get("priority") or {}
        band = p.get("band", "")
        pill = {"high": "pri-high", "medium": "pri-medium"}.get(band.lower(), "pri-low")
        cls = "caserow on" if c["case_id"] == open_case else "caserow"
        arrow = '<span class="linklike">open &#9656;</span>' if c["case_id"] == open_case else ""
        # Only the seeded case carries real output, so it is the only row that goes anywhere.
        opens = ' data-open="1"' if c["case_id"] == open_case else ""
        rows.append(
            f'<tr class="{cls}"{opens}>'
            f'<td><span class="pill {pill}">{e(band or "—")}</span></td>'
            f'<td class="mono">{e(c["case_id"])}</td>'
            f'<td><b>{e(c["taxpayer"])}</b><div class="sub">{e(c["vat_no"])}</div></td>'
            f'<td>{e(c["sector"])}</td><td>{e(c["reason"])}</td>'
            f'<td class="mono">{e(c["period"])}</td>'
            f'<td><span class="pill status">{e(c["status"])}</span></td>'
            f'<td>{arrow}</td></tr>')

    return f"""
<header class="page-head"><div><p class="eyebrow">ZATCA · VAT Audit Agent</p>
<h1>Cases</h1><p class="sub">{len(cases)} open · ranked by what is worth looking at first</p>
</div><div><span class="btn">+ Add case</span></div></header>

<div class="panel"><div class="panel-head"><h2>Open cases</h2>
<span class="muted">Ranked by exposure, deadline, history and how quickly they can be settled
</span></div>
<div class="panel-body"><div class="tablescroll"><table class="inv-table"><thead><tr>
<th>Priority</th><th>Case</th><th>Taxpayer</th><th>Sector</th><th>Referral reason</th>
<th>Period</th><th>Status</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="detail-note"><b>Open a case</b> and its three modules appear inside it — Taxpayer
Correspondence, Investigation, Audit Report. They are a case&rsquo;s tabs, not the
application&rsquo;s: <b>Cases</b> is the whole sidebar, because everything else has to know
which case it is about. In this walkthrough only <b>{e(open_case)}</b> carries real output, so
that is the row that opens.</p></div></div>"""


# ------------------------------------------------------------------ the three tabs

def correspondence(loop: dict, threads: dict) -> str:
    a = loop.get("assessment") or {"items": [], "summary": {}}
    t = (threads.get("threads") or [{}])[0]
    msgs = t.get("messages") or []
    docs = t.get("documents") or []
    rows = a["items"]
    outstanding = [i for i in rows if i["state"] != "received"]

    def step(n, title, note, body):
        return (f'<section class="rstep"><div class="rstep-head"><span class="rstep-n">{n}</span>'
                f'<h3>{e(title)}</h3><span class="sub">{e(note)}</span></div>'
                f'<div class="rstep-body">{body}</div></section>')

    chain = "".join(
        f'<div class="msg msg-{e(m["direction"])}"><div class="msg-meta"><b>{e(m["sender"])}</b>'
        f'<span class="sub">→ {e(m["recipient"])} · AI draft — review before sending</span></div>'
        f'<pre class="letterpre">{e(m["body"])}</pre></div>' for m in msgs)
    chain += ('<div class="dropzone"><b>Drop the email chain here</b>'
              '<span class="sub">.eml or .msg — as many as you like, filed in the order they '
              'were sent, with their attachments</span></div>'
              '<div class="row-actions">'
              '<button class="btn" disabled>Read what was asked for</button></div>'
              '<p class="detail-note">The chain goes in as files rather than as pasted text '
              'because the headers are the part that matters: they say who sent each message, '
              'when, and what came attached. The spreadsheets land in step 2 without a second '
              'upload, the messages sort into the order they were actually sent, and '
              '<b>only ZATCA&rsquo;s own messages define the request</b> — the taxpayer writing '
              '&ldquo;please find the sales analysis attached&rdquo; is not them asking '
              'themselves for it.</p>')

    received = ('<div class="dropzone"><b>Drop what the taxpayer sent here</b>'
                '<span class="sub">.xlsx, .xlsm, .csv — read into columns and rows on arrival'
                '</span></div>')
    received += "".join(
        f'<div class="docrow"><b>{e(d["filename"])}</b>'
        f'<span class="sub">{d["rows"]} rows · {d["columns"]} columns</span></div>' for d in docs)

    pills = {"missing": "pri-high", "incomplete": "pri-high",
             "needs-review": "pri-medium", "received": "pri-low"}
    bar = "".join(
        f'<div class="statechip {pills[s]}"><b>{a["summary"].get(s, 0)}</b>'
        f'<span>{"need review" if s == "needs-review" else s}</span></div>'
        for s in ("missing", "incomplete", "needs-review", "received"))
    compare = f'<div class="statebar">{bar}</div><div class="assesslist">' + "".join(
        f'<div class="assessrow {e(i["state"])}"><span class="pill {pills[i["state"]]}">'
        f'{e(i["state_label"])}</span><div><b>{e(i["label"])}</b>'
        + (f'<p>{e(i["reason"])}</p>' if i["reason"] else "")
        + (f'<small class="mono">{e(", ".join(i["documents"]))}</small>'
           if i["documents"] and ", ".join(i["documents"]) != i["label"] else "")
        + "</div></div>" for i in rows) + (
        '</div><p class="detail-note"><b>Incomplete</b> is the taxpayer\'s to fix; '
        '<b>needs review</b> is yours to settle. A chase written from the second asks for '
        'something that was already sent.</p>')

    chase = (f'<pre class="letterpre">{e(loop.get("_followup", ""))}</pre>'
             if loop.get("_followup") else
             '<p class="detail-note">Drafted from the gaps in step 3 and nothing else.</p>')

    return f"""
<header class="page-head"><div><h1>Taxpayer correspondence</h1>
<p class="sub">{e(CASE)} · what we asked for, and what arrived</p></div>
<div class="chips"><span class="pill pri-high">Round 1</span>
<span class="pill pri-high">{len(outstanding)} outstanding</span></div></header>

<div class="roundcard live">
  <div class="round-head"><span class="round-n">Round 1</span>
  <span class="round-origin">Opening request</span>
  <span class="pill pri-low">open</span></div>
  {step(1, "The email chain", f"{len(msgs)} message", chain)}
  {step(2, "Documents received", f"{len(docs)} on file", received)}
  {step(3, "Requested versus received", f"{len(outstanding)} outstanding of {len(rows)}", compare)}
  {step(4, "The email to send next", "drafted deterministically", chase)}
</div>

<div class="roundcard soon"><div class="round-head"><span class="round-n">Round 2</span>
<span class="round-origin">Opens from the investigation — when a hypothesis cannot be settled
on the evidence held, requesting information from the taxpayer starts the next round here.
</span><span class="pill status">coming soon</span></div>
<div class="rstep"><p class="detail-note" style="margin:0">The same four steps, against
whatever the next question turns out to be.</p></div></div>
"""


def investigation(inv: dict, z: dict) -> str:
    cats = "".join(
        f'<div class="statechip {"pri-high" if c["blocking"] else "pri-medium"}">'
        f'<b>{c["count"]}</b><span>{e(c["category"])}'
        + (f' · {sar(c["vat_at_stake"])}' if c["vat_at_stake"] else "") + "</span></div>"
        for c in z.get("categories", []))
    mismatches = "".join(
        f'<div class="assessrow {"incomplete" if m["severity"] == "blocking" else "needs-review"}">'
        f'<span class="pill {"pri-high" if m["severity"] == "blocking" else "pri-medium"}">'
        f'{e(m["code"])}</span><div><p>{e(m["detail"])}</p>'
        f'<small class="mono">{e(m["citation"])}</small></div></div>'
        for m in z.get("mismatches", []))

    zatca = f"""
<div class="panel"><div class="panel-head"><div class="ai-h">
<span class="chip-det">Deterministic</span><h2>ZATCA's own invoice records</h2></div>
<span class="muted">{z.get("zatca_count", 0)} invoices · {e((z.get("dataset") or {}).get("filename", ""))}</span>
</div><div class="panel-body">
<div class="statebar"><div class="statechip pri-low"><b>{z.get("matched_count", 0)}</b>
<span>matched</span></div>{cats}</div>
<p class="detail-note" style="margin-top:0">{z.get("listing_count", 0)} rows in
<b>{e(z.get("listing_name", ""))}</b> against {z.get("zatca_count", 0)} in
<b>{e(z.get("zatca_name", ""))}</b>. Amounts are read per rule, never added across them.</p>
<div class="assesslist">{mismatches}</div></div></div>"""

    cards = []
    for h in inv["hypotheses"]:
        c = h.get("regulatory") or {}
        cite = ""
        if c.get("state") == "not-found":
            cite = ('<div class="cite none"><span class="pill status">no provision identified'
                    f'</span><span class="sub">{e(c.get("note", ""))}</span></div>')
        elif c.get("label"):
            warn = (f'<p class="cite-warn">{e(c["note"])}</p>'
                    if c["state"] == "needs-validation" else "")
            stale = ('<span class="pill pri-medium">wording superseded</span>'
                     if c["state"] == "needs-validation" else "")
            cite = f"""<div class="cite {e(c['state'])}">
<div class="cite-head"><span class="pill pri-low">{e(c['label'])}</span>
<b>{e(c['title'])}</b>{stale}</div>
<p class="cite-because"><b>{e(c['label'])}</b> establishes that {e(c['establishes'])};
accordingly, {e(c['consequence'])}.</p>{warn}
<details><summary>read the article</summary>
<pre class="letterpre cite-text">{e(c['text'])}</pre>
<span class="sub">{e(c['chapter'])} · ZATCA English translation, unofficial — the Arabic is
the official version.</span></details></div>"""

        band = h["confidence"]["band"]
        cards.append(f"""
<div class="hyp"><div class="hyp-side"><code>{e(h['hypothesis_id'])}</code>
<span class="pill status">{e(h['reason_code'])}</span></div>
<div class="hyp-main"><div class="hyp-agent">{e(h['agent']).upper()}</div>
{e(h['claim'])}
<div class="hyp-why"><b>Why raised</b> {e(h['why'])}</div>
<div class="verdict verdict-{e(h['status'])}"><b>{e(h['status'].replace('-', ' '))}</b>
{" — " + e(h['explanation']) if h['explanation'] else ""}</div>
{cite}
<div class="row-actions"><button class="btn" disabled>Record your decision</button>
<span class="linklike">✉ Request information from the taxpayer</span></div></div>
<div class="hyp-right"><span class="pill {'pri-low' if h['status'] == 'supported' else 'pri-medium'}">
{e(h['status'])}</span><span class="pill pri-medium">{e(band)} confidence</span>
<b>{sar(h['amount']) if h['amount'] else ''}</b></div></div>""")

    return f"""
<header class="page-head"><div><h1>Investigation</h1>
<p class="sub">{e(CASE)} · what the evidence shows</p></div>
<div class="chips"><span class="pill">{inv['counts']['total']} hypotheses</span>
<span class="pill pri-medium">{inv['counts']['total'] - inv['counts']['decided']} undecided</span>
</div></header>
{zatca}
<div class="panel"><div class="panel-head"><div class="ai-h">
<span class="chip-det">Agents</span><h2>Investigation</h2></div>
<span class="pill status">∑ Adjudicated (no AI)</span></div>
<div class="panel-body">{"".join(cards)}
<p class="detail-note">Every verdict above was settled by the engine against the case's own
figures. The audit conclusion is the auditor's: only what you accept reaches the report.</p>
</div></div>"""


def report(rep: dict, inv: dict, verdict: dict) -> str:
    """The document of record, and the letter that closes the case.

    Both are built from the findings the auditor **accepted** and from nothing else, which is
    why the banner and the letter below it agree. They did not: the letter was drafted from the
    engine's own verdicts, so this page carried "no finding has been confirmed yet" directly
    above a letter to the taxpayer asserting eight of them.

    Every field is editable in the application; here it is a static capture, so the controls are
    shown and do not act, like everything else on this page.
    """
    def field(f: dict) -> str:
        long = len(f["value"]) > 90 or "\n" in f["value"]
        tag = '<span class="rfield-tag">yours</span>' if f.get("edited") else ""
        return (f'<div class="rfield{" wide" if long else ""}'
                f'{" edited" if f.get("edited") else ""}">'
                f'<span class="k">{e(f["label"])}{tag}</span>'
                f'<span class="v{"" if f["held"] else " gap"}">{e(f["value"])}</span>'
                f'<div class="rfield-actions"><span class="linklike">'
                f'{"fill this in" if not f["held"] else "edit"}</span></div></div>')

    sections = "".join(
        f'<section class="rep-section"><h3 class="rep-h">{e(s["title"])}</h3>'
        f'<div class="rfields">' + "".join(field(f) for f in s["fields"]) + "</div></section>"
        for s in rep["sections"])
    undecided = inv["counts"]["total"] - inv["counts"]["decided"]
    accepted = inv["counts"]["accepted"]
    outstanding = rep["completeness"]["outstanding"]

    # Driven by the counts, not written out. It was a fixed "no finding has been confirmed yet",
    # which is the same defect this page exists to show fixed: a banner contradicting the letter
    # printed underneath it.
    if accepted:
        banner = (f'<div class="callout ok"><b>{accepted} finding'
                  f'{"" if accepted == 1 else "s"} confirmed by you</b> · {undecided} '
                  f'hypothes{"is" if undecided == 1 else "es"} still undecided in the '
                  f'Investigation tab. The report and the letter below are built from what you '
                  f'accepted, and from nothing else.</div>')
    else:
        banner = (f'<div class="callout warn"><b>No finding has been confirmed yet.</b> This '
                  f'report — and the letter at the bottom of this page — are built from the '
                  f'findings you accept in the Investigation tab. The engine\'s own verdicts '
                  f'are proposals, not audit conclusions. {undecided} hypotheses are still '
                  f'undecided.</div>')

    letter = ""
    if verdict:
        letter = f"""
<div class="panel ai-panel"><div class="panel-head">
<div class="ai-h"><span class="ai-chip">AI</span><h2>{e(verdict["title"])}</h2></div>
<div class="chips"><span class="pill status">{e(verdict["trigger"])}</span>
<span class="pill">Edit</span><span class="pill">Copy</span></div></div>
<div class="panel-body"><pre class="letterpre">{e(verdict["text"])}</pre>
<p class="detail-note">Written from the findings you accepted, and from nothing else — and
editable in place, because a letter is the one thing here that leaves the building in the
Authority&rsquo;s name.</p></div></div>"""

    return f"""
<header class="page-head"><div><p class="eyebrow">Audit report</p>
<h1>{e(rep.get("taxpayer", CASE))}</h1></div>
<div class="chips"><span class="pill">Download Word</span>
<span class="pill">Open printable / PDF</span></div></header>
{banner}
<div class="panel"><div class="panel-head"><h2>{e(rep["title"])}</h2>
<div class="chips"><span class="pill status">{rep["completeness"]["filled"]} of
{rep["completeness"]["fields"]} answered</span>
<span class="pill pri-medium">{outstanding} still open</span></div></div>
<div class="panel-body">
<p class="detail-note" style="margin-top:0">Every field here can be written in your own words —
the ones marked <b>[for the auditor to complete]</b> are judgements the tool has no business
making, and <b>[not held]</b> is something ZATCA keeps in another system. What you write
replaces what the engine wrote, is marked as yours, keeps the original beside it, and goes into
the Word and printable versions too.</p>
{sections}</div></div>{letter}"""


# -------------------------------------------------- the auditor's instructions for a case

def instructions(d: dict) -> str:
    """One steer, written once, reaching every module of this case.

    It sits under the module tabs rather than on a page because it applies to all three — a
    steer that lived on one of them would be one the auditor believes is in force everywhere
    and is not, which is worse than not having it.

    This one **works**: type in it, save it, clear it. It is UI state rather than engine output,
    so a static file can carry it honestly — nothing is persisted anywhere, and the page says so.
    """
    text = d.get("text", "")
    return f"""
<button class="instrbar{' set' if text else ''}" id="instr-open">
<span class="ai-chip">AI</span><b>Instructions for this case</b>
<span class="instrbar-text"{'' if text else ' hidden'}></span>
<span class="pill pri-low" id="instr-force"{'' if text else ' hidden'}>in force</span>
<span class="instrbar-empty"{' hidden' if text else ''}>Tell the AI what it cannot see in the
documents — context, house style, what not to raise. It applies to every module of this
case.</span>
<span class="instrbar-open">{'Edit' if text else 'Add'}</span></button>

<section class="instr" id="instr">
<div class="instr-head"><span class="ai-chip">AI</span><b>Instructions for this case</b>
<span class="sub">Applied to every module</span>
<button class="asst-x" id="instr-close" aria-label="Close">×</button></div>
<div class="instr-body">
<textarea class="instr-input" id="instr-text" rows="5"
placeholder="What should the AI know about this case that the documents do not say?">{e(text)}</textarea>
<div class="row-actions"><button class="btn" id="instr-save">Save instructions</button>
<button class="linklike danger" id="instr-clear">Clear</button>
<span class="sub" id="instr-count"></span></div>
<p class="detail-note" style="margin-bottom:0">This steers <b>wording and emphasis</b> across
all three modules. It cannot make the AI state a figure, change a verdict, or alter a test —
every number is computed in Python before any sentence is written.</p>
</div></section>"""


# ------------------------------------------------------------------ the case assistant

def assistant(a: dict) -> str:
    """One conversation per case, docked over whichever module you are in.

    It is rendered outside the tab panes for the same reason it sits outside the router in the
    application: a question about a case spans what arrived, what the tests said and what will
    be written, so making the auditor pick a tab before they can ask would be the wrong shape.

    The exchange below is real — the three questions were put to the running assistant when this
    file was generated, and the answers are the ones it gave, deterministically, with no API key
    involved. What it *can* do is the row of buttons: a closed list of the application's own
    checks, not open-ended analysis."""
    msgs = []
    for m in a.get("messages", []):
        tag = ""
        if m["role"] == "assistant" and m.get("action") and m["action"] != "explain":
            tag = f'<span class="pill status">{e(m["action"].replace("_", " "))}</span>'
        did = f'<span class="asst-did">✓ {e(m["did"])}</span>' if m.get("did") else ""
        msgs.append(f'<div class="asst-msg {e(m["role"])}">{tag}'
                    f'<pre>{e(m["content"])}</pre>{did}</div>')
    chips = "".join(f'<button class="qchip" title="{e(x["hint"])}">{e(x["label"])}</button>'
                    for x in a.get("actions", []) if x["key"] != "explain")
    return f"""
<button class="asst-fab" id="asst-open"><span class="ai-chip">AI</span>
Ask about this case</button>
<aside class="asst" id="asst">
<div class="asst-head"><span class="ai-chip">AI</span><b>Case assistant</b>
<span class="sub">{e(CASE)}</span>
<button class="asst-x" id="asst-close" aria-label="Close">×</button></div>
<div class="asst-body">
<p class="detail-note" style="margin-top:0">Everything the assistant can do is on the list
below — it runs the application&rsquo;s own checks rather than analysis of its own, and every
figure in an answer was computed by the engine before the sentence was written. Which is why
it answers with no API key at all.</p>
{"".join(msgs)}</div>
<div class="asst-foot"><div class="asst-quick">{chips}</div>
<div class="asst-input"><input placeholder="Ask about this case…" disabled>
<button class="btn" disabled>Ask</button></div></div>
</aside>"""


# ------------------------------------------------------------------ the page

def build() -> str:
    # The walkthrough sets up the state it is meant to show, rather than depending on whoever
    # last clicked around the running app. Accepting two hypotheses and writing one report field
    # is what makes the report, the traceability panel and the verdict letter say anything at
    # all — and it keeps the three of them agreeing, which is the property worth demonstrating.
    try:
        state = _get(f"/cases/{CASE}/investigation")
        # Idempotent: regenerating twice must not accept two more each time. It did, and the
        # banner went from "2 findings confirmed by you" to 4 with no case data changing.
        supported = ([] if state["counts"]["accepted"] else
                     [h for h in state["hypotheses"]
                      if h["status"] == "supported" and h.get("outcome_code")][:2])
        for h in supported:
            _post(f"/cases/{CASE}/hypotheses/{h['hypothesis_id']}/decision",
                  {"decision": "accepted", "comment": "Accepted on review."})
        rulings = next(f for sec in _get(f"/cases/{CASE}/audit-report")["sections"]
                       for f in sec["fields"] if f["label"] == "Rulings")
        _put(f"/cases/{CASE}/audit-report/fields", {
            "key": rulings["key"], "original": rulings["value"],
            "value": "No ruling has been issued. The taxpayer accepted the adjustment at the "
                     "closing meeting of 12 August."})
    except Exception:                                    # noqa: BLE001
        pass

    loop = _get(f"/cases/{CASE}/requests")
    threads = _get(f"/cases/{CASE}/threads")
    inv = _get(f"/cases/{CASE}/investigation")
    z = _get(f"/cases/{CASE}/zatca")
    rep = _get(f"/cases/{CASE}/audit-report")
    mails = _get(f"/cases/{CASE}/emails").get("emails") or []
    verdict = next((m for m in mails if m["kind"] == "verdict"), {})
    _put(f"/cases/{CASE}/instructions", {
        "text": "The group restructured on 1 February; the second half of the period trades "
                "under a different entity. Say where that could explain a difference rather "
                "than treating it as unexplained.\n\n"
                "Keep letters to one page, and lead with what we need from them.",
        "enabled": True})
    instr = _get(f"/cases/{CASE}/instructions")
    cov = _get("/regulatory/coverage")
    cases = _get("/cases")
    try:
        loop["_followup"] = _get(f"/cases/{CASE}/followup").get("text", "")
    except Exception:                                    # noqa: BLE001
        loop["_followup"] = ""

    # The assistant is asked its questions here rather than being scripted, for the same reason
    # the rest of the page is generated: an answer written by hand would drift the moment the
    # engine behind it changed, and the point of the panel is that it is not being written by
    # hand. Cleared first so regenerating twice does not stack the same exchange.
    _delete(f"/cases/{CASE}/assistant")
    asst: dict = {}
    for q in ("where are we on this case",
              "what is still missing?",
              "compare with ZATCA's records"):
        try:
            asst = _post(f"/cases/{CASE}/assistant", {"question": q})
        except Exception:                                # noqa: BLE001
            pass
    if not asst:
        asst = _get(f"/cases/{CASE}/assistant")

    theme = THEME.read_text(encoding="utf-8") if THEME.exists() else ""

    # The sidebar is what is global; the tabs are what is inside a case. Mirrored here because
    # a walkthrough that put all four side by side would be showing a different product: an
    # auditor lands on the queue and opens a case, and the three modules are what is *in* the
    # case rather than peers of the list that contains it.
    modules = {
        "correspondence": ("Taxpayer Correspondence", "What we asked, what arrived",
                           correspondence(loop, threads)),
        "investigation": ("Investigation", "What the evidence shows", investigation(inv, z)),
        "report": ("Audit Report", "What you concluded", report(rep, inv, verdict)),
    }
    nav = "".join(
        f'<button class="ctab" data-tab="{k}"><b>{e(t)}</b><span>{e(s)}</span></button>'
        for k, (t, s, _) in modules.items())
    panes = "".join(f'<div class="pane" id="pane-{k}">{body}</div>'
                    for k, (_, _, body) in modules.items())
    taxpayer = next((c["taxpayer"] for c in cases if c["case_id"] == CASE), CASE)
    case_json = json.dumps(CASE)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-AUDIT — walkthrough</title>
<style>{theme}
body{{margin:0;padding:0 0 60px}}
.wrap{{max-width:1180px;margin:0 auto;padding:26px 30px 60px}}
.navlink{{cursor:pointer}}
.side{{position:sticky;top:0;height:100vh}}
.demo-note{{background:var(--surface-2);border:1px solid var(--line);border-radius:11px;
  padding:13px 16px;margin-bottom:18px;font-size:13px;line-height:1.6}}
.ctabs{{display:flex;gap:0;border-bottom:1px solid var(--line);margin-bottom:20px}}
.ctab{{background:none;border:none;border-bottom:2px solid transparent;padding:11px 18px 13px;
  font:inherit;text-align:left;cursor:pointer;color:var(--muted);display:flex;
  flex-direction:column;gap:2px}}
.ctab b{{font-size:14px;color:var(--muted)}}
.ctab span{{font-size:11.5px}}
.ctab.on{{border-bottom-color:var(--brand)}}
.ctab.on b{{color:var(--brand)}}
.pane{{display:none}} .pane.on{{display:block}}
.hyp{{display:flex;gap:14px;border:1px solid var(--line);border-radius:11px;padding:13px;
  margin-bottom:11px;background:var(--surface)}}
.hyp-side{{flex:none;width:66px;display:flex;flex-direction:column;gap:5px;align-items:flex-start}}
.hyp-side code{{font-size:12px;font-weight:700;color:var(--brand)}}
.hyp-main{{flex:1;font-size:13.5px;line-height:1.55}}
.hyp-agent{{font-size:11px;letter-spacing:.05em;color:var(--muted);margin-bottom:5px}}
.hyp-why{{font-size:12.5px;color:var(--muted);margin:6px 0}}
.hyp-right{{flex:none;width:160px;display:flex;flex-direction:column;gap:6px;align-items:flex-end;
  text-align:right}}
.verdict{{font-size:12.5px;margin:6px 0;color:var(--high)}}
.verdict-supported{{color:var(--low)}}
.rep-h{{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  margin:16px 0 8px}}
.kv{{display:grid;grid-template-columns:1fr 1fr;gap:9px}}
.kv .k{{display:block;font-size:11px;letter-spacing:.04em;text-transform:uppercase;
  color:var(--muted)}}
.kv .v{{font-size:13px}} .kv .v.gap{{color:var(--med);font-weight:600}}
.kv>div{{border:1px solid var(--line);border-radius:8px;padding:8px 11px;background:var(--surface)}}
details summary{{cursor:pointer;font-size:12px;color:var(--brand);font-weight:600;margin-top:4px}}
.tabhint{{font-size:12px;color:var(--muted);margin:0 0 6px}}
.caserow.on{{background:var(--surface-2)}}
.caserow.on td{{font-weight:600}}
/* The row that opens. Only the seeded case carries real output, so it is the only one that
   goes anywhere — and it says so rather than looking broken when the others do not. */
tr[data-open]{{cursor:pointer}}
tr[data-open]:hover{{background:color-mix(in srgb,var(--brand) 8%,var(--surface))}}
details[open] summary{{margin-bottom:6px}}
/* Two views, not four tabs: the queue, and one case opened out of it. */
.view{{display:none}} .view.on{{display:block}}
.casebar{{display:flex;align-items:center;gap:14px;margin-bottom:6px}}
.backlink{{border:none;background:none;font:inherit;font-size:13px;font-weight:600;
  color:var(--brand);cursor:pointer;padding:0}}
.backlink:hover{{text-decoration:underline}}
/* Says why a control did nothing, rather than leaving the click unanswered — an inert button
   with no feedback is the thing that reads as broken. */
#toast{{position:fixed;left:50%;bottom:26px;transform:translate(-50%,14px);z-index:60;
  max-width:min(640px,90vw);background:var(--ink);color:var(--surface);font-size:13px;
  line-height:1.5;padding:11px 16px;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.28);
  opacity:0;pointer-events:none;transition:opacity .16s,transform .16s}}
#toast.on{{opacity:.96;transform:translate(-50%,0)}}
/* The assistant is conditionally rendered in React; here it is toggled, and the page is
   narrowed while it is docked so it covers nothing. */
.asst{{display:none}}
body.asst-on .asst{{display:flex}}
body.asst-on .asst-fab{{display:none}}
.app.asst-on,body.asst-on{{padding-right:430px}}
@media (max-width:1000px){{body.asst-on{{padding-right:0}}}}
</style></head><body><div class="app">
<aside class="side">
<div class="brand"><span class="mark">ZC</span>
<span><b>ZATCA</b><small>VAT Audit Agent</small></span></div>
<nav>
<a class="navlink active" data-view="cases"><span class="ic">&#9635;</span>Cases</a>
<div class="navgroup">Coming next</div>
<span class="navlink disabled"><span class="ic">&#9702;</span>Legal retrieval</span>
</nav>
<div class="side-foot">ZATCA VAT Audit Agent</div>
</aside>
<main class="main"><div class="wrap">

<div class="demo-note"><b>A static walkthrough, not the application.</b> Every figure, finding,
citation and gap on this page is the real output of the engine for the seeded demo case
{e(CASE)}, captured when this file was generated. <b>What works here:</b> opening the case,
moving between its modules, writing the case instructions, and editing the report fields and
the verdict letter — those are the auditor's own words, so a file with no backend can do the
whole interaction. <b>What does not:</b> uploading, re-running the investigation and asking the
assistant, which all need the engine; they say so when you click them rather than going quiet.
Nothing you change here is saved anywhere. The regulations corpus behind the citations holds
{cov.get('article_count', 0)} articles, {len(cov.get('amended_since_english_edition', []))} of
which have been amended since the English edition they are shown in.</div>

<div class="view on" id="view-cases">{case_list(cases, CASE)}</div>

<div class="view" id="view-case">
<div class="casebar"><button class="backlink" id="back">&#8592; All cases</button>
<span class="mono muted">{e(CASE)}</span>
<b>{e(taxpayer)}</b></div>
<p class="tabhint">The three modules of this case. Only <b>Cases</b> is application-wide
&mdash; everything else needs to know which case it is about, so it lives here. The
<b>case assistant</b> and the <b>case instructions</b> are on all three.</p>
<div class="ctabs">{nav}</div>
{instructions(instr)}
{panes}
</div>

</div></div>{assistant(asst)}<script>
const tabs = document.querySelectorAll('.ctab');
function show(k) {{
  tabs.forEach(t => t.classList.toggle('on', t.dataset.tab === k));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + k));
}}
tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));

function view(name) {{
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + name));
  // The assistant is a *case* assistant, so it is docked inside a case and nowhere else. Left
  // over the queue it squeezed the table for a panel that had nothing to say about it.
  dock(name === 'case');
  document.querySelectorAll('.navlink[data-view]').forEach(
    n => n.classList.toggle('active', n.dataset.view === (name === 'case' ? 'cases' : name)));
  window.scrollTo(0, 0);
}}
document.querySelectorAll('tr[data-open]').forEach(
  r => r.addEventListener('click', () => {{ view('case'); show('correspondence'); }}));
document.getElementById('back').addEventListener('click', () => view('cases'));
document.querySelectorAll('.navlink[data-view="cases"]').forEach(
  n => n.addEventListener('click', () => view('cases')));

/* ---------------------------------------------------------- the instructions box
   Real: type in it, save it, clear it. It is UI state rather than engine output, so a file
   with no backend can carry it honestly. Nothing is persisted — reload and it is back. */
const instr = document.getElementById('instr');
const instrBar = document.getElementById('instr-open');
const instrText = document.getElementById('instr-text');
const instrCount = document.getElementById('instr-count');
const showInstr = on => {{ instr.style.display = on ? 'block' : 'none';
                           instrBar.style.display = on ? 'none' : 'flex'; }};
function paintInstr() {{
  const v = instrText.value.trim();
  instrBar.classList.toggle('set', !!v);
  instrBar.querySelector('.instrbar-text').textContent = v;
  instrBar.querySelector('.instrbar-text').hidden = !v;
  document.getElementById('instr-force').hidden = !v;
  instrBar.querySelector('.instrbar-empty').hidden = !!v;
  instrBar.querySelector('.instrbar-open').textContent = v ? 'Edit' : 'Add';
  instrCount.textContent = instrText.value.length.toLocaleString() + ' / 4,000';
}}
instrText.addEventListener('input', () => instrCount.textContent =
  instrText.value.length.toLocaleString() + ' / 4,000');
instrBar.addEventListener('click', () => showInstr(true));
document.getElementById('instr-close').addEventListener('click', () => showInstr(false));
document.getElementById('instr-save').addEventListener('click', () => {{
  paintInstr(); showInstr(false); toast('Instructions saved on this case.');
}});
document.getElementById('instr-clear').addEventListener('click', () => {{
  instrText.value = ''; paintInstr(); showInstr(false); toast('Instructions cleared.');
}});
showInstr(false);
paintInstr();

/* ------------------------------------------------------------ editing, for real
   The report's fields and the outbound letter are edited in place here exactly as in the
   application. They are the auditor's own words — no engine involved — so this file can do
   the whole interaction rather than showing a picture of it. */
function editField(field) {{
  if (field.querySelector('textarea')) return;
  const v = field.querySelector('.v');
  const before = v.textContent;
  const long = before.length > 90 || before.includes(String.fromCharCode(10));
  const gap = v.classList.contains('gap');
  const ta = document.createElement('textarea');
  ta.className = 'rfield-input';
  ta.rows = long ? 8 : 2;
  ta.value = gap ? '' : before;
  ta.placeholder = 'Write this in your own words…';
  const bar = document.createElement('div');
  bar.className = 'rfield-actions';
  const save = document.createElement('button');
  save.className = 'btn small'; save.textContent = 'Save';
  const cancel = document.createElement('button');
  cancel.className = 'linklike'; cancel.textContent = 'cancel';
  bar.append(save, cancel);
  const actions = field.querySelector('.rfield-actions');
  v.hidden = true; actions.hidden = true;
  field.classList.add('editing');
  field.append(ta, bar);
  ta.focus();
  const done = () => {{ ta.remove(); bar.remove(); v.hidden = false;
                        actions.hidden = false; field.classList.remove('editing'); }};
  cancel.addEventListener('click', done);
  save.addEventListener('click', () => {{
    const next = ta.value.trim();
    if (next) {{
      v.textContent = next; v.classList.remove('gap');
      field.classList.add('edited');
      if (!field.querySelector('.rfield-tag')) {{
        const tag = document.createElement('span');
        tag.className = 'rfield-tag'; tag.textContent = 'yours';
        field.querySelector('.k').append(tag);
      }}
      actions.querySelector('.linklike').textContent = 'edit';
    }}
    done();
    toast('Field saved. In the application this also goes into the Word and printable versions.');
  }});
}}
document.querySelectorAll('.rfield').forEach(f => {{
  const link = f.querySelector('.rfield-actions .linklike');
  if (link) link.addEventListener('click', () => editField(f));
}});

const letter = document.querySelector('.ai-panel pre.letterpre');
const letterPanel = letter && letter.closest('.panel');
if (letterPanel) {{
  const chips = letterPanel.querySelectorAll('.panel-head .pill');
  const editBtn = [...chips].find(c => c.textContent.trim() === 'Edit');
  const copyBtn = [...chips].find(c => c.textContent.trim() === 'Copy');
  if (copyBtn) copyBtn.addEventListener('click', () => {{
    navigator.clipboard && navigator.clipboard.writeText(letter.textContent);
    toast('Letter copied.');
  }});
  if (editBtn) editBtn.addEventListener('click', () => {{
    if (letterPanel.querySelector('.letter-edit')) return;
    const ta = document.createElement('textarea');
    ta.className = 'letter-edit';
    ta.rows = Math.min(30, letter.textContent.split(String.fromCharCode(10)).length + 3);
    ta.value = letter.textContent;
    const bar = document.createElement('div');
    bar.className = 'row-actions';
    const save = document.createElement('button');
    save.className = 'btn'; save.textContent = 'Save the letter';
    const cancel = document.createElement('button');
    cancel.className = 'linklike'; cancel.textContent = 'cancel';
    bar.append(save, cancel);
    letter.hidden = true;
    letter.after(ta, bar);
    ta.focus();
    const done = () => {{ ta.remove(); bar.remove(); letter.hidden = false; }};
    cancel.addEventListener('click', done);
    save.addEventListener('click', () => {{
      letter.textContent = ta.value;
      done();
      toast('Letter saved. The verified badge is replaced by “your wording” — the checker never saw these words.');
    }});
  }});
}}

/* ------------------------------------------------- what a file with no backend cannot do
   Uploading, re-running the investigation and asking the assistant all need the engine. They
   say so when clicked rather than doing nothing, which is the thing that reads as broken. */
let toastTimer;
function toast(msg) {{
  let el = document.getElementById('toast');
  if (!el) {{ el = document.createElement('div'); el.id = 'toast'; document.body.append(el); }}
  el.textContent = msg;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 3200);
}}
const NEEDS_ENGINE = 'That one needs the engine, so it is inert in this static walkthrough — '
  + 'it works in the application.';
document.querySelectorAll('.dropzone, .qchip, .asst-input, .btn[disabled], .instr + * button[disabled]')
  .forEach(el => el.addEventListener('click', () => toast(NEEDS_ENGINE), true));
document.querySelectorAll('tr.caserow:not([data-open])').forEach(
  r => {{ r.style.cursor = 'pointer';
          r.addEventListener('click', () => toast(
            'Only ' + {case_json} + ' was captured into this file — the other rows are the real '
            + 'queue, with no output behind them here.')); }});

const dock = on => document.body.classList.toggle('asst-on', on);
document.getElementById('asst-open').addEventListener('click', () => dock(true));
document.getElementById('asst-close').addEventListener('click', () => dock(false));
view('cases');
</script></body></html>"""


if __name__ == "__main__":                               # pragma: no cover
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
