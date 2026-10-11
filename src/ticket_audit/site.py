"""Pages of the deployed system. The home page walks the method (problem to improvement) with evidence;
batch pages show what happened to every ticket; trace pages show every step for one ticket.

Every number comes from the runs, the evaluation or the build's test results; nothing is typed in.
"""
from html import escape
from urllib.parse import quote

from ticket_audit.domain.normalize import key
from ticket_audit.domain.rules import CHECKS, CONFIG, REASONS, RULE_VERSION
from ticket_audit.improvements import IMPROVEMENTS
from ticket_audit.report import SHOWN_FIELDS, Summary

REPO = "https://github.com/oxyp1e/ticket-audit/blob/main/"
SCALE_FIELDS = [("scale_ticket_no", "Ticket"), ("date", "Date"), ("unit", "Unit"), ("product", "Product"),
                ("gross_kg", "Gross"), ("tare_kg", "Tare"), ("net_kg", "Net")]

# What a billing clerk does about each reason. Interface text, not rules.
ACTIONS = {
    "DUPLICATE_TICKET": "Don't bill. Confirm the first submission was billed, then discard this copy.",
    "WEIGHT_MISMATCH": "Compare the two photos. Bill the scale weight once the driver's figure is explained.",
    "SCALE_INCONSISTENT": "Ask the scale house for a reprint.",
    "SCALE_MISMATCH": "Check the driver attached the right scale ticket.",
    "NO_SCALE_TICKET": "Ask the driver for the scale ticket photo.",
    "NO_SIGNATURE": "Get the receiver's sign-off, or the customer's confirmation, before billing.",
    "MISSING_COST_CODE": "Get the AFE / cost code from the customer before billing.",
    "COST_CODE_MISMATCH": "Confirm with the customer which AFE applies.",
    "MISSING_PO": "Confirm the PO with the customer.",
    "PO_MISMATCH": "Read the PO off the photo; confirm it with the customer if it really differs.",
    "LOW_CONFIDENCE": "Read the value off the photo and confirm it.",
    "UNREADABLE_FIELD": "Read the field off the photo, or ask the driver.",
    "UNKNOWN_CUSTOMER": "Add the customer to master data, or correct the ticket.",
    "UNKNOWN_ORIGIN": "Add the pit to master data, or correct the ticket.",
    "UNKNOWN_LEASE": "Add the lease to master data, or correct the ticket.",
    "INVALID_LSD": "Check the land description against the lease.",
    "LSD_MISMATCH": "Check the land description against the lease.",
    "NO_DISPATCH_MATCH": "Ask dispatch whether this load happened; add it to dispatch if it did.",
    "FALLBACK_MATCH": "Confirm with dispatch that this ticket is the matched load.",
    "AMBIGUOUS_MATCH": "Ask dispatch which load this was.",
    "DISPATCH_MISMATCH": "Find out which record is wrong, the ticket or dispatch, and correct it.",
    "NO_RATE": "Add the rate for this customer and route, then re-run.",
    "RATE_EXPIRED": "Get the renewed rate, then re-run.",
    "AMBIGUOUS_RATE": "Remove the overlapping rate, then re-run.",
    "STANDBY_MISMATCH": "Compare the written standby with the times on the ticket.",
    "STANDBY_RECOVERED": "Confirm the standby before billing it.",
    "MISSING_TICKET": "Ask the driver for the ticket; the load can't be billed without it.",
    "ORPHAN_SCALE_TICKET": "Find the haul ticket this scale ticket belongs to.",
    "UNREADABLE_DOCUMENT": "Look at the photo; ask for a retake if needed.",
    "DUPLICATE_FILE": "Discard: the identical photo was already submitted.",
}
OUTCOME = {"approve": ("Approved", "ok"), "approve_adjusted": ("Approved, standby added", "ok"),
           "exception": ("Held for review", "hold"), "missing_ticket": ("Missing ticket", "hold")}
STATUS = {"pass": ("✓", "pass", "Passed"), "fail": ("✗", "fail", "Failed"),
          "adjust": ("+", "adjust", "Adjusted"), "skip": ("–", "skip", "Not checked")}

CSS = """
:root { --bg:#f6f5f1; --panel:#fff; --ink:#1d1d1f; --muted:#64646a; --line:#e2e0d9; --accent:#1f5f8b;
  --good:#2f7d4f; --warn:#9a5800; --bad:#b3261e; --chip:#eef1f4; --on-warn:#fff; --soft:#f0efe9; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#141416; --panel:#1d1d20;
  --ink:#ececee; --muted:#9a9aa1; --line:#2e2e33; --accent:#78b3dc; --good:#6cc28f; --warn:#e5a44a;
  --bad:#f28b82; --chip:#26262b; --on-warn:#1d1d1f; --soft:#232327; } }
:root[data-theme="dark"] { --bg:#141416; --panel:#1d1d20; --ink:#ececee; --muted:#9a9aa1; --line:#2e2e33;
  --accent:#78b3dc; --good:#6cc28f; --warn:#e5a44a; --bad:#f28b82; --chip:#26262b; --on-warn:#1d1d1f; --soft:#232327; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
a { color:var(--accent); }
nav.top { position:sticky; top:0; z-index:5; background:var(--panel); border-bottom:1px solid var(--line); }
nav.top div { max-width:1080px; margin:0 auto; padding:10px 16px; display:flex; gap:6px 18px; flex-wrap:wrap; align-items:center; font-size:14px; }
nav.top b { margin-right:auto; } nav.top a { text-decoration:none; } nav.top a.on { font-weight:700; color:var(--ink); }
main { max-width:1080px; margin:0 auto; padding:28px 16px 72px; }
h1 { font-size:28px; line-height:1.2; margin:0 0 8px; letter-spacing:-.015em; }
h2 { font-size:20px; margin:0 0 4px; letter-spacing:-.01em; }
h3 { font-size:15px; margin:18px 0 8px; }
p { margin:0 0 10px; } .lede { font-size:17px; color:var(--muted); max-width:760px; }
.muted { color:var(--muted); } .small { font-size:13px; color:var(--muted); }
.synthetic { display:inline-block; background:var(--warn); color:var(--on-warn); font-size:12px; font-weight:600; padding:2px 9px; border-radius:99px; vertical-align:middle; }
.crumbs { font-size:13px; color:var(--muted); margin-bottom:10px; }
section.step { display:grid; grid-template-columns:150px minmax(0,1fr); gap:24px; padding:30px 0; border-top:1px solid var(--line); }
section.step > .label { font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); }
section.step > .label span { display:block; font-size:30px; font-weight:800; color:var(--line); letter-spacing:0; }
.quote { border-left:3px solid var(--accent); padding:4px 0 4px 14px; margin:10px 0 14px; font-size:16px; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }
.grid3 { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:12px 0; }
.grid2 { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:12px 0; }
.panel h4 { margin:0 0 6px; font-size:14px; } .panel ul { margin:0; padding-left:18px; font-size:14px; }
table.t { border-collapse:collapse; width:100%; font-size:14px; background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
table.t th, table.t td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
table.t th { font-size:12px; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.04em; background:var(--soft); }
table.t tr:last-child td { border-bottom:0; } td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.wrap { overflow-x:auto; }
code, .mono { font:12.5px/1.4 ui-monospace,Menlo,monospace; overflow-wrap:anywhere; }
.tag { font:600 11px/1.6 ui-monospace,Menlo,monospace; background:var(--chip); color:var(--bad); padding:1px 6px; border-radius:6px; white-space:nowrap; }
.tag.adj { color:var(--warn); }
.ok-badge, .hold-badge { display:inline-block; font-size:13px; font-weight:700; padding:3px 10px; border-radius:99px; }
.ok-badge { background:color-mix(in srgb, var(--good) 15%, transparent); color:var(--good); }
.hold-badge { background:color-mix(in srgb, var(--bad) 13%, transparent); color:var(--bad); }
svg.diagram { width:100%; height:auto; display:block; }
svg.diagram .box { fill:var(--panel); stroke:var(--line); stroke-width:1.5; }
svg.diagram .box.key { stroke:var(--accent); } svg.diagram .box.hold { stroke:var(--bad); } svg.diagram .box.ok { stroke:var(--good); }
svg.diagram text { fill:var(--ink); font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
svg.diagram text.sub { fill:var(--muted); font-size:11.5px; } svg.diagram text.lane { font-weight:700; font-size:12px; fill:var(--accent); letter-spacing:.05em; }
svg.diagram line, svg.diagram path { stroke:var(--muted); stroke-width:1.5; fill:none; }
svg.diagram .arrowhead { fill:var(--muted); stroke:none; }
.flow { display:flex; flex-wrap:wrap; gap:8px; align-items:stretch; margin:14px 0; }
.flow .n { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:120px; flex:1; }
.flow .n b { display:block; font-size:24px; font-variant-numeric:tabular-nums; } .flow .n span { font-size:13px; color:var(--muted); }
.flow .n.ok { border-color:var(--good); } .flow .n.hold { border-color:var(--bad); }
.flow .arrow { align-self:center; color:var(--muted); }
ol.checks { list-style:none; margin:0; padding:0; background:var(--panel); border:1px solid var(--line); border-radius:12px; }
ol.checks li { display:grid; grid-template-columns:28px minmax(170px,240px) minmax(0,1fr); gap:10px; padding:9px 14px; border-bottom:1px solid var(--line); font-size:14px; }
ol.checks li:last-child { border-bottom:0; }
.st { width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:13px; }
.st.pass { background:color-mix(in srgb, var(--good) 16%, transparent); color:var(--good); }
.st.fail { background:color-mix(in srgb, var(--bad) 16%, transparent); color:var(--bad); }
.st.adjust { background:color-mix(in srgb, var(--warn) 18%, transparent); color:var(--warn); }
.st.skip { background:var(--chip); color:var(--muted); }
li.fail { background:color-mix(in srgb, var(--bad) 5%, transparent); }
.photos { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.photos a { display:block; text-decoration:none; color:var(--muted); font-size:12px; }
.photos img { width:100%; border-radius:10px; border:1px solid var(--line); background:var(--chip); display:block; margin-bottom:4px; }
.conf { display:inline-block; width:56px; height:6px; background:var(--chip); border-radius:99px; overflow:hidden; vertical-align:middle; margin-right:6px; }
.conf i { display:block; height:100%; background:var(--good); } .conf.low i { background:var(--bad); }
.changed { background:color-mix(in srgb, var(--warn) 14%, transparent); border-radius:4px; padding:0 3px; }
.callout { border:1px solid var(--bad); background:color-mix(in srgb, var(--bad) 6%, var(--panel)); border-radius:12px; padding:14px 18px; margin:14px 0; }
.callout.ok { border-color:var(--good); background:color-mix(in srgb, var(--good) 6%, var(--panel)); }
.callout ul { margin:6px 0 0; padding-left:18px; }
.imp { border-left:3px solid var(--line); padding:2px 0 2px 16px; margin:0 0 18px; }
.imp h4 { margin:0 0 4px; font-size:15px; } .imp .d { font-size:12px; color:var(--muted); }
.imp dl { display:grid; grid-template-columns:70px minmax(0,1fr); gap:3px 12px; margin:6px 0 0; font-size:14px; }
.imp dt { color:var(--muted); font-weight:600; }
.money td.num { font-weight:700; }
details summary { cursor:pointer; }
.cards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
a.card { display:block; text-decoration:none; color:inherit; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }
a.card:hover { border-color:var(--accent); } a.card b { font-size:17px; }
@media (max-width:760px) {
  section.step { grid-template-columns:minmax(0,1fr); gap:8px; } section.step > .label span { display:inline; font-size:14px; margin-right:6px; color:var(--accent); }
  .grid3, .grid2, .cards, .photos { grid-template-columns:minmax(0,1fr); }
  ol.checks li { grid-template-columns:28px minmax(0,1fr); } ol.checks li .detail { grid-column:2; }
  h1 { font-size:24px; }
}
"""


def _money(x: float) -> str:
    return f"${x:,.2f}"


def page(title: str, body: str, batches: list[str], current: str = "") -> str:
    links = [('<a href="/" class="on">How it works</a>' if current == "home" else '<a href="/">How it works</a>')]
    for b in batches:
        cls = ' class="on"' if current == b else ""
        links.append(f'<a href="/b/{escape(b)}/"{cls}>{escape(b.capitalize())} batch</a>')
    links.append('<a href="/logout">Sign out</a>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title><style>{CSS}</style></head>
<body><nav class="top"><div><b>Ticket Audit</b>{''.join(links)}</div></nav><main>{body}</main></body></html>"""


def _arrow(x1, y1, x2, y2) -> str:
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2 - 7}" y2="{y2}"/>'
            f'<polygon class="arrowhead" points="{x2},{y2} {x2 - 8},{y2 - 4} {x2 - 8},{y2 + 4}"/>')


def _box(x, y, w, h, title, sub="", cls="") -> str:
    out = f'<rect class="box {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>'
    out += f'<text x="{x + w / 2}" y="{y + (h / 2 - 3 if sub else h / 2 + 4)}" text-anchor="middle">{escape(title)}</text>'
    if sub:
        out += f'<text class="sub" x="{x + w / 2}" y="{y + h / 2 + 13}" text-anchor="middle">{escape(sub)}</text>'
    return out


def process_map(approved: int, held: int, total: int) -> str:
    today = [("Ticket arrives", "photo or paper"), ("Find the load", "in dispatch"), ("Check the ticket", "weight, signature, AFE"),
             ("Look up the rate", "and standby"), ("Invoice", "")]
    svg = ['<svg class="diagram" viewBox="0 0 1000 300" role="img" aria-label="Process today and with the system">',
           '<text class="lane" x="0" y="18">TODAY: A PERSON, FOR EVERY TICKET</text>']
    x = 0
    for i, (t, s) in enumerate(today):
        svg.append(_box(x, 30, 176, 58, t, s, "key" if 0 < i < 4 else ""))
        if i < len(today) - 1:
            svg.append(_arrow(x + 176, 59, x + 206, 59))
        x += 206
    svg.append('<text class="lane" x="0" y="140">WITH THE SYSTEM: THE SAME CHECKS, EVERY TICKET; A PERSON ONLY FOR EXCEPTIONS</text>')
    svg.append(_box(0, 152, 176, 58, "Ticket photos", "haul + scale"))
    svg.append(_arrow(176, 181, 206, 181))
    svg.append(_box(206, 152, 176, 58, "Read", "Azure Document Intelligence", "key"))
    svg.append(_arrow(382, 181, 412, 181))
    svg.append(_box(412, 152, 176, 58, "Match and check", "14 checks, rules only", "key"))
    svg.append('<path d="M588 181 L618 181 L618 128 L640 128"/><polygon class="arrowhead" points="648,128 640,124 640,132"/>')
    svg.append('<path d="M618 181 L618 236 L640 236"/><polygon class="arrowhead" points="648,236 640,232 640,240"/>')
    svg.append(_box(648, 100, 176, 56, "Invoice-ready lines", f"{approved} of {total} tickets", "ok"))
    svg.append(_box(648, 208, 176, 56, "Exception queue", f"{held} items, each with a reason", "hold"))
    svg.append(_arrow(824, 236, 854, 236))
    svg.append(_box(854, 208, 146, 56, "A person", "works the queue"))
    svg.append("</svg>")
    return "".join(svg)


def pipeline_diagram() -> str:
    steps = [("Intake", "SHA-256, dedupe"), ("Read", "engine interface"), ("Normalize", "dates, names, LSD"),
             ("Match", "dispatch (TMS)"), ("Rate check", "rate sheet"), ("Decide", "pure rules")]
    svg = ['<svg class="diagram" viewBox="0 0 1000 190" role="img" aria-label="Pipeline">']
    x = 0
    for i, (t, s) in enumerate(steps):
        svg.append(_box(x, 20, 140, 58, t, s, "key" if t in ("Read", "Decide") else ""))
        if i < len(steps) - 1:
            svg.append(_arrow(x + 140, 49, x + 168, 49))
        x += 168
    svg.append('<text class="sub" x="238" y="96" text-anchor="middle">Azure DI · local OCR · generator truth</text>')
    svg.append('<path d="M910 78 L910 104 L640 104 L640 128"/><path d="M910 104 L910 128"/>')
    svg.append('<polygon class="arrowhead" points="640,128 636,120 644,120"/><polygon class="arrowhead" points="910,128 906,120 914,120"/>')
    svg.append(_box(520, 128, 240, 52, "approved.csv", "invoice-ready lines", "ok"))
    svg.append(_box(790, 128, 210, 52, "Exception queue", "plain reasons", "hold"))
    svg.append('<path d="M70 78 L70 150 L120 150" stroke-dasharray="4 4"/><path d="M406 78 L406 150 L360 150" stroke-dasharray="4 4"/>')
    svg.append(_box(120, 128, 240, 52, "Decision log", "append-only; every step, every check"))
    svg.append("</svg>")
    return "".join(svg)


def _rule_rows() -> str:
    rows = []
    for _, name, requires, codes in CHECKS:
        text = requires.format(**CONFIG)
        tags = " ".join(f'<span class="tag{" adj" if c == "STANDBY_RECOVERED" else ""}">{c}</span>' for c in codes)
        rows.append(f"<tr><td><b>{escape(name)}</b></td><td>{escape(text)}</td><td>{tags}</td></tr>")
    return "".join(rows)


def home(batches: dict, build: dict | None, startup: dict) -> str:
    names = list(batches)
    day = batches.get("day", next(iter(batches.values())))
    s: Summary = day["summary"]
    held = len(s.queue)
    ev_rows, total_photos = "", 0
    for name, b in batches.items():
        ev = b["summary"].evaluation
        if not ev:
            continue
        f, o = ev["fields"], ev["outcomes"]
        total_photos += f["documents"]
        ev_rows += (f"<tr><td>{escape(name.capitalize())}</td><td class='num'>{f['documents']}</td>"
                    f"<td class='num'>{f['fields_right']:,} / {f['fields_read']:,}</td>"
                    f"<td class='num'>{f['confidently_wrong']}</td>"
                    f"<td class='num'>{o['planted_caught']} / {o['planted']}</td>"
                    f"<td class='num'>{o['clean_approved']} / {o['clean']}</td></tr>")
    tests = ""
    if build:
        fit = "".join(f"<li>{'✓' if f['passed'] else '✗'} {escape(f['label'])}</li>" for f in build["fitness"])
        mut = "".join(f"<li>{'✓ caught' if m['caught'] else '✗ missed'}: {escape(m['label'])}</li>" for m in build["mutants"])
        tests = f"""<div class="grid2">
  <div class="panel"><h4>{build['tests']['passed']} of {build['tests']['total']} automated tests passed</h4>
    <p class="small">Run while building the image now serving this page (commit <code>{escape(build['commit'])}</code>,
    {escape(build['built'][:10])}). The build fails if any test fails.</p>
    <h4>Fitness functions</h4><ul>{fit}</ul></div>
  <div class="panel"><h4>Can the tests fail? Deliberate breaks</h4>
    <p class="small">Each break is applied to the code, the tests run, and the break is reverted. A break the
    tests don't catch would fail the build.</p><ul>{mut}</ul></div></div>"""
    imps = "".join(f"""<div class="imp"><span class="d">{escape(i['date'])}</span><h4>{escape(i['title'])}</h4><dl>
<dt>Found</dt><dd>{escape(i['found'])}</dd><dt>Changed</dt><dd>{escape(i['change'])}</dd>
<dt>Effect</dt><dd>{escape(i['effect'])}</dd><dt>Evidence</dt><dd><a href="{REPO}{escape(i['evidence'])}">{escape(i['evidence'])}</a></dd></dl></div>"""
                   for i in sorted(IMPROVEMENTS, key=lambda i: i["date"]))
    cards = "".join(f"""<a class="card" href="/b/{escape(n)}/"><b>{escape(n.capitalize())} batch</b>
<p class="small" style="margin:6px 0 0">{b['summary'].tickets} tickets · {b['summary'].approved + b['summary'].adjusted} approved ·
{len(b['summary'].queue)} in the exception queue · every ticket traceable</p></a>""" for n, b in batches.items())
    timings = " · ".join(f"{escape(n)} batch {t:.1f} s" for n, t in startup.items())
    adrs = [("0001", "extraction-behind-an-interface", "The OCR engine sits behind an interface"),
            ("0002", "ai-never-approves", "AI never makes the approve decision"),
            ("0003", "when-in-doubt-exception", "When in doubt, it's an exception"),
            ("0004", "append-only-decision-log", "An append-only decision log with provenance"),
            ("0005", "one-process-sqlite-batch", "One process, SQLite, run as a batch"),
            ("0006", "position-based-field-pairing", "Read fields by position; Azure's pairing is a second opinion"),
            ("0007", "bill-from-the-scale-ticket", "Bill tonnes from the scale ticket"),
            ("0008", "deployment-read-only", "The deployed system is read-only and holds no OCR key")]
    adr_list = "".join(f'<li><a href="{REPO}docs/adr/{n}-{slug}.md">ADR {n[-1]}</a>: {escape(t)}</li>' for n, slug, t in adrs)
    body = f"""
<span class="synthetic">Synthetic data: invented companies, tickets and rates</span>
<h1 style="margin-top:12px">Automating the ticket audit before invoicing</h1>
<p class="lede">A working system for the problem in Bizi Transport's posting: read haul and scale tickets, compare them
with dispatch and the rate sheet, bill what is right, and hold everything uncertain for a person with a plain reason.
This page walks through how it was built, step by step, with the evidence for each step.</p>

<section class="step"><div class="label"><span>1</span>Problem</div><div>
  <h2>Hundreds of tickets a day, each compared by hand</h2>
  <p class="quote">"…receives hundreds of paper/PDF tickets every day and staff manually compare those tickets against
  dispatch information and customer rates before invoicing…" <span class="small">(application question 2)</span></p>
  <p>The work isn't reading the ticket; it's the <b>three-way comparison</b>. Errors come from three places, and a
  wrong invoice in either direction costs money: underbilling loses revenue, overbilling loses trust.</p>
  <div class="grid3">
    <div class="panel"><h4>The ticket</h4><ul><li>net weight differs from the scale ticket</li><li>no receiver signature</li>
      <li>no AFE / cost code</li><li>standby earned but not written</li><li>the same ticket sent twice</li><li>an unreadable value</li></ul></div>
    <div class="panel"><h4>Dispatch</h4><ul><li>a ticket for a load dispatch never recorded</li><li>a dispatched load whose ticket never came back</li>
      <li>no load number on the ticket</li></ul></div>
    <div class="panel"><h4>The rate sheet</h4><ul><li>no rate for this customer and route</li><li>the rate expired before the ticket date</li></ul></div>
  </div>
  <p class="small">Every one of these is planted in the synthetic batches, so the system can be checked against a known answer.</p>
</div></section>

<section class="step"><div class="label"><span>2</span>Process mapping</div><div>
  <h2>Same checks, every ticket; a person only for the exceptions</h2>
  {process_map(s.approved + s.adjusted, held, s.tickets)}
  <p>The checks a person does today become explicit rules that run on every ticket the same way. The person's job
  becomes the exception queue: in the day batch, {held} items for {s.tickets} tickets, each saying what failed and what to
  do next. <span class="small">The individual steps of today's process are an assumption from the posting's wording;
  mapping the real process with the billing team comes first in production.</span></p>
</div></section>

<section class="step"><div class="label"><span>3</span>Architecture</div><div>
  <h2>A pipeline where AI only reads and rules decide</h2>
  {pipeline_diagram()}
  <p>The probabilistic part (reading a photo) is separated from the decision (pure, deterministic rules with no I/O).
  Every decision is written to an append-only log with the SHA-256 of its source photos, the inputs as read, the rule
  version and the OCR model.</p>
  <div class="wrap"><table class="t"><thead><tr><th>Characteristic</th><th>Means here</th><th>Proved by (automated)</th></tr></thead><tbody>
  <tr><td><b>Auditability</b></td><td>every invoice line traceable and replayable</td><td>every approved line's photo hashes, dispatch, rate and log entry verify</td></tr>
  <tr><td><b>Data integrity</b></td><td>nothing wrong reaches an invoice; anything uncertain is held</td><td>every load gets exactly its required outcome; nothing planted is approved</td></tr>
  <tr><td><b>Reliability</b></td><td>no ticket lost or processed twice, even through a crash</td><td>a run killed halfway, re-run, gives byte-identical output</td></tr>
  </tbody></table></div>
  <p class="small" style="margin-top:8px">Deliberately not optimized: throughput (hundreds a day is one every few minutes:
  no queues or microservices) and availability (a batch that is down an hour delays tickets, loses none).</p>
  <h3>Decisions, with the reasoning and evidence</h3><ul>{adr_list}</ul>
</div></section>

<section class="step"><div class="label"><span>4</span>Development</div><div>
  <h2>The rules, as they run</h2>
  <p>A load is approved only when every check passes. This table is generated from the rule code itself, so it can't
  drift from what runs; its hash is the rule version stamped on every decision (<code>{escape(RULE_VERSION)}</code>).</p>
  <div class="wrap"><table class="t"><thead><tr><th>Check</th><th>Requires</th><th>Reasons it can give</th></tr></thead>
  <tbody>{_rule_rows()}</tbody></table></div>
  <p class="small" style="margin-top:8px">Tonnes are billed from the scale ticket. The one automatic change is standby
  earned but left blank, added and flagged. A match to dispatch without a load number is never auto-approved.
  Open any ticket in a batch to see every check with the values it compared.</p>
</div></section>

<section class="step"><div class="label"><span>5</span>Testing</div><div>
  <h2>Proved by tests, and measured on real OCR</h2>
  {tests}
  <h3>Real OCR: {total_photos} synthetic photos read by Azure AI Document Intelligence</h3>
  <div class="wrap"><table class="t"><thead><tr><th>Batch</th><th class="num">Photos</th><th class="num">Fields read right</th>
  <th class="num">Wrong, confident</th><th class="num">Problems held</th><th class="num">Should pass, approved</th></tr></thead>
  <tbody>{ev_rows}</tbody></table></div>
  <p class="small" style="margin-top:8px">Measured against the generator's answer key, which only this evaluation reads; the
  rules never see it. The audit batch's two held loads are a real misread of one PO (a handwritten 1 read as 7), held
  correctly. Synthetic tickets prove the engineering, not accuracy on real tickets; that comes from a pilot (step 8).</p>
</div></section>

<section class="step"><div class="label"><span>6</span>Deployment</div><div>
  <h2>Running now, at no cost, with nothing to leak</h2>
  <div class="grid2">
    <div class="panel"><h4>What happened when this server started</h4><ul>
      <li>Audited every batch from the saved Azure responses: {timings}</li>
      <li>Wrote the decision log, the invoice-ready lines and the exception queue you can browse here</li>
      <li>Holds no OCR key; a page budget of zero means it cannot call Azure</li></ul></div>
    <div class="panel"><h4>Safeguards</h4><ul>
      <li>Azure Container Apps, scales to zero; $1 budget alert; free tiers only</li>
      <li>Access code, signed cookie, 5 sign-in attempts per 15 minutes</li>
      <li>Read-only: no uploads, so no real documents can arrive</li>
      <li>Runbook for OCR, network, budget and storage failures: all fail closed</li></ul></div>
  </div>
  <p class="small"><a href="{REPO}docs/runbook.md">Runbook</a> · <a href="{REPO}deploy/deploy.sh">deploy script</a></p>
</div></section>

<section class="step"><div class="label"><span>7</span>Improvement</div><div>
  <h2>What broke while building it, and what changed</h2>
  <p>Every entry happened on this system's own runs. The numbers are from the run outputs.</p>
  {imps}
</div></section>

<section class="step"><div class="label"><span>8</span>Limits and next step</div><div>
  <h2>What this doesn't prove yet, and how to get there</h2>
  <div class="grid2">
    <div class="panel"><h4>Honest limits</h4><ul>
      <li>All data is synthetic; the ticket layout is designed from public descriptions of frac-sand hauling, not Bizi's forms</li>
      <li>Assumed, not sourced: B-train weights (38–42 t net), one hour of free time, the rates, the error shares</li>
      <li>Stand-ins: a folder for the inbox, SQLite for the TMS, CSV for accounting</li>
      <li>Not built: owner-operator settlements, multi-user review, accounting integration</li></ul></div>
    <div class="panel"><h4>Next step: a shadow-mode pilot</h4><ul>
      <li>20–50 real tickets of each type, the rate sheet's structure, and read access to dispatch data</li>
      <li>Fit the field reader to the real forms; add the real reason list from the billing team</li>
      <li>Run alongside billing for two weeks: it invoices nothing; its decisions are compared with the team's every day</li>
      <li>Go live only on agreed numbers: what share it handles alone, and zero wrong approvals</li></ul></div>
  </div>
</div></section>

<section class="step"><div class="label"><span>→</span>See it</div><div>
  <h2>Open a batch and follow any ticket</h2><div class="cards">{cards}</div>
</div></section>"""
    return page("Ticket Audit", body, names, "home")


def _flow(s: Summary) -> str:
    hauls = [e for e in s.entries.values() if e["kind"] == "haul"]
    photos = {d["file"] for e in s.entries.values() for d in e["documents"].values() if d}
    by_number = sum(1 for e in hauls if any(c["key"] == "dispatch" and c["status"] == "pass" for c in e["checks"]))
    nodes = [(len(photos), "photos received", ""), (s.tickets, "haul tickets read", ""),
             (by_number, "matched to dispatch by load number", ""), (s.approved + s.adjusted, "passed every check: invoice-ready", "ok"),
             (s.held, "tickets held for a person", "hold"), (s.missing, "dispatched loads with no ticket", "hold")]
    parts = []
    for i, (n, label, cls) in enumerate(nodes):
        parts.append(f'<div class="n {cls}"><b>{n}</b><span>{escape(label)}</span></div>')
        if i < 3:
            parts.append('<span class="arrow">→</span>')
    return f'<div class="flow">{"".join(parts)}</div>'


def _ticket_link(batch: str, e: dict, text: str | None = None) -> str:
    return f'<a href="/b/{escape(batch)}/t/{quote(e["subject"])}">{escape(text or e["ticket_no"] or e["subject"])}</a>'


def batch_page(name: str, s: Summary, names: list[str]) -> str:
    days = s.days[0] if len(s.days) == 1 else f"{s.days[0]} – {s.days[-1]}"
    queue_rows = ""
    for e in sorted(s.queue, key=lambda e: -e["amount"]):
        codes = [r["code"] for r in e["reasons"]]
        action = ACTIONS.get(next((c for c in codes if c != "STANDBY_RECOVERED"), codes[0]), "")
        label = e["ticket_no"] or (f"Load {e['subject']}" if e["kind"] == "missing_ticket" else e["subject"])
        tags = " ".join(f'<span class="tag{" adj" if c == "STANDBY_RECOVERED" else ""}">{c}</span>' for c in codes)
        queue_rows += (f"<tr><td>{_ticket_link(name, e, label)}</td><td>{tags}<div class='small'>{escape(e['reasons'][0]['message'])}</div></td>"
                       f"<td>{escape(action)}</td><td class='num'>{_money(e['amount']) if e['amount'] else '—'}</td></tr>")

    def listed(pred):
        items = [e for e in s.entries.values() if pred(e)]
        return ", ".join(_ticket_link(name, e, e["ticket_no"] or e["subject"]) for e in items) or "none"

    recovered = listed(lambda e: e["outcome"] == "approve_adjusted")
    stake_standby = listed(lambda e: e["outcome"] == "exception" and e["line"] and e["line"]["standby_recovered"]
                           and "DUPLICATE_TICKET" not in [r["code"] for r in e["reasons"]])
    missing = listed(lambda e: e["outcome"] == "missing_ticket")
    dupes = listed(lambda e: "DUPLICATE_TICKET" in [r["code"] for r in e["reasons"]])
    lines = "".join(
        f"<tr><td>{_ticket_link(name, e)}</td><td>{escape(e['line']['customer_code'])}</td><td>{escape(e['line']['dispatch_no'])}</td>"
        f"<td class='num'>{e['line']['net_t']:.2f}</td><td class='num'>{_money(e['line']['per_tonne'])}</td>"
        f"<td class='num'>{e['line']['standby_h']:g}{' +' if e['line']['standby_recovered'] else ''}</td>"
        f"<td class='num'>{_money(e['line']['total'])}</td></tr>"
        for e in sorted(s.lines, key=lambda e: e["ticket_no"]))
    ev = s.evaluation
    ev_line = ""
    if ev:
        f, o = ev["fields"], ev["outcomes"]
        ev_line = (f"<p class='small'>Checked against the generator's answer key: {o['planted_caught']} of {o['planted']} planted "
                   f"problems held; {o['clean_approved']} of {o['clean']} loads that should pass approved; "
                   f"{f['fields_right']:,} of {f['fields_read']:,} fields read correctly, {f['confidently_wrong']} wrong with high confidence.</p>")
    body = f"""<div class="crumbs"><a href="/">How it works</a> › {escape(name.capitalize())} batch</div>
<span class="synthetic">Synthetic batch</span>
<h1 style="margin-top:10px">{escape(name.capitalize())} batch: {s.tickets} tickets, {escape(days)}</h1>
<p class="lede">Every photo was read by Azure AI Document Intelligence and every ticket went through the same {len(CHECKS)} checks.
Open any ticket to see what was read, each check with the values it compared, and the decision.</p>
<h2 style="margin-top:22px">What happened to the tickets</h2>
{_flow(s)}
{ev_line}

<h2 style="margin-top:28px">The exception queue: what a person works through</h2>
<p class="small">{len(s.queue)} items instead of {s.tickets} tickets, largest amount first. Each says what failed and what to do.</p>
<div class="wrap"><table class="t"><thead><tr><th>Ticket</th><th>Why it's held</th><th>What to do</th><th class="num">Amount</th></tr></thead>
<tbody>{queue_rows or '<tr><td colspan=4>Nothing to review.</td></tr>'}</tbody></table></div>

<h2 style="margin-top:28px">What the checks found in money</h2>
<p class="small">Synthetic rates and amounts. Each figure is the sum of the tickets listed with it.</p>
<div class="wrap"><table class="t money"><thead><tr><th>Found</th><th>How it's counted</th><th class="num">Amount</th></tr></thead><tbody>
<tr><td><b>Standby recovered</b></td><td>Earned on site but left blank; added to lines that passed every check. Tickets: {recovered}</td><td class="num">{_money(s.recovered)}</td></tr>
<tr><td><b>Standby at stake</b></td><td>Earned on held tickets; billable once a person clears them. Tickets: {stake_standby}</td><td class="num">{_money(s.at_stake_standby)}</td></tr>
<tr><td><b>Loads with no ticket</b></td><td>Dispatched, no ticket came back; valued at planned tonnes × rate. Loads: {missing}</td><td class="num">{_money(s.at_stake_missing)}</td></tr>
<tr><td><b>Duplicates held back</b></td><td>Overbilling prevented: the same ticket submitted again. Tickets: {dupes}</td><td class="num">{_money(s.overbilling_prevented)}</td></tr>
</tbody></table></div>
<p class="small" style="margin-top:6px">Underbilling and overbilling are separate and never added together. Also on hold for review: {_money(s.on_hold_value)}.</p>

<h2 style="margin-top:28px">Invoice-ready lines ({len(s.lines)}, {_money(s.approved_value)})</h2>
<p class="small">Downloads: <a href="approved.csv">approved.csv</a> · <a href="exceptions.csv">exceptions.csv</a>. Every line carries
the SHA-256 of both photos, the dispatch number, the rate row, the rule version and its decision-log entry.</p>
<details><summary class="small">Show all {len(s.lines)} lines</summary><div class="wrap"><table class="t"><thead><tr><th>Ticket</th><th>Customer</th><th>Load</th>
<th class="num">Tonnes (scale)</th><th class="num">Rate /t</th><th class="num">Standby h</th><th class="num">Amount</th></tr></thead><tbody>{lines}</tbody></table></div></details>
"""
    return page(f"{name.capitalize()} batch · Ticket Audit", body, names, name)


def _read_table(e: dict) -> str:
    read, haul = e.get("read") or {}, (e["inputs"] or {}).get("haul") or {}
    normalized = {"ticket_no": haul.get("ticket_no"), "dispatch_no": haul.get("dispatch_no"), "date": haul.get("date"),
                  "unit": haul.get("unit"), "customer": haul.get("customer_code"), "po": haul.get("po"),
                  "afe": haul.get("afe"), "origin": haul.get("pit_code"), "lease": haul.get("lease_code"),
                  "lsd": haul.get("lsd"), "product": haul.get("product"), "net_t": haul.get("net_t"),
                  "scale_ticket_no": haul.get("scale_ticket_no"), "arrive": haul.get("arrive"),
                  "depart": haul.get("depart"), "standby_h": haul.get("standby_h")}
    rows = []
    for raw, label in SHOWN_FIELDS:
        f = read.get(raw)
        norm = normalized.get(raw)
        norm_txt = "" if norm in (None, "") else str(norm)
        if raw in ("arrive", "depart") and len(norm_txt) == 8:
            norm_txt = norm_txt[:5]
        if f is None:
            rows.append(f"<tr><td>{label}</td><td class='muted'>blank</td><td></td><td class='muted'>{escape(norm_txt) or '—'}</td></tr>")
            continue
        c = f["confidence"]
        floor = CONFIG["min_confidence_critical"] if raw in CONFIG["critical_fields"] else CONFIG["min_confidence"]
        bar = (f"<span class='conf{' low' if c < floor else ''}'><i style='width:{c * 100:.0f}%'></i></span>"
               f"<span class='mono'>{c:.2f}</span>")
        fixed = raw in ("lsd",) and norm_txt and norm_txt.replace("-", "") != f["value"].replace("-", "").replace(" ", "")
        norm_cell = f"<span class='changed' title='corrected while normalizing'>{escape(norm_txt)}</span>" if fixed else escape(norm_txt or "—")
        rows.append(f"<tr><td>{label}</td><td>{escape(f['value'])}</td><td style='white-space:nowrap'>{bar}</td><td class='mono'>{norm_cell}</td></tr>")
    return ("<div class='wrap'><table class='t'><thead><tr><th>Field</th><th>As read</th><th>OCR confidence</th><th>Normalized</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _scale_table(e: dict) -> str:
    read = e.get("read_scale") or {}
    if not read:
        return ""
    rows = "".join(f"<tr><td>{label}</td><td>{escape(read[k]['value'])}</td><td class='mono'>{read[k]['confidence']:.2f}</td></tr>"
                   for k, label in SCALE_FIELDS if k in read)
    return ("<h3>Scale ticket, as read</h3><div class='wrap'><table class='t'><thead><tr><th>Field</th><th>As read</th>"
            f"<th>Confidence</th></tr></thead><tbody>{rows}</tbody></table></div>")


def trace_page(name: str, e: dict, names: list[str]) -> str:
    label, cls = OUTCOME[e["outcome"]]
    title = e["ticket_no"] or (f"Load {e['subject']}" if e["kind"] == "missing_ticket" else e["subject"])
    codes = [r["code"] for r in e["reasons"]]
    if e["outcome"] in ("approve", "approve_adjusted"):
        verdict = (f"<div class='callout ok'><b>Approved.</b> Every check passed"
                   f"{', and standby earned on site was added to the line' if e['outcome'] == 'approve_adjusted' else ''}.</div>")
    else:
        items = "".join(f"<li><b>{escape(REASONS[r['code']])}</b>{escape(r['message'][len(REASONS[r['code']]):])}"
                        f"<div class='small'>What to do: {escape(ACTIONS.get(r['code'], ''))}</div></li>" for r in e["reasons"])
        verdict = f"<div class='callout'><b>Held for review.</b><ul>{items}</ul></div>"
    photos = "".join(f"<a href='../inbox/{escape(d['file'])}' target='_blank' rel='noopener'><img src='../inbox/{escape(d['file'])}' "
                     f"alt='{k} ticket photo' loading='lazy'>{k.capitalize()} ticket · {escape(d['file'])}</a>"
                     for k, d in e["documents"].items() if d)
    checks = ""
    for c in e.get("checks", []):
        icon, scls, alt = STATUS[c["status"]]
        checks += (f"<li class='{scls}'><span class='st {scls}' title='{alt}'>{icon}</span><b>{escape(c['name'])}</b>"
                   f"<span class='detail'>{escape(c['detail'])}</span></li>")
    line = e.get("line")
    calc = ""
    if line:
        calc = f"""<div class="wrap"><table class="t"><tbody>
<tr><td>Tonnes (from the scale ticket)</td><td class="num">{line['net_t']:.2f} t × {_money(line['per_tonne'])}/t</td><td class="num">{_money(line['tonnage_amount'])}</td></tr>
<tr><td>Standby{' (recovered: left blank on the ticket)' if line['standby_recovered'] else ''}</td><td class="num">{line['standby_h']:g} h × {_money(line['standby_per_h'])}/h</td><td class="num">{_money(line['standby_amount'])}</td></tr>
<tr><td><b>Line total</b></td><td></td><td class="num"><b>{_money(line['total'])}</b></td></tr></tbody></table></div>
<p class="small" style="margin-top:6px">{'Billed on the next invoice.' if e['outcome'] in ('approve', 'approve_adjusted') else 'Not billed: this amount waits in the exception queue.'}</p>"""
    dispatch = (e["inputs"] or {}).get("dispatch")
    haul = (e["inputs"] or {}).get("haul") or {}
    disp = ""
    if dispatch and e["kind"] == "haul":
        pairs = [("Load number", haul.get("dispatch_no") or "not written", dispatch["dispatch_no"]),
                 ("Date", haul.get("date"), dispatch["date"]), ("Unit", haul.get("unit"), dispatch["unit"]),
                 ("Customer", haul.get("customer_code"), dispatch["customer_code"]),
                 ("Pit", haul.get("pit_code"), dispatch["pit_code"]), ("Lease", haul.get("lease_code"), dispatch["lease_code"]),
                 ("Product", (e.get("read") or {}).get("product", {}).get("value") or haul.get("product"), dispatch["product"])]
        rows = "".join(f"<tr><td>{a}</td><td class='mono'>{escape(str(t))}</td><td class='mono'>{escape(str(d))}</td>"
                       f"<td>{'✓' if t is not None and key(str(t)) == key(str(d)) else '✗'}</td></tr>" for a, t, d in pairs)
        disp = ("<h2 style='margin-top:26px'>2 · Matched</h2><p class='small'>The ticket next to the dispatched load it was "
                "matched to (planned " + escape(str(dispatch["planned_t"])) + " t).</p><div class='wrap'><table class='t'>"
                "<thead><tr><th></th><th>Ticket says</th><th>Dispatch says</th><th></th></tr></thead><tbody>" + rows +
                "</tbody></table></div>")
    elif dispatch:
        disp = ("<h2 style='margin-top:26px'>Dispatch record</h2><div class='wrap'><table class='t'><tbody>" +
                "".join(f"<tr><td>{escape(k.replace('_', ' '))}</td><td>{escape(str(v))}</td></tr>" for k, v in dispatch.items()) +
                "</tbody></table></div>")
    docs = "".join(f"<li>{k} photo <code>{escape(d['file'])}</code> SHA-256 <code>{escape(d['sha256'])}</code></li>"
                   for k, d in e["documents"].items() if d)
    read_section = (f"<h2 style='margin-top:26px'>1 · Read</h2><p class='small'>Text as Azure read it, its confidence, and the value after "
                    f"normalizing (formats, master-data codes, known OCR confusions). Corrected values are highlighted.</p>"
                    f"<div class='grid2'><div>{_read_table(e)}{_scale_table(e)}</div><div class='photos'>{photos}</div></div>") if e["kind"] == "haul" else ""
    n = 3 if disp and e["kind"] == "haul" else 2
    check_section = (f"<h2 style='margin-top:26px'>{n} · Checked</h2><p class='small'>All {len(CHECKS)} checks, in order, with the values compared.</p>"
                     f"<ol class='checks'>{checks}</ol>") if checks else ""
    body = f"""<div class="crumbs"><a href="/">How it works</a> › <a href="/b/{escape(name)}/">{escape(name.capitalize())} batch</a> › {escape(title)}</div>
<h1>{escape(title)} <span class="{cls}-badge">{label}</span></h1>
{verdict}
{read_section}
{disp}
{check_section}
{(f'<h2 style="margin-top:26px">{n + 1} · Decided</h2>' + calc) if calc else ''}
<h2 style="margin-top:26px">{n + 2 if calc else n + 1} · Recorded</h2>
<p class="small">This decision is an entry in the append-only decision log. Rule version <code>{escape(e['rule_version'])}</code> ·
read by <code>{escape(e['engine'])} {escape(e['model_version'])}</code> · outcome codes {', '.join(f'<code>{c}</code>' for c in codes) or 'none'}.</p>
<ul class="small">{docs}</ul>"""
    return page(f"{title} · Ticket Audit", body, names, name)
