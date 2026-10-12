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
@font-face { font-family:"Inter"; src:url("/static/Inter.woff2") format("woff2"); font-weight:100 900; font-display:swap; }
:root { --bg:#f3f4f6; --panel:#fff; --ink:#18202b; --muted:#5f6b7a; --line:#e3e6ea; --accent:#1d5f8f; --accent-ink:#fff;
  --good:#23794a; --warn:#965a00; --bad:#b42318; --chip:#eef1f5; --soft:#f7f8fa; --on-warn:#fff;
  --side:#0f1b2a; --side-ink:#c5d0dc; --side-mute:#7f90a4; --side-on:rgba(255,255,255,.10); }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0f1115; --panel:#171a20; --ink:#e8ebef;
  --muted:#99a3af; --line:#2a2f37; --accent:#7cb4df; --accent-ink:#0f1115; --good:#6cc28f; --warn:#e5a44a; --bad:#f28b82;
  --chip:#222730; --soft:#1b1f26; --on-warn:#141414; --side:#0a0d12; --side-on:rgba(255,255,255,.08); } }
:root[data-theme="dark"] { --bg:#0f1115; --panel:#171a20; --ink:#e8ebef; --muted:#99a3af; --line:#2a2f37; --accent:#7cb4df;
  --accent-ink:#0f1115; --good:#6cc28f; --warn:#e5a44a; --bad:#f28b82; --chip:#222730; --soft:#1b1f26; --on-warn:#141414;
  --side:#0a0d12; --side-on:rgba(255,255,255,.08); }
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink); font:14.5px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  font-feature-settings:"cv11","ss01"; }
a { color:var(--accent); }
.app { display:grid; grid-template-columns:248px minmax(0,1fr); min-height:100vh; }
.side { background:var(--side); color:var(--side-ink); position:sticky; top:0; height:100vh; overflow-y:auto; padding:18px 12px; display:flex; flex-direction:column; }
.brand { display:flex; align-items:center; gap:10px; color:#fff; font-weight:700; font-size:15px; text-decoration:none; padding:2px 10px 0; }
.brand svg { flex:none; }
.env { margin:12px 10px 6px; font-size:11.5px; font-weight:600; color:#f5c06a; display:flex; align-items:center; gap:6px; }
.env::before { content:""; width:7px; height:7px; border-radius:50%; background:#f5c06a; }
.side nav { display:flex; flex-direction:column; gap:2px; }
.side nav a { display:flex; align-items:center; gap:10px; padding:7px 10px; border-radius:8px; color:var(--side-ink); text-decoration:none; font-size:14px; white-space:nowrap; }
.side nav a:hover { background:rgba(255,255,255,.05); color:#fff; }
.side nav a.on { background:var(--side-on); color:#fff; font-weight:600; }
.side nav a svg { flex:none; opacity:.85; }
.side .grp { font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:var(--side-mute); margin:18px 10px 6px; display:flex; justify-content:space-between; }
.side .grp span { text-transform:none; letter-spacing:0; font-weight:500; }
.count { margin-left:auto; font-size:12px; font-weight:600; background:rgba(255,255,255,.10); color:#fff; padding:0 7px; border-radius:99px; font-variant-numeric:tabular-nums; }
.count.hold { background:#c2410c; }
.side .foot { margin-top:auto; padding:18px 10px 0; font-size:12px; color:var(--side-mute); line-height:1.7; }
.side .foot code { color:var(--side-ink); }
.side .foot a { color:var(--side-ink); }
.bar { position:sticky; top:0; z-index:4; background:color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line); padding:11px 32px; display:flex; justify-content:space-between; align-items:center; gap:12px; }
.crumbs { font-size:13px; color:var(--muted); } .crumbs a { color:var(--muted); text-decoration:none; } .crumbs a:hover { color:var(--accent); }
.crumbs b { color:var(--ink); font-weight:600; }
.badge-syn { font-size:12px; font-weight:600; color:var(--warn); background:color-mix(in srgb, var(--warn) 12%, transparent); padding:3px 10px; border-radius:99px; white-space:nowrap; }
main { padding:26px 32px 72px; max-width:1200px; }
h1 { font-size:24px; line-height:1.25; margin:0; letter-spacing:-.015em; }
h2 { font-size:18px; margin:0 0 4px; letter-spacing:-.01em; } h3 { font-size:14.5px; margin:18px 0 8px; }
p { margin:0 0 10px; } .lede { font-size:16px; color:var(--muted); max-width:780px; }
.muted { color:var(--muted); } .small { font-size:13px; color:var(--muted); }
.pagehead { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap; margin-bottom:20px; }
.pagehead .sub { color:var(--muted); margin-top:4px; }
.actions { display:flex; gap:8px; flex-wrap:wrap; }
.btn { display:inline-flex; align-items:center; gap:7px; padding:8px 14px; border-radius:8px; font-weight:600; font-size:13.5px; text-decoration:none;
  border:1px solid var(--line); background:var(--panel); color:var(--ink); white-space:nowrap; }
.btn:hover { border-color:var(--accent); } .btn.primary { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.btn.disabled { opacity:.45; pointer-events:none; }
.kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:16px; }
.kpi { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.kpi .k { font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.kpi .v { font-size:28px; font-weight:700; letter-spacing:-.02em; font-variant-numeric:tabular-nums; margin:2px 0; }
.kpi .d { font-size:12.5px; color:var(--muted); }
.kpi.ok .v { color:var(--good); } .kpi.hold .v { color:var(--bad); }
.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; margin-bottom:16px; overflow:hidden; }
.card > header { padding:12px 16px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }
.card > header h2 { font-size:15px; margin:0; } .card > header .small { margin:0; }
.card .body { padding:14px 16px; }
.cols { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { display:inline-flex; gap:6px; align-items:center; padding:5px 11px; border-radius:99px; border:1px solid var(--line); background:var(--panel);
  font-size:13px; text-decoration:none; color:var(--ink); white-space:nowrap; }
.chip span { color:var(--muted); font-variant-numeric:tabular-nums; } .chip:hover { border-color:var(--accent); }
.chip.on { background:var(--ink); color:var(--bg); border-color:var(--ink); } .chip.on span { color:var(--bg); opacity:.7; }
.filters { display:flex; flex-direction:column; gap:10px; padding:12px 16px; border-bottom:1px solid var(--line); background:var(--soft); }
.filters .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; } .filters .chips { flex:1; min-width:0; } .filters .lbl { font-size:12px; font-weight:600; color:var(--muted); width:58px; }
form.search { display:flex; gap:6px; } form.search input { font:inherit; padding:6px 10px; border:1px solid var(--line); border-radius:8px; background:var(--panel); color:var(--ink); width:200px; }
form.search button { font:inherit; font-weight:600; padding:6px 12px; border-radius:8px; border:1px solid var(--line); background:var(--panel); color:var(--ink); cursor:pointer; }
.pill { display:inline-flex; align-items:center; gap:6px; font-size:12.5px; font-weight:600; padding:2px 10px; border-radius:99px; white-space:nowrap; }
.pill::before { content:""; width:7px; height:7px; border-radius:50%; background:currentColor; }
.pill.ok { color:var(--good); background:color-mix(in srgb, var(--good) 12%, transparent); }
.pill.hold { color:var(--bad); background:color-mix(in srgb, var(--bad) 11%, transparent); }
.pill.adj { color:var(--warn); background:color-mix(in srgb, var(--warn) 13%, transparent); }
table.t { border-collapse:collapse; width:100%; font-size:13.5px; }
table.t th, table.t td { text-align:left; padding:9px 14px; border-bottom:1px solid var(--line); vertical-align:top; }
table.t th { font-size:11.5px; color:var(--muted); font-weight:600; text-transform:uppercase; letter-spacing:.05em; background:var(--soft); white-space:nowrap; }
table.t tr:last-child td { border-bottom:0; } table.t tbody tr:hover td { background:var(--soft); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.card table.t { border:0; } .boxed { background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.wrap { overflow-x:auto; }
code, .mono { font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }
.tag { font:600 11px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; background:var(--chip); color:var(--bad); padding:1px 6px; border-radius:6px; white-space:nowrap; }
.tag.adj { color:var(--warn); }
.bars { list-style:none; margin:0; padding:0; } .bars li { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) 28px; gap:12px; align-items:center; padding:6px 0; font-size:13.5px; }
.bars a { text-decoration:none; color:var(--ink); } .bars a:hover { color:var(--accent); }
.bar-track { height:8px; background:var(--chip); border-radius:99px; overflow:hidden; } .bar-track i { display:block; height:100%; background:var(--bad); opacity:.75; border-radius:99px; }
.flow { display:flex; flex-wrap:wrap; gap:8px; align-items:stretch; }
.flow .n { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:118px; flex:1; }
.flow .n b { display:block; font-size:22px; font-variant-numeric:tabular-nums; } .flow .n span { font-size:12.5px; color:var(--muted); }
.flow .n.ok { border-color:var(--good); } .flow .n.hold { border-color:var(--bad); } .flow .arrow { align-self:center; color:var(--muted); }
section.step { display:grid; grid-template-columns:150px minmax(0,1fr); gap:24px; padding:28px 0; border-top:1px solid var(--line); }
section.step > .label { font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--accent); }
section.step > .label span { display:block; font-size:30px; font-weight:800; color:var(--line); letter-spacing:0; }
.quote { border-left:3px solid var(--accent); padding:4px 0 4px 14px; margin:10px 0 14px; font-size:15.5px; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.grid3 { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:12px 0; }
.grid2 { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:12px 0; }
.panel h4 { margin:0 0 6px; font-size:14px; } .panel ul { margin:0; padding-left:18px; font-size:13.5px; }
.synthetic { display:inline-block; background:var(--warn); color:var(--on-warn); font-size:12px; font-weight:600; padding:2px 9px; border-radius:99px; }
svg.diagram { width:100%; height:auto; display:block; }
svg.diagram .box { fill:var(--panel); stroke:var(--line); stroke-width:1.5; }
svg.diagram .box.key { stroke:var(--accent); } svg.diagram .box.hold { stroke:var(--bad); } svg.diagram .box.ok { stroke:var(--good); }
svg.diagram text { fill:var(--ink); font:13px Inter,-apple-system,sans-serif; }
svg.diagram text.sub { fill:var(--muted); font-size:11.5px; } svg.diagram text.lane { font-weight:700; font-size:12px; fill:var(--accent); letter-spacing:.05em; }
svg.diagram line, svg.diagram path { stroke:var(--muted); stroke-width:1.5; fill:none; } svg.diagram .arrowhead { fill:var(--muted); stroke:none; }
.imp { border-left:3px solid var(--line); padding:2px 0 2px 16px; margin:0 0 18px; }
.imp h4 { margin:0 0 4px; font-size:14.5px; } .imp .d { font-size:12px; color:var(--muted); }
.imp dl { display:grid; grid-template-columns:70px minmax(0,1fr); gap:3px 12px; margin:6px 0 0; font-size:13.5px; } .imp dt { color:var(--muted); font-weight:600; } .imp dd { margin:0; }
.checklist { display:flex; flex-wrap:wrap; gap:6px; margin:10px 0; }
.checklist span { font-size:12.5px; padding:3px 9px; border-radius:6px; background:var(--chip); }
.cards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
a.tile { display:block; text-decoration:none; color:inherit; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }
a.tile:hover { border-color:var(--accent); } a.tile b { font-size:16px; }
.detail { display:grid; grid-template-columns:minmax(0,5fr) minmax(0,7fr); gap:20px; align-items:start; }
.viewer { position:sticky; top:66px; display:flex; flex-direction:column; gap:12px; }
.viewer figure { margin:0; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px; }
.viewer img { width:100%; display:block; border-radius:8px; background:var(--chip); }
.viewer figcaption { font-size:12px; color:var(--muted); margin-top:6px; display:flex; justify-content:space-between; gap:8px; }
.summary { display:flex; gap:22px; flex-wrap:wrap; margin-top:10px; font-size:13.5px; color:var(--muted); }
.summary b { color:var(--ink); font-variant-numeric:tabular-nums; }
ol.checks { list-style:none; margin:0; padding:0; }
ol.checks li { display:grid; grid-template-columns:26px minmax(150px,210px) minmax(0,1fr); gap:10px; padding:9px 16px; border-bottom:1px solid var(--line); font-size:13.5px; }
ol.checks li:last-child { border-bottom:0; } ol.checks li.fail { background:color-mix(in srgb, var(--bad) 6%, transparent); }
ol.checks li.adjust { background:color-mix(in srgb, var(--warn) 7%, transparent); }
.st { width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:12px; }
.st.pass { background:color-mix(in srgb, var(--good) 15%, transparent); color:var(--good); }
.st.fail { background:color-mix(in srgb, var(--bad) 15%, transparent); color:var(--bad); }
.st.adjust { background:color-mix(in srgb, var(--warn) 18%, transparent); color:var(--warn); } .st.skip { background:var(--chip); color:var(--muted); }
.conf { display:inline-block; width:52px; height:6px; background:var(--chip); border-radius:99px; overflow:hidden; vertical-align:middle; margin-right:6px; }
.conf i { display:block; height:100%; background:var(--good); } .conf.low i { background:var(--bad); }
.changed { background:color-mix(in srgb, var(--warn) 16%, transparent); border-radius:4px; padding:0 3px; }
.callout { border:1px solid var(--bad); background:color-mix(in srgb, var(--bad) 6%, var(--panel)); border-radius:12px; padding:14px 16px; margin:0 0 16px; }
.callout.ok { border-color:var(--good); background:color-mix(in srgb, var(--good) 6%, var(--panel)); }
.callout ul { margin:6px 0 0; padding-left:18px; } .callout .next { margin-top:4px; font-size:13px; }
.callout .next b { color:var(--ink); }
.calc td.num { width:1%; }
@media (max-width:1100px) { .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:900px) {
  .app { grid-template-columns:minmax(0,1fr); }
  .side { position:static; height:auto; padding:12px 12px 8px; }
  .side .env { margin:8px 10px 6px; }
  .side nav { flex-direction:row; overflow-x:auto; gap:4px; padding-bottom:4px; }
  .side .grp, .side .foot { display:none; }
  .bar { padding:10px 16px; position:static; } main { padding:20px 16px 56px; }
  .detail, .cols { grid-template-columns:minmax(0,1fr); } .viewer { position:static; }
  section.step { grid-template-columns:minmax(0,1fr); gap:8px; }
  section.step > .label span { display:inline; font-size:14px; margin-right:6px; color:var(--accent); }
  .grid3, .grid2, .cards { grid-template-columns:minmax(0,1fr); }
  ol.checks li { grid-template-columns:26px minmax(0,1fr); } ol.checks li .detail-text { grid-column:2; }
  .bars li { grid-template-columns:minmax(0,1fr) 90px 24px; }
  .chip { white-space:normal; } .filters .lbl { width:auto; } form.search input { width:100%; min-width:0; } form.search { flex:1; }
}
@media (max-width:520px) { .kpis { grid-template-columns:minmax(0,1fr); } h1 { font-size:21px; } }
"""

ICONS = {
    "book": '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H16v14H5.5A1.5 1.5 0 0 0 4 18.5v-14Z"/><path d="M4 18.5A1.5 1.5 0 0 1 5.5 17H16"/>',
    "rules": '<path d="M7 5h10M7 10h10M7 15h10"/><path d="M3.5 5h.01M3.5 10h.01M3.5 15h.01"/>',
    "dash": '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="11" y="3" width="6" height="4" rx="1"/><rect x="11" y="9" width="6" height="8" rx="1"/><rect x="3" y="11" width="6" height="6" rx="1"/>',
    "queue": '<path d="M3 11h4l1.5 2.5h3L13 11h4"/><path d="M5 4h10l2 7v5H3v-5l2-7Z"/>',
    "lines": '<path d="M6 3h6l3 3v11H6V3Z"/><path d="M12 3v3h3M8.5 10h4M8.5 13h4"/>',
    "out": '<path d="M8 4H4v12h4M12 7l3 3-3 3M15 10H8"/>',
}


def _icon(name: str) -> str:
    return (f'<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


LOGO = ('<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="7" fill="#2b7bb9"/>'
        '<path d="M7 7h12v12H7z" fill="none" stroke="#fff" stroke-width="1.6" stroke-dasharray="2.2 1.6"/>'
        '<path d="M9.5 13.2l2.3 2.3 4.7-5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def shell(title: str, body: str, ctx: dict, active: str, crumbs: list[tuple[str, str | None]]) -> str:
    def link(href, icon, label, key, extra=""):
        cls = ' class="on"' if key == active else ""
        return f'<a href="{href}"{cls}>{_icon(icon)}<span>{label}</span>{extra}</a>'

    nav = [link("/", "book", "How it works", "home"), link("/rules", "rules", "Rules", "rules")]
    for name, b in ctx["batches"].items():
        s = b["summary"]
        days = s.days[0] if len(s.days) == 1 else f"{s.days[0][5:]} – {s.days[-1][5:]}"
        nav.append(f'<div class="grp">{escape(name.capitalize())} batch <span>{escape(days)}</span></div>')
        nav.append(link(f"/b/{name}/", "dash", "Dashboard", f"{name}:dash"))
        nav.append(link(f"/b/{name}/queue", "queue", "Exception queue", f"{name}:queue",
                        f'<span class="count hold">{len(s.queue)}</span>'))
        nav.append(link(f"/b/{name}/lines", "lines", "Invoice lines", f"{name}:lines",
                        f'<span class="count">{len(s.lines)}</span>'))
    build = ctx.get("build") or {}
    foot = (f'Build <code>{escape(build.get("commit", "local"))}</code> · {build.get("tests", {}).get("passed", "–")} tests passed<br>'
            f'Rules <code>{escape(RULE_VERSION)}</code><br><a href="/logout">Sign out</a>')
    trail = " › ".join(f'<a href="{h}">{escape(t)}</a>' if h else f"<b>{escape(t)}</b>" for t, h in crumbs)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml"><style>{CSS}</style></head>
<body><div class="app"><aside class="side"><a class="brand" href="/">{LOGO}Ticket Audit</a>
<div class="env">Synthetic data · read-only</div><nav>{''.join(nav)}</nav><div class="foot">{foot}</div></aside>
<div><header class="bar"><div class="crumbs">{trail}</div><span class="badge-syn">Synthetic data</span></header>
<main>{body}</main></div></div></body></html>"""


def _money(x: float) -> str:
    return f"${x:,.2f}"


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


def home(ctx: dict) -> str:
    batches, build, startup = ctx["batches"], ctx.get("build"), ctx.get("timings", {})
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
    cards = "".join(f"""<a class="tile" href="/b/{escape(n)}/"><b>{escape(n.capitalize())} batch</b>
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
<div class="pagehead"><div><h1>Automating the ticket audit before invoicing</h1></div>
<div class="actions"><a class="btn primary" href="/b/day/queue">Open the exception queue</a><a class="btn" href="/b/day/">Day batch dashboard</a></div></div>
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
  <p>A load is approved only when every one of {len(CHECKS)} checks passes:</p>
  <div class="checklist">{''.join(f"<span>{escape(name)}</span>" for _, name, _, _ in CHECKS)}</div>
  <p>The rules are data: the <a href="/rules">rule table</a> is generated from the rule code itself, so it can't drift
  from what runs, and its hash is the rule version stamped on every decision (<code>{escape(RULE_VERSION)}</code>).
  Tonnes are billed from the scale ticket. The one automatic change is standby earned but left blank, added and
  flagged. A match to dispatch without a load number is never auto-approved.</p>
  <p class="small">Open any ticket in a batch to see every check with the values it compared.</p>
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
    return shell("How it works · Ticket Audit", body, ctx, "home", [("How it works", None)])




# ── Batch screens ────────────────────────────────────────────────────────────
DISPATCH_CHECKS, RATE_CHECKS = {"dispatch", "dispatch_agree"}, {"rate"}
SOURCE = {code: ("dispatch" if k in DISPATCH_CHECKS else "rates" if k in RATE_CHECKS else "ticket")
          for k, _, _, codes in CHECKS for code in codes}
SOURCE.update({"MISSING_TICKET": "dispatch", "ORPHAN_SCALE_TICKET": "ticket", "UNREADABLE_DOCUMENT": "ticket",
               "DUPLICATE_FILE": "ticket"})


def _label(e: dict) -> str:
    return e["ticket_no"] or (f"Load {e['subject']}" if e["kind"] == "missing_ticket" else e["subject"])


def _href(batch: str, e: dict) -> str:
    return f"/b/{escape(batch)}/t/{quote(e['subject'])}"


def _codes(e: dict) -> list[str]:
    return [r["code"] for r in e["reasons"]]


def _primary(e: dict) -> str:
    codes = _codes(e)
    return next((c for c in codes if c != "STANDBY_RECOVERED"), codes[0] if codes else "")


def _queue_order(s: Summary) -> list[dict]:
    return sorted(s.queue, key=lambda e: (-e["amount"], e["subject"]))


def _lines_order(s: Summary) -> list[dict]:
    return sorted(s.lines, key=lambda e: e["ticket_no"])


def _tags(codes: list[str]) -> str:
    return " ".join(f'<span class="tag{" adj" if c == "STANDBY_RECOVERED" else ""}">{c}</span>' for c in codes)


def _flow(s: Summary) -> str:
    hauls = [e for e in s.entries.values() if e["kind"] == "haul"]
    photos = {d["file"] for e in s.entries.values() for d in e["documents"].values() if d}
    by_number = sum(1 for e in hauls if any(c["key"] == "dispatch" and c["status"] == "pass" for c in e["checks"]))
    nodes = [(len(photos), "photos received", ""), (s.tickets, "haul tickets read", ""),
             (by_number, "matched to dispatch by load number", ""), (s.approved + s.adjusted, "passed every check", "ok"),
             (s.held, "tickets held for a person", "hold"), (s.missing, "dispatched, no ticket", "hold")]
    parts = []
    for i, (n, label, cls) in enumerate(nodes):
        parts.append(f'<div class="n {cls}"><b>{n}</b><span>{escape(label)}</span></div>')
        if i < 3:
            parts.append('<span class="arrow">→</span>')
    return f'<div class="flow">{"".join(parts)}</div>'


def dashboard_page(name: str, ctx: dict) -> str:
    s: Summary = ctx["batches"][name]["summary"]
    days = s.days[0] if len(s.days) == 1 else f"{s.days[0]} – {s.days[-1]}"
    counts: dict[str, int] = {}
    for e in s.queue:
        for c in set(_codes(e)) - {"STANDBY_RECOVERED"}:
            counts[c] = counts.get(c, 0) + 1
    top = max(counts.values(), default=1)
    bars = "".join(f'<li><a href="queue?reason={c}">{escape(REASONS[c])}</a><span class="bar-track"><i style="width:{n / top * 100:.0f}%"></i></span>'
                   f'<span class="num">{n}</span></li>' for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def listed(pred):
        items = [e for e in s.entries.values() if pred(e)]
        return ", ".join(f'<a href="{_href(name, e)}">{escape(e["ticket_no"] or e["subject"])}</a>' for e in items) or "none"

    money = f"""<table class="t"><tbody>
<tr><td><b>Standby recovered</b><div class="small">Earned on site, left blank; added to lines that passed every check · {listed(lambda e: e["outcome"] == "approve_adjusted")}</div></td><td class="num">{_money(s.recovered)}</td></tr>
<tr><td><b>Standby at stake</b><div class="small">Earned on held tickets · {listed(lambda e: e["outcome"] == "exception" and e["line"] and e["line"]["standby_recovered"] and "DUPLICATE_TICKET" not in _codes(e))}</div></td><td class="num">{_money(s.at_stake_standby)}</td></tr>
<tr><td><b>Loads with no ticket</b><div class="small">Dispatched, no ticket came back; planned tonnes × rate · {listed(lambda e: e["outcome"] == "missing_ticket")}</div></td><td class="num">{_money(s.at_stake_missing)}</td></tr>
<tr><td><b>Duplicates held back</b><div class="small">Overbilling prevented · {listed(lambda e: "DUPLICATE_TICKET" in _codes(e))}</div></td><td class="num">{_money(s.overbilling_prevented)}</td></tr>
</tbody></table>"""
    ev, quality = s.evaluation, ""
    if ev:
        f, o = ev["fields"], ev["outcomes"]
        quality = f"""<div class="card"><header><h2>Checked against the answer key</h2><span class="small">synthetic batches only; the rules never see it</span></header>
<div class="body"><div class="summary" style="margin:0"><span><b>{o['planted_caught']} of {o['planted']}</b> planted problems held</span>
<span><b>{o['clean_approved']} of {o['clean']}</b> loads that should pass, approved</span>
<span><b>{f['fields_right']:,} of {f['fields_read']:,}</b> fields read correctly</span><span><b>{f['confidently_wrong']}</b> wrong with high confidence</span></div></div></div>"""
    body = f"""<div class="pagehead"><div><h1>{escape(name.capitalize())} batch</h1>
<div class="sub">{s.tickets} tickets · {escape(days)} · read by Azure AI Document Intelligence · {len(CHECKS)} checks per ticket</div></div>
<div class="actions"><a class="btn primary" href="queue">{_icon("queue")}Review {len(s.queue)} exceptions</a><a class="btn" href="lines">{_icon("lines")}Invoice lines</a></div></div>
<div class="kpis">
  <div class="kpi"><div class="k">Tickets audited</div><div class="v">{s.tickets}</div><div class="d">{len({d["file"] for e in s.entries.values() for d in e["documents"].values() if d})} photos · every ticket traceable</div></div>
  <div class="kpi ok"><div class="k">No human touch</div><div class="v">{s.touchless:.0%}</div><div class="d">{s.approved + s.adjusted} tickets passed every check</div></div>
  <div class="kpi hold"><div class="k">Exception queue</div><div class="v">{len(s.queue)}</div><div class="d">{s.held} held · {s.missing} missing · {_money(s.on_hold_value)} on hold</div></div>
  <div class="kpi"><div class="k">Ready to invoice</div><div class="v">{_money(s.approved_value).split('.')[0]}</div><div class="d">{len(s.lines)} lines · tonnes billed from the scale ticket</div></div>
</div>
<div class="card"><header><h2>What happened to the tickets</h2></header><div class="body">{_flow(s)}</div></div>
<div class="cols">
  <div class="card"><header><h2>Why items were held</h2><a class="small" href="queue">Open the queue →</a></header><div class="body"><ul class="bars">{bars or '<li>Nothing held.</li>'}</ul></div></div>
  <div class="card"><header><h2>What the checks found</h2><span class="small">synthetic amounts</span></header>{money}
    <div class="body small" style="border-top:1px solid var(--line)">Underbilling and overbilling are separate and never added together.</div></div>
</div>
{quality}"""
    return shell(f"{name.capitalize()} batch · Ticket Audit", body, ctx, f"{name}:dash",
                 [("How it works", "/"), (f"{name.capitalize()} batch", None)])


def queue_page(name: str, ctx: dict, reason: str = "", source: str = "", q: str = "") -> str:
    s: Summary = ctx["batches"][name]["summary"]
    items = _queue_order(s)
    by_source = {k: [e for e in items if SOURCE.get(_primary(e)) == k] for k in ("ticket", "dispatch", "rates")}
    reasons: dict[str, int] = {}
    for e in items:
        reasons[_primary(e)] = reasons.get(_primary(e), 0) + 1
    shown = items
    if source in by_source:
        shown = by_source[source]
    if reason in REASONS:
        shown = [e for e in shown if reason in _codes(e)]
    if q:
        shown = [e for e in shown if q.strip().upper() in (e["ticket_no"] or e["subject"]).upper()]

    def chip(label, href, n, on):
        return f'<a class="chip{" on" if on else ""}" href="{href}">{escape(label)} <span>{n}</span></a>'

    src_chips = chip("All", "queue", len(items), not (source or reason or q)) + "".join(
        chip(k.capitalize(), f"queue?source={k}", len(v), source == k) for k, v in by_source.items() if v)
    reason_chips = "".join(chip(REASONS[c], f"queue?reason={c}", n, reason == c)
                           for c, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))
    rows = ""
    for e in shown:
        status = ('<span class="pill hold">Missing ticket</span>' if e["outcome"] == "missing_ticket"
                  else '<span class="pill hold">Held</span>')
        sub = e["subject"] if e["kind"] != "missing_ticket" else f"unit {e['inputs']['dispatch']['unit']} · {e['inputs']['dispatch']['date']}"
        rows += (f'<tr><td>{status}</td><td><a href="{_href(name, e)}"><b>{escape(_label(e))}</b></a><div class="small">{escape(sub)}</div></td>'
                 f'<td>{_tags(_codes(e))}<div class="small">{escape(e["reasons"][0]["message"])}</div></td>'
                 f'<td>{escape(ACTIONS.get(_primary(e), ""))}</td><td class="num">{_money(e["amount"]) if e["amount"] else "—"}</td>'
                 f'<td class="num"><a class="btn" href="{_href(name, e)}">Review</a></td></tr>')
    body = f"""<div class="pagehead"><div><h1>Exception queue</h1>
<div class="sub">{len(items)} items for {s.tickets} tickets · largest amount first · each says what failed and what to do</div></div></div>
<div class="card"><div class="filters">
  <div class="row"><span class="lbl">Source</span><div class="chips">{src_chips}</div></div>
  <div class="row"><span class="lbl">Reason</span><div class="chips">{reason_chips}</div></div>
  <div class="row"><span class="lbl">Find</span><form class="search" method="get" action="queue"><input name="q" value="{escape(q)}" placeholder="Ticket or load number" aria-label="Ticket or load number"><button type="submit">Search</button></form></div>
</div>
<div class="wrap"><table class="t"><thead><tr><th>Status</th><th>Ticket</th><th>Why it's held</th><th>Next step</th><th class="num">Amount</th><th></th></tr></thead>
<tbody>{rows or '<tr><td colspan="6" class="muted">No items match.</td></tr>'}</tbody></table></div></div>"""
    return shell(f"Exception queue · {name.capitalize()} batch", body, ctx, f"{name}:queue",
                 [("How it works", "/"), (f"{name.capitalize()} batch", f"/b/{name}/"), ("Exception queue", None)])


def lines_page(name: str, ctx: dict) -> str:
    s: Summary = ctx["batches"][name]["summary"]
    rows = "".join(
        f"<tr><td><span class='pill {'adj' if e['line']['standby_recovered'] else 'ok'}'>{'Standby added' if e['line']['standby_recovered'] else 'Approved'}</span></td>"
        f"<td><a href='{_href(name, e)}'><b>{escape(e['ticket_no'])}</b></a></td><td>{escape(e['line']['date'])}</td>"
        f"<td>{escape(e['line']['customer_code'])}</td><td>{escape(e['line']['dispatch_no'])}</td>"
        f"<td class='num'>{e['line']['net_t']:.2f}</td><td class='num'>{_money(e['line']['per_tonne'])}</td>"
        f"<td class='num'>{e['line']['standby_h']:g}</td><td class='num'><b>{_money(e['line']['total'])}</b></td></tr>"
        for e in _lines_order(s))
    body = f"""<div class="pagehead"><div><h1>Invoice lines</h1>
<div class="sub">{len(s.lines)} lines · {_money(s.approved_value)} · every line carries the SHA-256 of both photos, the dispatch number,
the rate row, the rule version and its decision-log entry</div></div>
<div class="actions"><a class="btn" href="approved.csv">{_icon("lines")}approved.csv</a><a class="btn" href="exceptions.csv">{_icon("lines")}exceptions.csv</a></div></div>
<div class="card"><div class="wrap"><table class="t"><thead><tr><th>Status</th><th>Ticket</th><th>Date</th><th>Customer</th><th>Load</th>
<th class="num">Tonnes (scale)</th><th class="num">Rate /t</th><th class="num">Standby h</th><th class="num">Amount</th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return shell(f"Invoice lines · {name.capitalize()} batch", body, ctx, f"{name}:lines",
                 [("How it works", "/"), (f"{name.capitalize()} batch", f"/b/{name}/"), ("Invoice lines", None)])


def rules_page(ctx: dict) -> str:
    thresholds = [("Weight tolerance", f"{CONFIG['weight_tolerance_t']} t", "driver's net vs the scale's net"),
                  ("Scale balance", f"{CONFIG['scale_balance_tolerance_kg']} kg", "gross − tare vs printed net"),
                  ("Standby tolerance", f"{CONFIG['standby_tolerance_h']} h", "written standby vs time on site"),
                  ("Confidence, money and identity fields", f"≥ {CONFIG['min_confidence_critical']:.2f}",
                   ", ".join(CONFIG["critical_fields"])),
                  ("Confidence, other fields", f"≥ {CONFIG['min_confidence']:.2f}",
                   "unless an independent record confirms the value exactly")]
    trows = "".join(f"<tr><td><b>{escape(a)}</b></td><td class='num mono'>{escape(b)}</td><td>{escape(c)}</td></tr>" for a, b, c in thresholds)
    body = f"""<div class="pagehead"><div><h1>Rules</h1>
<div class="sub">Generated from the rule code; its hash is the rule version on every decision: <code>{escape(RULE_VERSION)}</code></div></div></div>
<div class="card"><header><h2>Checks, in the order they run</h2><span class="small">a load is approved only when every check passes</span></header>
<div class="wrap"><table class="t"><thead><tr><th>Check</th><th>Requires</th><th>Reasons it can give</th></tr></thead><tbody>{_rule_rows()}</tbody></table></div></div>
<div class="card"><header><h2>Thresholds</h2><span class="small">data, not code: changing one changes the rule version</span></header>
<div class="wrap"><table class="t"><tbody>{trows}</tbody></table></div></div>
<p class="small">Tonnes are billed from the scale ticket. The one automatic change is standby earned but left blank, added and
flagged. A match to dispatch without a load number is never auto-approved. AI reads the photos; it never decides.</p>"""
    return shell("Rules · Ticket Audit", body, ctx, "rules", [("How it works", "/"), ("Rules", None)])


# ── Ticket screen ────────────────────────────────────────────────────────────
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
            rows.append(f"<tr><td>{label}</td><td class='muted'>blank</td><td></td><td class='muted mono'>{escape(norm_txt) or '—'}</td></tr>")
            continue
        c = f["confidence"]
        floor = CONFIG["min_confidence_critical"] if raw in CONFIG["critical_fields"] else CONFIG["min_confidence"]
        bar = (f"<span class='conf{' low' if c < floor else ''}'><i style='width:{c * 100:.0f}%'></i></span>"
               f"<span class='mono'>{c:.2f}</span>")
        fixed = raw == "lsd" and norm_txt and norm_txt.replace("-", "") != f["value"].replace("-", "").replace(" ", "")
        norm_cell = (f"<span class='changed' title='corrected while normalizing'>{escape(norm_txt)}</span>" if fixed
                     else escape(norm_txt or "—"))
        rows.append(f"<tr><td>{label}</td><td>{escape(f['value'])}</td><td style='white-space:nowrap'>{bar}</td><td class='mono'>{norm_cell}</td></tr>")
    return ("<div class='wrap'><table class='t'><thead><tr><th>Field</th><th>As read</th><th>OCR confidence</th><th>Normalized</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _scale_table(e: dict) -> str:
    read = e.get("read_scale") or {}
    if not read:
        return ""
    rows = "".join(f"<tr><td>{label}</td><td>{escape(read[k]['value'])}</td><td class='mono'>{read[k]['confidence']:.2f}</td></tr>"
                   for k, label in SCALE_FIELDS if k in read)
    return ("<div class='wrap'><table class='t'><thead><tr><th>Field</th><th>As read</th><th>Confidence</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


def trace_page(name: str, e: dict, ctx: dict) -> str:
    s: Summary = ctx["batches"][name]["summary"]
    label, cls = OUTCOME[e["outcome"]]
    pill = {"approve": "ok", "approve_adjusted": "adj"}.get(e["outcome"], "hold")
    title = _label(e)
    in_queue = e["outcome"] not in ("approve", "approve_adjusted")
    order = _queue_order(s) if in_queue else _lines_order(s)
    idx = next((i for i, x in enumerate(order) if x["subject"] == e["subject"]), 0)
    prev_e = order[idx - 1] if idx > 0 else None
    next_e = order[idx + 1] if idx + 1 < len(order) else None
    where = ("Exception", "queue", "Exception queue") if in_queue else ("Line", "lines", "Invoice lines")
    nav = (f'<a class="btn{" disabled" if not prev_e else ""}" href="{_href(name, prev_e) if prev_e else "#"}">← Previous</a>'
           f'<a class="btn primary{" disabled" if not next_e else ""}" href="{_href(name, next_e) if next_e else "#"}">Next →</a>')
    checks = e.get("checks", [])
    passed = sum(c["status"] in ("pass", "adjust") for c in checks)
    line = e.get("line")
    summary = [f"<span>{where[0]} <b>{idx + 1} of {len(order)}</b></span>"]
    if checks:
        summary.append(f"<span><b>{passed} of {len(checks)}</b> checks passed</span>")
    if line:
        summary.append(f"<span>Amount <b>{_money(line['total'])}</b></span>")
    if e["documents"].get("haul"):
        summary.append(f"<span>Photo <b>{escape(e['documents']['haul']['file'])}</b></span>")

    if in_queue:
        items = "".join(f"<li><b>{escape(REASONS[r['code']])}</b>{escape(r['message'][len(REASONS[r['code']]):])}"
                        f"<div class='next'><b>Next step:</b> {escape(ACTIONS.get(r['code'], ''))}</div></li>" for r in e["reasons"])
        verdict = f"<div class='callout'><b>Held for review</b><ul>{items}</ul></div>"
    else:
        extra = ", and standby earned on site was added to the line" if e["outcome"] == "approve_adjusted" else ""
        verdict = f"<div class='callout ok'><b>Approved.</b> Every check passed{extra}. The line goes on the next invoice.</div>"

    figs = "".join(f"<figure><a href='../inbox/{escape(d['file'])}' target='_blank' rel='noopener'><img src='../inbox/{escape(d['file'])}' "
                   f"alt='{k} ticket photo'></a><figcaption><span>{k.capitalize()} ticket</span><span class='mono'>{escape(d['file'])}</span></figcaption></figure>"
                   for k, d in e["documents"].items() if d)
    check_rows = "".join(f"<li class='{c['status']}'><span class='st {STATUS[c['status']][1]}' title='{STATUS[c['status']][2]}'>{STATUS[c['status']][0]}</span>"
                         f"<b>{escape(c['name'])}</b><span class='detail-text'>{escape(c['detail'])}</span></li>" for c in checks)
    sections = []
    if checks:
        sections.append(f"<div class='card'><header><h2>Checks</h2><span class='small'>{passed} of {len(checks)} passed, in the order they ran</span></header>"
                        f"<ol class='checks'>{check_rows}</ol></div>")
    if e["kind"] == "haul":
        sections.append(f"<div class='card'><header><h2>Read from the haul ticket</h2><span class='small'>as read · OCR confidence · normalized (corrections highlighted)</span></header>{_read_table(e)}</div>")
        if e.get("read_scale"):
            sections.append(f"<div class='card'><header><h2>Read from the scale ticket</h2></header>{_scale_table(e)}</div>")
    dispatch = (e["inputs"] or {}).get("dispatch")
    haul = (e["inputs"] or {}).get("haul") or {}
    if dispatch and e["kind"] == "haul":
        pairs = [("Load number", haul.get("dispatch_no") or "not written", dispatch["dispatch_no"]),
                 ("Date", haul.get("date"), dispatch["date"]), ("Unit", haul.get("unit"), dispatch["unit"]),
                 ("Customer", haul.get("customer_code"), dispatch["customer_code"]),
                 ("Pit", haul.get("pit_code"), dispatch["pit_code"]), ("Lease", haul.get("lease_code"), dispatch["lease_code"]),
                 ("Product", (e.get("read") or {}).get("product", {}).get("value") or haul.get("product"), dispatch["product"])]
        rows = "".join(f"<tr><td>{a}</td><td class='mono'>{escape(str(t))}</td><td class='mono'>{escape(str(d))}</td>"
                       f"<td>{'<span class=\"st pass\">✓</span>' if t is not None and key(str(t)) == key(str(d)) else '<span class=\"st fail\">✗</span>'}</td></tr>"
                       for a, t, d in pairs)
        sections.append(f"<div class='card'><header><h2>Matched to dispatch</h2><span class='small'>planned {escape(str(dispatch['planned_t']))} t</span></header>"
                        f"<div class='wrap'><table class='t'><thead><tr><th></th><th>Ticket says</th><th>Dispatch says</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>")
    elif dispatch:
        rows = "".join(f"<tr><td>{escape(k.replace('_', ' '))}</td><td>{escape(str(v))}</td></tr>" for k, v in dispatch.items())
        sections.append(f"<div class='card'><header><h2>Dispatch record</h2></header><div class='wrap'><table class='t'><tbody>{rows}</tbody></table></div></div>")
    if line:
        sections.append(f"""<div class='card'><header><h2>Invoice line</h2><span class='small'>{'billed on the next invoice' if not in_queue else 'not billed: waits in the exception queue'}</span></header>
<table class="t calc"><tbody>
<tr><td>Tonnes (from the scale ticket)</td><td class="num">{line['net_t']:.2f} t × {_money(line['per_tonne'])}/t</td><td class="num">{_money(line['tonnage_amount'])}</td></tr>
<tr><td>Standby{' <span class="pill adj">recovered</span>' if line['standby_recovered'] else ''}</td><td class="num">{line['standby_h']:g} h × {_money(line['standby_per_h'])}/h</td><td class="num">{_money(line['standby_amount'])}</td></tr>
<tr><td><b>Line total</b></td><td></td><td class="num"><b>{_money(line['total'])}</b></td></tr></tbody></table></div>""")
    docs = "".join(f"<li>{k} photo <code>{escape(d['file'])}</code><br>SHA-256 <code>{escape(d['sha256'])}</code></li>"
                   for k, d in e["documents"].items() if d)
    sections.append(f"""<div class='card'><header><h2>Audit trail</h2><span class='small'>append-only decision log</span></header><div class='body small'>
Rule version <code>{escape(e['rule_version'])}</code> · read by <code>{escape(e['engine'])} {escape(e['model_version'])}</code> ·
outcome codes {', '.join(f'<code>{c}</code>' for c in _codes(e)) or 'none'}<ul style="margin:8px 0 0;padding-left:18px">{docs}</ul></div></div>""")

    left = f"<div class='viewer'>{figs}</div>" if figs else ""
    layout = (f"<div class='detail'>{left}<div>{verdict}{''.join(sections)}</div></div>" if left
              else f"{verdict}{''.join(sections)}")
    body = f"""<div class="pagehead"><div><h1>{escape(title)} <span class="pill {pill}" style="vertical-align:middle">{label}</span></h1>
<div class="summary">{''.join(summary)}</div></div><div class="actions">{nav}</div></div>
{layout}"""
    return shell(f"{title} · Ticket Audit", body, ctx, f"{name}:{where[1]}",
                 [("How it works", "/"), (f"{name.capitalize()} batch", f"/b/{name}/"), (where[2], f"/b/{name}/{where[1]}"), (title, None)])
