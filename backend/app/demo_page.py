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

SPARK = ('<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"'
         ' stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
         '<path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/>'
         '<path d="M19 3l.75 2.25L22 6l-2.25.75L19 9l-.75-2.25L16 6l2.25-.75z"/></svg>')


FONTS = ROOT / "frontend" / "public" / "fonts"


def inline_fonts(css: str) -> str:
    """Carry the typefaces inside the file.

    `theme.css` loads them from `/fonts/...`, which is right for the application and wrong for
    a single HTML file somebody opens from their downloads folder: the requests 404 and every
    screen silently falls back to a system face. Since the whole point of this file is to show
    what the design looks like, the fonts are embedded rather than referenced.
    """
    import base64
    import re

    def swap(m: "re.Match[str]") -> str:
        name = m.group(1)
        f = FONTS / name
        if not f.exists():
            return m.group(0)
        b64 = base64.b64encode(f.read_bytes()).decode()
        return f"url('data:font/woff2;base64,{b64}') format('woff2')"

    return re.sub(r"url\('/fonts/([^']+)'\) format\('woff2'\)", swap, css)


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

    One bordered card of rows rather than a table. The priority bar carries no number — the
    score is a composite nobody can check at a glance, and a bar you can rank by is what the
    column is actually for.
    """
    rows = []
    for c in cases:
        p = c.get("priority") or {}
        band = (p.get("band") or "low").lower()
        opens = ' data-open="1"' if c["case_id"] == open_case else ""
        days = p.get("deadline_days")
        when = "" if days is None else ("past due" if days < 0 else f"{days}d")
        pill = "pill pri-low" if c["status"] == "reconciled" else "pill status"
        rows.append(
            f'<div class="caserow"{opens}>'
            f'<span class="pbar pri-{e(band)}"></span>'
            f'<div class="caserow-who"><div class="caserow-name">{e(c["taxpayer"])}</div>'
            f'<div class="caserow-sub">{e(c["sector"])} · '
            f'<span class="mono">{e(c["vat_no"])}</span></div></div>'
            f'<div class="caserow-id mono">{e(c["case_id"])}</div>'
            f'<div class="caserow-reason">{e(c["reason"])}</div>'
            f'<div class="caserow-when mono">{e(when)}</div>'
            f'<div class="caserow-state"><span class="{pill}">{e(c["status"])}</span></div>'
            "</div>")

    return f"""
<header class="page-head"><div><h1>Cases</h1>
<p class="sub">{len(cases)} open, ranked by what is worth looking at first</p></div>
<div><button class="btn-ghost" id="new-case">New case</button></div></header>

<div class="caselist">{''.join(rows)}</div>
<p class="detail-note">Every case covers 2025-01-01 to 2025-03-31. Only
<b>{e(open_case)}</b> carries engine output in this walkthrough — that is the row that opens.
</p>"""


# ------------------------------------------------------------------ the three tabs

def correspondence(loop: dict, threads: dict) -> str:
    a = loop.get("assessment") or {"items": [], "summary": {}}
    t = (threads.get("threads") or [{}])[0]
    msgs = t.get("messages") or []
    docs = t.get("documents") or []
    rows = a["items"]
    outstanding = [i for i in rows if i["state"] != "received"]

    def step(n, title, note, body):
        return (f'<section class="rstep on"><div class="rstep-head">'
                f'<span class="rstep-n">{n}</span><b>{e(title)}</b>'
                f'<span class="sub">{e(note)}</span><span class="rstep-mark">&#9662;</span></div>'
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
        + ('<div class="review"><button class="btn small ghost">Approve</button>'
           '<button class="btn small warn">Challenge</button></div>')
        + "</div></div>" for i in rows) + (
        '</div><p class="detail-note"><b>Incomplete</b> is the taxpayer\'s to fix; '
        '<b>needs review</b> is yours to settle. A chase written from the second asks for '
        'something that was already sent.</p>')

    chase = (f'<pre class="letterpre">{e(loop.get("_followup", ""))}</pre>'
             if loop.get("_followup") else
             '<p class="detail-note">Drafted from the gaps in step 3 and nothing else.</p>')

    return f"""
<div class="modulehead"><h2 class="display">Round 1 &mdash; opening request</h2>
<span class="pill pri-high">{len(outstanding)} outstanding</span></div>

<div class="roundcard live">
  <div class="round-head"><span class="round-n">Round 1</span>
  <span class="round-origin">Opening request</span>
  <span class="pill pri-low">open</span></div>
  {step(1, "The email chain", f"{len(msgs)} message", chain)}
  {step(2, "Documents received", f"{len(docs)} on file", received)}
  {step(3, "Documents received analysis", f"{len(outstanding)} outstanding of {len(rows)}", compare)}
  {step(4, "The email to send next", "drafted deterministically", chase)}
</div>

<div class="roundcard soon"><div class="round-head"><span class="round-n">Round 2</span>
<span class="round-origin">Opens from the investigation — when a hypothesis cannot be settled
on the evidence held, requesting information from the taxpayer starts the next round here.
</span><span class="pill status">coming soon</span></div>
<div class="rstep"><p class="detail-note" style="margin:0">The same four steps, against
whatever the next question turns out to be.</p></div></div>
"""


def investigation(inv: dict, z: dict, summary: dict, asmt: dict) -> str:
    """The module in the order the work happens.

    Optional ZATCA data, then what the investigation found, then the evidence behind it, then
    the auditor's own assessment. The evidence layer is everything that used to be at the top:
    it is not less important, it is what the summary is answerable to, and it is one click away
    rather than the first thing between the auditor and the answer.
    """
    ds = z.get("dataset") or {}
    zhead = (f'<b>{e(ds["filename"])}</b> <span class="sub">{z.get("zatca_count", 0)} invoices'
             f' · {z.get("matched_count", 0)} matched against the listing</span>'
             if ds else '<span class="sub zsrc-none">None loaded — the investigation runs on '
                        "the taxpayer's documents alone</span>")
    zmeta = (f'<div class="zsrc-meta"><span><span class="k">File</span>{e(ds["filename"])}</span>'
             f'<span><span class="k">Invoices</span>{ds.get("row_count", 0)}</span>'
             f'<span><span class="k">Columns</span>{len(ds.get("columns", []))}</span>'
             f'<span><span class="k">Loaded</span>{e(ds.get("uploaded_at", "")[:10])}</span></div>'
             if ds else "")
    zsrc = f"""
<section class="zsrc" id="zsrc"><button class="zsrc-head" id="zsrc-head">
<b>ZATCA invoice records</b><span class="zsrc-opt">Optional</span>
<span class="zsrc-file">{zhead}</span><span class="zsrc-mark" id="zsrc-mark">&#9656;</span>
</button><div class="zsrc-body" id="zsrc-body" hidden>
<div class="dropzone"><b>Drop a file here to replace it</b>
<span class="sub">.xlsx, .xlsm, .csv &mdash; one row per invoice, as ZATCA holds it</span></div>
{zmeta}
<p class="detail-note" style="margin-bottom:0">The taxpayer&rsquo;s own documents come from
<b>Taxpayer Correspondence</b> and are already in use here. This slot is for ZATCA&rsquo;s
internal invoice extract, which the listing is matched against.</p></div></section>"""

    # ---------------------------------------------------------------- the summary cards
    KIND = {"observation": ("Observed", "obs"),
            "unresolved": ("Not settled", "open"),
            "data-quality": ("Records defect", "rec")}
    cards = []
    for c in summary["cards"]:
        label, cls = KIND[c["kind"]]
        alt = ""
        if c["alternatives"]:
            items = "".join(f"<li>{e(a)}</li>" for a in c["alternatives"])
            alt = (f'<details class="sumalt"><summary>The same evidence also reads '
                   f'{len(c["alternatives"])} other way'
                   f'{"" if len(c["alternatives"]) == 1 else "s"}</summary>'
                   f"<ul>{items}</ul><p class=\"sub\">One matter, one amount. These are readings "
                   "of the same evidence, not separate money.</p></details>")
        read = ""
        if c["reading"]:
            k = "Why it matters" if c["kind"] == "data-quality" else "What it may mean"
            read = f'<p class="sumread"><span class="k">{k}</span>{e(c["reading"])}</p>'
        ruled = (f'<span class="pill pri-low">{e(c["decision"].replace("-", " "))} by you</span>'
                 if c["decision"] else '<span class="sub">requires your validation</span>')
        band = (f'<span class="pill pri-medium">{e(c["confidence"])} confidence</span>'
                if c["confidence"] else "")
        ids = (f'<span class="sub mono">{e(" · ".join(c["hypothesis_ids"]))}</span>'
               if c["hypothesis_ids"] else "")
        cards.append(f"""
<article class="sumcard {cls}"><header><span class="sumkind {cls}">{label}</span>
<h3>{e(c["title"])}</h3>
{f'<b class="sumamt">{sar(c["amount"])}</b>' if c["amount"] else ""}</header>
<p class="sumobs">{e(c["observed"])}</p>{read}{alt}
<footer>{band}{ruled}{ids}</footer></article>""")

    t = summary["totals"]
    bar = [f"<span><b>{t['observations']}</b> observed</span>"]
    if t["unresolved"]:
        bar.append(f"<span><b>{t['unresolved']}</b> not settled</span>")
    if t["record_defects"]:
        bar.append(f"<span><b>{t['record_defects']}</b> records defect"
                   f"{'' if t['record_defects'] == 1 else 's'}</span>")
    if t["not_supported"]:
        bar.append(f'<span class="muted"><b>{t["not_supported"]}</b> tested, not supported</span>')
    if t["at_stake"]:
        bar.append(f'<span class="sumbar-amt"><b>{sar(t["at_stake"])}</b> at stake</span>')

    summary_panel = f"""
<div class="panel"><div class="panel-head"><h2>Investigation summary</h2>
<span class="pill status">&#8721; Adjudicated (no AI)</span></div>
<div class="panel-body"><div class="sumbar">{"".join(bar)}</div>
<div class="sumcards">{"".join(cards)}</div>
<p class="detail-note">Each amount is counted once against the evidence it rests on, so nothing
here is the same money twice &mdash; but this is <b>not a proposed adjustment</b>. Everything
above is an observation for you to validate; what you conclude is yours to write at the foot of
this page, and only what you accept reaches the report.</p></div></div>"""

    # ------------------------------------------------------ the evidence, one click behind
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
    # With no dataset there is one side and no comparison, so the panel is not rendered at all
    # rather than reporting a reconciliation that was never run.
    zatca = f"""
<div class="panel"><div class="panel-head"><div class="ai-h">
<span class="chip-det">Deterministic</span><h2>ZATCA's own invoice records</h2></div>
<span class="muted">{z.get("zatca_count", 0)} invoices · {e(ds.get("filename", ""))}</span>
</div><div class="panel-body">
<div class="statebar"><div class="statechip pri-low"><b>{z.get("matched_count", 0)}</b>
<span>matched</span></div>{cats}</div>
<p class="detail-note" style="margin-top:0">{z.get("listing_count", 0)} rows in
<b>{e(z.get("listing_name", ""))}</b> against {z.get("zatca_count", 0)} in
<b>{e(z.get("zatca_name", ""))}</b>. Amounts are read per rule, never added across them.</p>
<div class="assesslist">{mismatches}</div></div></div>""" if ds and z.get("comparable") else ""

    hyps = []
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
        hyps.append(f"""
<div class="hyp"><div class="hyp-side"><code>{e(h['hypothesis_id'])}</code>
<span class="pill status">{e(h['reason_code'])}</span></div>
<div class="hyp-main"><div class="hyp-agent">{e(h['agent']).upper()}</div>
{e(h['claim'])}
<div class="hyp-why"><b>Why raised</b> {e(h['why'])}</div>
<div class="verdict verdict-{e(h['status'])}"><b>{e(h['status'].replace('-', ' '))}</b>
{" — " + e(h['explanation']) if h['explanation'] else ""}</div>
{cite}</div>
<div class="hyp-right"><span class="pill {'pri-low' if h['status'] == 'supported' else 'pri-medium'}">
{e(h['status'])}</span><span class="pill pri-medium">{e(band)} confidence</span>
<b>{sar(h['amount']) if h['amount'] else ''}</b></div></div>""")

    # Collapsed by default here as in the application — it is UI state, so a file with no
    # backend can carry it honestly.
    detail = f"""
<div class="collapse" id="inv-detail"><button class="collapse-head" id="inv-detail-head">
<span class="collapse-mark" id="inv-detail-mark">&#9656;</span>
<b>Detailed investigation &amp; evidence</b>
<span class="sub">every hypothesis, why it was raised, the figures behind it, the law it rests
on, and the source records</span><span class="collapse-action">Open</span></button>
<div class="collapse-body" id="inv-detail-body" hidden>{zatca}
<div class="panel"><div class="panel-head"><div class="ai-h">
<span class="chip-det">Agents</span><h2>Investigation</h2></div>
<span class="pill status">&#8721; Adjudicated (no AI)</span></div>
<div class="panel-body">{"".join(hyps)}
<p class="detail-note">Every verdict above was settled by the engine against the case's own
figures. The audit conclusion is the auditor's: only what you accept reaches the report.</p>
</div></div></div></div>"""

    # ---------------------------------------------------------------- the auditor's own
    matters = "".join(
        f"""<div class="matter{" ruled" if c["decision"] else ""}">
<div class="matter-what"><b>{e(c["title"])}</b>
{f'<span class="matter-amt">{sar(c["amount"])}</span>' if c["amount"] else ""}</div>
<div class="matter-act">"""
        + (f'<span class="pill pri-low">{e(c["decision"].replace("-", " "))}</span>'
           if c["decision"]
           else '<button class="btn-ghost">Confirm</button>'
                '<button class="btn-ghost">Dismiss</button>'
                '<button class="btn-ghost">Ask the taxpayer</button>')
        + "</div></div>"
        for c in summary["cards"] if c["hypothesis_ids"])
    confirmed = len([c for c in summary["cards"] if c["decision"] == "accepted"])
    steers = "".join(f'<button class="btn-ghost">{e(s)}</button>' for s in (
        "Treat the largest difference as a timing difference and say why.",
        "Rewrite this using only what I have confirmed.",
        "Drop the matters where the evidence is insufficient.",
        "Say it in plainer language for a taxpayer with no adviser."))

    assess = f"""
<div class="panel assess"><div class="panel-head"><h2>Your assessment</h2>
<span class="pill {"pri-low" if confirmed else "status"}">
{f"{confirmed} confirmed — carried into the report" if confirmed else "nothing confirmed yet"}
</span></div><div class="panel-body">
<div class="matters"><div class="matters-head">Which of these you are taking forward. Only what
you confirm reaches the audit report and the letter to the taxpayer.</div>{matters}</div>
<div class="assess-doc"><div class="assess-doc-head"><b>The assessment</b>
<span class="sub">drafted from the investigation &mdash; yours to edit</span></div>
<pre class="assess-text" id="assess-text">{e(asmt.get("text", ""))}</pre>
<div class="row-actions"><button class="btn-ghost" id="assess-edit">Edit the assessment</button>
</div></div>
<div class="assess-ai"><span class="ai-chip">{SPARK}</span>
<b>Or tell the assistant what to change</b>
<div class="assess-steers">{steers}</div>
<p class="detail-note" style="margin-bottom:0">It rewrites the assessment against the same
figures the engine computed, checked the same way &mdash; an instruction can change how
something is put, and cannot introduce a number. The assessment stays yours.</p></div>
</div></div>"""

    return f"""{zsrc}
{summary_panel}
{detail}
{assess}"""


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
<div class="ai-h"><span class="ai-chip"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M19 3l.75 2.25L22 6l-2.25.75L19 9l-.75-2.25L16 6l2.25-.75z"/></svg></span><h2>{e(verdict["title"])}</h2></div>
<div class="chips"><span class="pill status">{e(verdict["trigger"])}</span>
<span class="pill">Edit</span><span class="pill">Copy</span></div></div>
<div class="panel-body"><pre class="letterpre">{e(verdict["text"])}</pre>
<p class="detail-note">Written from the findings you accepted, and from nothing else — and
editable in place, because a letter is the one thing here that leaves the building in the
Authority&rsquo;s name.</p></div></div>"""

    return f"""
<div class="modulehead"><h2 class="display">Audit report</h2>
<span class="sub"><span class="num">{rep["completeness"]["filled"]}</span> of
<span class="num">{rep["completeness"]["fields"]}</span> fields answered</span>
<div class="modulehead-act"><span class="btn-ghost">Download Word</span>
<span class="btn-ghost">Printable</span></div></div>
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
<span class="ai-chip"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M19 3l.75 2.25L22 6l-2.25.75L19 9l-.75-2.25L16 6l2.25-.75z"/></svg></span><b>Instructions for this case</b>
<span class="instrbar-text"{'' if text else ' hidden'}></span>
<span class="pill pri-low" id="instr-force"{'' if text else ' hidden'}>in force</span>
<span class="instrbar-empty"{' hidden' if text else ''}>Tell the AI what it cannot see in the
documents — context, house style, what not to raise. It applies to every module of this
case.</span>
<span class="instrbar-open">{'Edit' if text else 'Add'}</span></button>

<section class="instr" id="instr">
<div class="instr-head"><span class="ai-chip"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M19 3l.75 2.25L22 6l-2.25.75L19 9l-.75-2.25L16 6l2.25-.75z"/></svg></span><b>Instructions for this case</b>
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

def assistant(a: dict, answers: dict) -> str:
    """One conversation per case, docked over whichever module you are in.

    It is rendered outside the tab panes for the same reason it sits outside the router in the
    application: a question about a case spans what arrived, what the tests said and what will
    be written, so making the auditor pick a tab before they can ask would be the wrong shape.

    **And it answers here.** Every reply below was put to the running assistant when this file
    was generated and captured verbatim — deterministic engine output, no API key involved — so
    the walkthrough can route a question to the same closed set of actions the application
    routes it to, and give the same answer. It is not a model running in the page; it is the
    engine's own answers, indexed by the action that produced them.
    """
    msgs = []
    for m in a.get("messages", []):
        tag = ""
        if m["role"] == "assistant" and m.get("action") and m["action"] != "explain":
            tag = f'<span class="pill status">{e(m["action"].replace("_", " "))}</span>'
        did = f'<span class="asst-did">&#10003; {e(m["did"])}</span>' if m.get("did") else ""
        msgs.append(f'<div class="asst-msg {e(m["role"])}">{tag}'
                    f'<pre>{e(m["content"])}</pre>{did}</div>')
    acts = [x for x in a.get("actions", []) if x["key"] != "explain"]
    chips = "".join(
        f'<button class="qchip" data-act="{e(x["key"])}" title="{e(x["hint"])}">'
        f'{e(x["label"])}</button>' for x in acts)
    return f"""
<button class="asst-fab" id="asst-open"><span class="asst-dot"></span>Ask about this case</button>
<aside class="slideover asst" id="asst">
<div class="slideover-head"><span class="ic">{SPARK}</span><b>Case assistant</b>
<span class="mono">{e(CASE)}</span>
<button class="slideover-x" id="asst-close" aria-label="Close">&times;</button></div>
<div class="asst-body" id="asst-body">{"".join(msgs)}</div>
<div class="slideover-foot"><div class="asst-quick">{chips}</div>
<div class="asst-input"><input id="asst-q" placeholder="Ask about this case&hellip;">
<button class="btn" id="asst-send">Ask</button></div>
<p>The assistant runs the application&rsquo;s own checks. Every figure in an answer was
computed before the sentence was written.</p></div>
</aside>
<script id="asst-data" type="application/json">{json.dumps(answers)}</script>"""


def assistant_answers(acts: list) -> dict:
    """Ask the running assistant one question per action, and keep what it said.

    The routing table is the backend's own — `agents.assistant._CUES` — so a question typed in
    the walkthrough reaches the same action it would reach in the application. Anything that
    matches nothing becomes `explain`, exactly as it does there.
    """
    from app.agents.assistant import ACTIONS, _CUES

    out = {"cues": [[k, list(c)] for k, c in _CUES], "answers": {}, "labels": {}}
    for act in ACTIONS:
        out["labels"][act.key] = act.label
        try:
            state = _post(f"/cases/{CASE}/assistant", {"question": act.label, "action": act.key})
        except Exception:                                    # noqa: BLE001
            continue
        msgs = state.get("messages") or []
        if msgs:
            last = msgs[-1]
            out["answers"][act.key] = {"text": last.get("content", ""),
                                       "tag": last.get("action", ""),
                                       "did": last.get("did", "")}
    _delete(f"/cases/{CASE}/assistant")
    return out


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
    summary = _get(f"/cases/{CASE}/investigation/summary")
    asmt = _get(f"/cases/{CASE}/assessment")
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
    # Every action's answer, captured now so the walkthrough can reply the way the application
    # replies. Collected before the seeded exchange, because collecting it clears the thread.
    answers = assistant_answers([])

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
    answers["labels"] = {a["key"]: a["label"] for a in asst.get("actions", [])}

    theme = THEME.read_text(encoding="utf-8") if THEME.exists() else ""
    theme = inline_fonts(theme)

    # The sidebar is what is global; the tabs are what is inside a case. Mirrored here because
    # a walkthrough that put all four side by side would be showing a different product: an
    # auditor lands on the queue and opens a case, and the three modules are what is *in* the
    # case rather than peers of the list that contains it.
    modules = {
        "correspondence": ("Taxpayer Correspondence", "What we asked, what arrived",
                           correspondence(loop, threads)),
        "investigation": ("Investigation", "What the evidence shows", investigation(inv, z, summary, asmt)),
        "report": ("Audit Report", "What you concluded", report(rep, inv, verdict)),
    }
    panes = "".join(
        f'<div class="pane" id="pane-{k}">{body}</div>'
        for k, (t, s, body) in modules.items())
    tabs = "".join(
        f'<a class="casetab{" active" if k == "correspondence" else ""}" data-tab="{k}">'
        f'{e(t)}</a>' for k, (t, _, _) in modules.items())
    row = next((c for c in cases if c["case_id"] == CASE), {})
    taxpayer = row.get("taxpayer", CASE)
    vat_no = row.get("vat_no", "")
    period = row.get("period", "")
    case_json = json.dumps(CASE)
    instr_line = next((ln for ln in (instr.get("text") or "").split("\n") if ln.strip()),
                      "None set — add what the documents don't say")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-AUDIT — walkthrough</title>
<style>{theme}
body{{margin:0;padding:0 0 60px}}
.wrap{{max-width:1440px;padding:26px 48px 60px}}
.navlink{{cursor:pointer}}
.side{{position:sticky;top:0;height:100vh}}
.demo-note{{background:var(--surface-2);border:1px solid var(--line);border-radius:11px;
  padding:13px 16px;margin-bottom:18px;font-size:13px;line-height:1.6}}
/* `display:flex` beats the `hidden` attribute on its own, so the sections this file toggles
   need it said explicitly. The case card itself no longer collapses — the app's does not
   either — so the rule that used to gate its items on `.on` is gone with the handler. */
[hidden]{{display:none!important}}
.panehead{{margin:0 0 18px;padding-bottom:12px;border-bottom:1px solid var(--line)}}
.panehead h1{{margin:0;font-size:20px}}
.panehead p{{margin:3px 0 0;font-size:12.5px;color:var(--muted)}}
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
<a class="navlink active" data-view="cases"><span class="ic"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7"/></svg></span>
<span>Cases</span><span class="count">{len(cases)}</span></a>

<div class="navgroup-open" id="navcase" hidden>
<div class="navgroup-head">
<span class="navgroup-name"><b>{e(taxpayer)}</b><small>{e(CASE)}</small></span></div>
<div class="navgroup-items">
<span class="navsub out" aria-disabled="true"
title="Outside the scope of this proof of concept">Initial assessment
<span class="navsub-scope">Out of scope</span></span>
<a class="navsub active" data-tab="correspondence">Correspondence</a>
<a class="navsub" data-tab="investigation">Investigation</a>
<a class="navsub" data-tab="report">Audit report</a>
</div></div>

<div class="sidecards" id="sidecards" hidden>
<button class="sidecard set" id="nav-instr">
<span class="ic"><svg viewBox="0 0 24 24" width="13" height="13" fill="none"
stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="5" y1="7" x2="19"
y2="7"/><line x1="5" y1="12" x2="19" y2="12"/><line x1="5" y1="17" x2="13" y2="17"/></svg></span>
<span class="sidecard-txt"><b>Case instructions</b><span>{e(instr_line)}</span></span></button>
<button class="sidecard ask" id="nav-ai">
<span class="ic">{SPARK}</span>
<span class="sidecard-txt"><b>Ask about this case</b>
<span>Status, gaps, ZATCA records</span></span></button>
</div>
<div class="side-foot"><button class="iconbtn" id="theme-btn" title="Toggle theme"></button><span>Static walkthrough. Figures are the engine\u2019s real output for the seeded case; nothing is saved.</span></div>
</aside>
<main class="main"><div class="wrap">

<div class="demo-note"><b>A static walkthrough, not the application.</b> Every figure, finding,
citation and gap on this page is the real output of the engine for the seeded demo case
{e(CASE)}, captured when this file was generated. <b>What works here:</b> opening the case,
moving between its modules, opening the evidence behind a finding, writing the case
instructions, and editing the assessment, the report fields and the verdict letter — those are the auditor's own words, so a file with no backend can do the
whole interaction. <b>What does not:</b> uploading, re-running the investigation and asking the
assistant, which all need the engine; they say so when you click them rather than going quiet.
Nothing you change here is saved anywhere. The regulations corpus behind the citations holds
{cov.get('article_count', 0)} articles, {len(cov.get('amended_since_english_edition', []))} of
which have been amended since the English edition they are shown in.</div>

<div class="view on" id="view-cases">{case_list(cases, CASE)}</div>

<div class="view" id="view-case">
<div class="casehead"><div class="casehead-in">
<button class="back" id="back">&#8592; All cases</button>
<h1>{e(taxpayer)}</h1>
<p class="meta"><span class="mono">{e(CASE)}</span> &middot;
<span class="mono">{e(vat_no)}</span> &middot; {e(period)}</p>
<nav class="casetabs">{tabs}</nav>
</div></div>
<div class="page">
{instructions(instr)}
{panes}
</div>
</div>

</div></div>{assistant(asst, answers)}<script>
/* The modules are reachable from the rail and from the header tabs. Both are the same
   selector, so the two cannot get out of step. */
const tabs = document.querySelectorAll('[data-tab]');
function show(k) {{
  tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === k));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + k));
  window.scrollTo(0, 0);
}}
tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));

const navcase = document.getElementById('navcase');
function view(name) {{
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + name));
  // The assistant is a *case* assistant, so it is docked inside a case and nowhere else. Left
  // over the queue it squeezed the table for a panel that had nothing to say about it.
  dock(name === 'case');
  // The group appears when a case is open and goes when you leave it — a module link with no
  // case behind it would be pointing at nothing.
  navcase.hidden = name !== 'case';
  document.getElementById('sidecards').hidden = name !== 'case';
  document.querySelectorAll('.navlink[data-view]').forEach(
    n => n.classList.toggle('active', n.dataset.view === (name === 'case' ? 'cases' : name)));
  window.scrollTo(0, 0);
}}

document.querySelectorAll('[data-open]').forEach(
  r => r.addEventListener('click', () => {{ view('case'); show('correspondence'); }}));
document.getElementById('new-case').addEventListener('click', () => toast(
  'In the application this opens the Add case form \u2014 taxpayer, TIN, period, activities '
  + '\u2014 and writes a real case. A static file has no database to write it to.'));
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

/* The two sidebar entries that are not modules: both reach something that is on all three,
   so they open it wherever you are rather than navigating away from the module you were in. */
document.getElementById('nav-ai').addEventListener('click', () => dock(true));
document.getElementById('nav-instr').addEventListener('click', () => {{
  showInstr(true);
  instrText.focus();
  instr.scrollIntoView({{block: 'center'}});
}});

/* --------------------------------------------------- the two sections that open
   Collapsed by default, exactly as in the application: the summary is what the auditor came
   for, and the evidence behind it is one click away rather than in front of it. */
function toggle(root, body, mark, action) {{
  const el = document.getElementById(root);
  const b = document.getElementById(body);
  const m = document.getElementById(mark);
  el.querySelector('.' + (action || 'zsrc') + '-head').addEventListener('click', () => {{
    const on = b.hidden;
    b.hidden = !on;
    el.classList.toggle('on', on);
    m.innerHTML = on ? '&#9662;' : '&#9656;';
    const a = el.querySelector('.collapse-action');
    if (a) a.textContent = on ? 'Close' : 'Open';
  }});
}}
toggle('zsrc', 'zsrc-body', 'zsrc-mark', 'zsrc');
toggle('inv-detail', 'inv-detail-body', 'inv-detail-mark', 'collapse');

/* The assessment is the auditor's own words, so this file can do the whole interaction. */
const assessText = document.getElementById('assess-text');
document.getElementById('assess-edit').addEventListener('click', () => {{
  if (assessText.dataset.editing) return;
  assessText.dataset.editing = '1';
  const ta = document.createElement('textarea');
  ta.className = 'assess-input';
  ta.rows = 16;
  ta.value = assessText.textContent;
  const bar = document.createElement('div');
  bar.className = 'row-actions';
  const save = document.createElement('button');
  save.className = 'btn'; save.textContent = 'Save assessment';
  const cancel = document.createElement('button');
  cancel.className = 'linklike'; cancel.textContent = 'cancel';
  bar.append(save, cancel);
  assessText.hidden = true;
  assessText.after(ta, bar);
  ta.focus();
  const done = () => {{ ta.remove(); bar.remove(); assessText.hidden = false;
                        delete assessText.dataset.editing; }};
  cancel.addEventListener('click', done);
  save.addEventListener('click', () => {{
    if (ta.value.trim()) assessText.textContent = ta.value.trim();
    done();
    toast('Assessment saved. In the application it is kept beside the engine\u2019s draft.');
  }});
}});
document.querySelectorAll('.assess-steers .btn-ghost, .matter-act .btn-ghost').forEach(
  btn => btn.addEventListener('click', () => toast(
    'That needs the engine \u2014 in the application this rewrites the assessment, or records '
    + 'your ruling on that matter.')));

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
document.querySelectorAll('.dropzone, .btn[disabled], .instr + * button[disabled]')
  .forEach(el => el.addEventListener('click', () => toast(NEEDS_ENGINE), true));
document.querySelectorAll('tr.caserow:not([data-open])').forEach(
  r => {{ r.style.cursor = 'pointer';
          r.addEventListener('click', () => toast(
            'Only ' + {case_json} + ' was captured into this file — the other rows are the real '
            + 'queue, with no output behind them here.')); }});

/* The theme toggle, as in the application. */
const SUN = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.5"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
const themeBtn = document.getElementById('theme-btn');
function paintTheme() {{
  const dark = document.documentElement.dataset.theme === 'dark';
  themeBtn.innerHTML = dark ? SUN : MOON;
}}
themeBtn.addEventListener('click', () => {{
  const dark = document.documentElement.dataset.theme === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  paintTheme();
}});
document.documentElement.dataset.theme =
  matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
paintTheme();

const dock = on => document.body.classList.toggle('asst-on', on);
/* ------------------------------------------------------ the assistant, answering
   Not a model in the page: the engine's own answers, captured per action when this file was
   generated, and routed by the backend's own cue table. A question that matches nothing falls
   to `explain`, exactly as it does in the application. */
const ASST = JSON.parse(document.getElementById('asst-data').textContent);

function route(q) {{
  const t = (q || '').toLowerCase();
  for (const [key, cues] of ASST.cues) {{
    if (cues.some(c => t.includes(c))) return key;
  }}
  return 'explain';
}}

function bubble(role, text, tag, did) {{
  const el = document.createElement('div');
  el.className = 'asst-msg ' + role;
  if (tag && tag !== 'explain') {{
    const t = document.createElement('span');
    t.className = 'pill status';
    t.textContent = tag.replace(/_/g, ' ');
    el.append(t);
  }}
  const pre = document.createElement('pre');
  pre.textContent = text;
  el.append(pre);
  if (did) {{
    const d = document.createElement('span');
    d.className = 'asst-did';
    d.textContent = '\u2713 ' + did;
    el.append(d);
  }}
  const body = document.getElementById('asst-body');
  body.append(el);
  body.scrollTop = body.scrollHeight;
}}

function askAssistant(q, forced) {{
  const key = forced || route(q);
  bubble('auditor', q);
  const a = ASST.answers[key] || ASST.answers['explain'];
  if (!a) {{
    bubble('assistant', 'That needs the engine, which this walkthrough does not carry.');
    return;
  }}
  bubble('assistant', a.text, a.tag || key, a.did);
}}

document.querySelectorAll('.qchip[data-act]').forEach(c => c.addEventListener('click', () => {{
  dock(true);
  askAssistant(ASST.labels[c.dataset.act] || c.textContent, c.dataset.act);
}}));

const asstQ = document.getElementById('asst-q');
const send = () => {{
  const v = asstQ.value.trim();
  if (!v) return;
  asstQ.value = '';
  askAssistant(v);
}};
document.getElementById('asst-send').addEventListener('click', send);
asstQ.addEventListener('keydown', ev => {{ if (ev.key === 'Enter') send(); }});

document.getElementById('asst-open').addEventListener('click', () => dock(true));
document.getElementById('asst-close').addEventListener('click', () => dock(false));
view('cases');
</script></body></html>"""


if __name__ == "__main__":                               # pragma: no cover
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
