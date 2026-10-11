"""The report page: what this batch found, then the exception queue a billing clerk works through.

Built from the decision log of the latest complete run, so every number on the page traces to
logged decisions. Writes out/<engine>/report.html next to approved.csv and exceptions.csv.

    uv run python -m ticket_audit.report data/generated/day --engine azure
"""
import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path

from ticket_audit.domain.rules import CONFIG, REASONS
from ticket_audit.tms import load_reference

ENGINE_NAMES = {"azure": "Azure AI Document Intelligence", "truth": "Generator truth (no OCR)"}
SHOWN_FIELDS = [  # (raw field, label) for the "what was read" panel
    ("ticket_no", "Ticket"), ("dispatch_no", "Load no."), ("date", "Date"), ("unit", "Unit"),
    ("customer", "Customer"), ("po", "PO"), ("afe", "AFE"), ("origin", "Origin"), ("lease", "Lease"),
    ("lsd", "LSD"), ("product", "Product"), ("net_t", "Net (t)"), ("scale_ticket_no", "Scale ticket"),
    ("arrive", "Arrive"), ("depart", "Depart"), ("standby_h", "Standby (h)"),
]


@dataclass
class Summary:
    batch: str
    engine: str
    run_id: int
    finished: str
    rule_version: str
    model_version: str
    days: list[str]
    tickets: int
    approved: int
    adjusted: int
    held: int
    missing: int
    recovered: float
    at_stake_standby: float
    at_stake_missing: float
    overbilling_prevented: float
    on_hold_value: float
    approved_value: float
    reasons: Counter
    queue: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)
    evaluation: dict | None = None
    entries: dict[str, dict] = field(default_factory=dict)  # every decision by subject, with what was read

    @property
    def underbilling(self) -> float:
        return round(self.recovered + self.at_stake_standby + self.at_stake_missing, 2)

    @property
    def touchless(self) -> float:
        return (self.approved + self.adjusted) / self.tickets if self.tickets else 0.0


def _rate_value(ref, d: dict) -> float:
    """Value of a dispatched load with no ticket: planned tonnes x the rate in effect that day."""
    day = date.fromisoformat(d["date"])
    for r in ref.rates:
        if (r.customer_code, r.pit_code, r.lease_code) == (d["customer_code"], d["pit_code"], d["lease_code"]) \
                and r.effective_from <= day and (r.effective_to is None or day <= r.effective_to):
            return round(d["planned_t"] * r.per_tonne, 2)
    return 0.0


def summarize(batch: Path, engine: str) -> Summary:
    out = batch / "out" / engine
    db = sqlite3.connect(out / "store.sqlite")
    run_id, finished, rule_version, model_version = db.execute(
        "SELECT run_id, finished, rule_version, model_version FROM runs WHERE status='complete' "
        "ORDER BY run_id DESC LIMIT 1").fetchone()
    entries = [json.loads(e) for (e,) in db.execute(
        "SELECT entry FROM decision_log WHERE run_id=? ORDER BY id", (run_id,))]
    read = {sha: json.loads(fields) for sha, fields in db.execute(
        "SELECT sha256, fields FROM extractions WHERE engine=? AND model_version=?", (engine, model_version))}
    ref = load_reference(batch / "tms.sqlite")
    manifest = json.loads((batch / "manifest.json").read_text())
    evaluation_file = out / "evaluation.json"

    s = Summary(batch.name, engine, run_id, finished, rule_version, model_version, manifest["days"],
                tickets=0, approved=0, adjusted=0, held=0, missing=0, recovered=0.0, at_stake_standby=0.0,
                at_stake_missing=0.0, overbilling_prevented=0.0, on_hold_value=0.0, approved_value=0.0,
                reasons=Counter(),
                evaluation=json.loads(evaluation_file.read_text()) if evaluation_file.exists() else None)
    for e in entries:
        haul_doc = e["documents"].get("haul")
        e["read"] = read.get(haul_doc["sha256"], {}) if haul_doc else {}
        scale_doc = e["documents"].get("scale")
        e["read_scale"] = read.get(scale_doc["sha256"], {}) if scale_doc else {}
        s.entries[e["subject"]] = e
        line = e["line"]
        codes = [r["code"] for r in e["reasons"]]
        if e["kind"] == "haul":
            s.tickets += 1
        if e["outcome"] in ("approve", "approve_adjusted"):
            s.approved += e["outcome"] == "approve"
            s.adjusted += e["outcome"] == "approve_adjusted"
            s.approved_value += line["total"]
            if line["standby_recovered"]:
                s.recovered += line["standby_amount"]
            s.lines.append(e)
            continue
        s.reasons.update(c for c in codes if c != "STANDBY_RECOVERED")
        amount = 0.0
        if e["outcome"] == "missing_ticket":
            s.missing += 1
            amount = _rate_value(ref, e["inputs"]["dispatch"])
            s.at_stake_missing += amount
        else:
            s.held += e["kind"] == "haul"
            if line:
                amount = line["total"]
                if "DUPLICATE_TICKET" in codes:
                    s.overbilling_prevented += line["total"]
                else:
                    s.on_hold_value += line["total"]
                    if line["standby_recovered"]:
                        s.at_stake_standby += line["standby_amount"]
        e["amount"] = amount
        s.queue.append(e)
    for name in ("recovered", "at_stake_standby", "at_stake_missing", "overbilling_prevented",
                 "on_hold_value", "approved_value"):
        setattr(s, name, round(getattr(s, name), 2))
    return s


# ── Rendering ────────────────────────────────────────────────────────────────
def _money(x: float) -> str:
    return f"${x:,.2f}"


def _photo(batch_rel: str, doc: dict | None, label: str) -> str:
    if not doc:
        return ""
    href = f"{batch_rel}/inbox/{escape(doc['file'])}"
    return (f'<a class="photo" href="{href}" target="_blank" rel="noopener">'
            f'<img src="{href}" alt="{escape(label)} photo {escape(doc["file"])}" loading="lazy">'
            f'<span>{escape(label)} · {escape(doc["file"])}</span></a>')


def _fields_table(e: dict) -> str:
    """What the engine read off the haul ticket, as written, with its OCR confidence."""
    read = e.get("read") or {}
    if not read:
        return ""
    rows = []
    for raw, label in SHOWN_FIELDS:
        f = read.get(raw)
        if f is None:
            rows.append(f"<tr><th>{label}</th><td class='muted'>blank</td><td></td></tr>")
            continue
        c = f["confidence"]
        floor = CONFIG["min_confidence_critical"] if raw in CONFIG["critical_fields"] else CONFIG["min_confidence"]
        cls = "low" if c < floor else ""
        rows.append(f"<tr><th>{label}</th><td>{escape(f['value'])}</td><td class='confcell'>"
                    f"<span class='conf {cls}' title='OCR confidence {c:.2f}'><i style='width:{c * 100:.0f}%'></i></span>"
                    f"<span class='num'>{c:.2f}</span></td></tr>")
    scale = (e["inputs"] or {}).get("scale")
    if scale and scale.get("net_kg") is not None:
        rows.append(f"<tr><th>Scale net</th><td>{scale['net_kg']:,} kg</td><td></td></tr>")
    return f'<table class="fields"><thead><tr><th></th><th class="muted">As read</th><th class="muted">Confidence</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _queue_item(e: dict, batch_rel: str) -> str:
    codes = [r["code"] for r in e["reasons"]]
    title = escape(e["ticket_no"] or e["subject"])
    if e["outcome"] == "missing_ticket":
        d = e["inputs"]["dispatch"]
        title = f"Load {escape(d['dispatch_no'])}"
        sub = f"Unit {escape(d['unit'])} · {escape(d['date'])} · dispatched, no ticket received"
    else:
        sub = escape(e["subject"])
    reasons = "".join(f"<li><b>{escape(REASONS[r['code']])}</b>"
                      f"{escape(r['message'][len(REASONS[r['code']]):])}</li>" for r in e["reasons"])
    tags = "".join(f'<span class="tag {"warn" if c == "STANDBY_RECOVERED" else ""}">{escape(c)}</span>' for c in codes)
    amount = f'<span class="amount">{_money(e["amount"])}</span>' if e["amount"] else '<span class="amount muted">—</span>'
    photos = _photo(batch_rel, e["documents"].get("haul"), "Haul ticket") + \
        _photo(batch_rel, e["documents"].get("scale"), "Scale ticket")
    return f"""
<details class="item">
  <summary><span class="who"><b>{title}</b><small>{sub}</small></span><span class="tags">{tags}</span>{amount}</summary>
  <div class="body">
    <ul class="reasons">{reasons}</ul>
    <div class="evidence">{_fields_table(e)}<div class="photos">{photos}</div></div>
    <p class="prov">Decision log entry · rule {escape(e["rule_version"])} · {escape(e["engine"])} {escape(e["model_version"])}</p>
  </div>
</details>"""


def render(s: Summary, batch_rel: str = "../..") -> str:
    days = s.days[0] if len(s.days) == 1 else f"{s.days[0]} – {s.days[-1]}"
    ev = s.evaluation
    integrity = ""
    if ev:
        o, f = ev["outcomes"], ev["fields"]
        integrity = f"""
    <div class="stat"><span class="k">Planted problems held</span><span class="v">{o['planted_caught']} of {o['planted']}</span>
      <span class="d">Synthetic-batch check against the generator's answer key</span></div>
    <div class="stat"><span class="k">Fields read correctly</span><span class="v">{f['field_accuracy']:.2%}</span>
      <span class="d">{f['fields_right']:,} of {f['fields_read']:,}; wrong and confident: {f['confidently_wrong']}</span></div>"""
    bars = ""
    top = max(s.reasons.values(), default=1)
    for code, n in s.reasons.most_common():
        bars += (f'<li><span class="lbl">{escape(REASONS[code])}</span>'
                 f'<span class="bar"><i style="width:{n / top * 100:.0f}%"></i></span><span class="n">{n}</span></li>')
    queue = "".join(_queue_item(e, batch_rel) for e in sorted(s.queue, key=lambda e: -e["amount"]))
    lines = "".join(
        f"<tr><td>{escape(e['ticket_no'])}</td><td>{escape(e['line']['date'])}</td>"
        f"<td>{escape(e['line']['customer_code'])}</td><td>{escape(e['line']['dispatch_no'])}</td>"
        f"<td class='num'>{e['line']['net_t']:.2f}</td><td class='num'>{e['line']['standby_h']:g}"
        f"{' <span class=tag-s>recovered</span>' if e['line']['standby_recovered'] else ''}</td>"
        f"<td class='num'>{_money(e['line']['total'])}</td>"
        f"<td><a href='{batch_rel}/inbox/{escape(e['documents']['haul']['file'])}' target='_blank' rel='noopener'>haul</a> · "
        f"<a href='{batch_rel}/inbox/{escape(e['documents']['scale']['file'])}' target='_blank' rel='noopener'>scale</a></td></tr>"
        for e in sorted(s.lines, key=lambda e: e["ticket_no"]))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ticket Audit</title>
<style>
:root {{
  --bg:#f6f5f1; --panel:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e2dc;
  --accent:#1f5f8b; --good:#2f7d4f; --warn:#a15c00; --bad:#b3261e; --chip:#eef2f5; --on-warn:#fff;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#141416; --panel:#1d1d20; --ink:#ececee; --muted:#9a9aa1; --line:#2e2e33;
  --accent:#78b3dc; --good:#6cc28f; --warn:#e5a44a; --bad:#f28b82; --chip:#26262b; --on-warn:#1d1d1f; }} }}
:root[data-theme="dark"] {{ --bg:#141416; --panel:#1d1d20; --ink:#ececee; --muted:#9a9aa1; --line:#2e2e33;
  --accent:#78b3dc; --good:#6cc28f; --warn:#e5a44a; --bad:#f28b82; --chip:#26262b; --on-warn:#1d1d1f; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:24px 16px 64px; }}
header {{ display:flex; flex-wrap:wrap; gap:8px 16px; align-items:baseline; justify-content:space-between; }}
h1 {{ font-size:24px; margin:0; letter-spacing:-.01em; }}
h2 {{ font-size:16px; margin:36px 0 12px; }}
.meta {{ color:var(--muted); font-size:13px; }}
.synthetic {{ display:inline-block; background:var(--warn); color:var(--on-warn); font-size:12px; font-weight:600; padding:2px 8px; border-radius:99px; }}
.hero {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:20px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 20px; }}
.card .k {{ color:var(--muted); font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }}
.card .v {{ font-size:34px; font-weight:700; letter-spacing:-.02em; margin:4px 0 6px; font-variant-numeric:tabular-nums; }}
.card .split {{ display:flex; gap:20px; flex-wrap:wrap; font-size:14px; }}
.card .split b {{ font-variant-numeric:tabular-nums; }}
.under .v {{ color:var(--good); }} .over .v {{ color:var(--accent); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-top:12px; }}
.stat {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; display:flex; flex-direction:column; }}
.stat .k {{ color:var(--muted); font-size:13px; }} .stat .v {{ font-size:22px; font-weight:700; font-variant-numeric:tabular-nums; }}
.stat .d {{ color:var(--muted); font-size:12px; }}
.small {{ color:var(--muted); font-size:12px; margin-top:10px; }}
ul.bars {{ list-style:none; padding:0; margin:0; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px 16px; }}
ul.bars li {{ display:grid; grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) 32px; gap:12px; align-items:center; padding:5px 0; font-size:14px; }}
.bar {{ height:8px; background:var(--chip); border-radius:99px; overflow:hidden; }} .bar i {{ display:block; height:100%; background:var(--accent); border-radius:99px; }}
.n {{ text-align:right; font-variant-numeric:tabular-nums; color:var(--muted); }}
details.item {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; margin-bottom:8px; }}
details.item summary {{ list-style:none; cursor:pointer; display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:12px; align-items:center; padding:12px 16px; }}
details.item summary::-webkit-details-marker {{ display:none; }}
details.item[open] summary {{ border-bottom:1px solid var(--line); }}
.who {{ display:flex; flex-direction:column; min-width:0; }} .who small {{ color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.tags {{ display:flex; flex-wrap:wrap; gap:4px; justify-content:flex-end; }}
.tag {{ font:600 11px/1.6 ui-monospace,Menlo,monospace; background:var(--chip); color:var(--bad); padding:1px 6px; border-radius:6px; }}
.tag.warn {{ color:var(--warn); }}
.amount {{ font-weight:700; font-variant-numeric:tabular-nums; min-width:90px; text-align:right; }}
.muted {{ color:var(--muted); font-weight:400; }}
.body {{ padding:12px 16px 16px; }}
ul.reasons {{ margin:0 0 12px; padding-left:18px; }}
.evidence {{ display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,1fr); gap:16px; }}
table.fields {{ border-collapse:collapse; width:100%; font-size:13px; }}
table.fields th {{ text-align:left; color:var(--muted); font-weight:500; padding:3px 8px 3px 0; white-space:nowrap; }}
table.fields td {{ padding:3px 8px 3px 0; overflow-wrap:anywhere; }}
.confcell {{ white-space:nowrap; }}
.conf {{ display:inline-block; width:60px; height:6px; background:var(--chip); border-radius:99px; overflow:hidden; vertical-align:middle; margin-right:6px; }}
.conf i {{ display:block; height:100%; background:var(--good); }} .conf.low i {{ background:var(--bad); }}
.num {{ font-variant-numeric:tabular-nums; }}
.photos {{ display:flex; gap:10px; flex-wrap:wrap; align-content:flex-start; }}
.photo {{ display:flex; flex-direction:column; gap:4px; text-decoration:none; color:var(--muted); font-size:12px; width:calc(50% - 5px); min-width:140px; }}
.photo img {{ width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:8px; border:1px solid var(--line); background:var(--chip); }}
.prov {{ color:var(--muted); font-size:12px; margin:12px 0 0; overflow-wrap:anywhere; }}
.tablewrap {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
table.lines {{ border-collapse:collapse; width:100%; font-size:13px; }}
table.lines th, table.lines td {{ padding:8px 12px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }}
table.lines th {{ color:var(--muted); font-weight:600; }} table.lines td.num {{ text-align:right; }}
.tag-s {{ font-size:11px; color:var(--warn); }}
a {{ color:var(--accent); }}
footer {{ margin-top:40px; color:var(--muted); font-size:13px; }}
@media (max-width:720px) {{
  .hero, .evidence {{ grid-template-columns:1fr; }}
  details.item summary {{ grid-template-columns:minmax(0,1fr) auto; }}
  .tags {{ grid-column:1 / -1; justify-content:flex-start; order:3; }}
  .card .v {{ font-size:28px; }}
}}
</style>
</head>
<body>
<main>
  <header>
    <div><h1>Ticket Audit</h1>
      <div class="meta">Batch <b>{escape(s.batch)}</b> · {escape(days)} · {s.tickets} tickets read by {escape(ENGINE_NAMES.get(s.engine, s.engine))}</div></div>
    <span class="synthetic">Synthetic batch: invented companies, tickets and rates</span>
  </header>

  <section class="hero">
    <div class="card under"><span class="k">Underbilling found</span>
      <div class="v">{_money(s.underbilling)}</div>
      <div class="split"><span>Recovered <b>{_money(s.recovered)}</b></span>
        <span>At stake <b>{_money(s.at_stake_standby + s.at_stake_missing)}</b></span></div></div>
    <div class="card over"><span class="k">Overbilling prevented</span>
      <div class="v">{_money(s.overbilling_prevented)}</div>
      <div class="split"><span>Duplicate submissions held <b>{s.reasons.get('DUPLICATE_TICKET', 0)}</b></span></div></div>
  </section>
  <p class="small"><b>Underbilling</b>, recovered: standby earned on site but left blank on the ticket, added to lines that passed every check.
    At stake: standby earned on held tickets, plus dispatched loads with no ticket (planned tonnes × rate), waiting for a person.
    <b>Overbilling</b>: duplicate submissions held back. The two figures are separate and are not added together. All amounts are synthetic.</p>

  <section class="stats">
    <div class="stat"><span class="k">Touchless</span><span class="v">{s.touchless:.0%}</span>
      <span class="d">{s.approved + s.adjusted} of {s.tickets} tickets approved with no human touch</span></div>
    <div class="stat"><span class="k">Exception queue</span><span class="v">{len(s.queue)}</span>
      <span class="d">{s.held} ticket{'s' if s.held != 1 else ''} held · {s.missing} missing ticket{'s' if s.missing != 1 else ''} · {_money(s.on_hold_value)} on hold</span></div>
    {integrity}
  </section>

  <h2>Why items were held</h2>
  <ul class="bars">{bars or '<li>Nothing held.</li>'}</ul>

  <h2>Exception queue <span class="meta">({len(s.queue)}, largest amount first; open an item for the evidence)</span></h2>
  {queue or '<p class="meta">Nothing to review.</p>'}

  <h2>Invoice-ready lines <span class="meta">({len(s.lines)} · {_money(s.approved_value)})</span></h2>
  <details><summary class="meta" style="cursor:pointer">Show approved lines</summary>
  <div class="tablewrap"><table class="lines"><thead><tr><th>Ticket</th><th>Date</th><th>Customer</th><th>Load</th>
    <th class="num">Tonnes (scale)</th><th class="num">Standby h</th><th class="num">Amount</th><th>Source</th></tr></thead>
    <tbody>{lines}</tbody></table></div></details>

  <footer>
    <p>Rules decide; OCR only reads. A load is approved only when every check passes: haul ticket against scale ticket,
      ticket against dispatch, a rate in effect, signature, AFE and PO, and values read with enough confidence where no other
      record confirms them. Tonnes are billed from the scale ticket.</p>
    <p>Run {s.run_id} · finished {escape(s.finished or '')} · rule version {escape(s.rule_version)} · {escape(s.model_version)}.
      Every line and every exception traces to an append-only decision log entry with the SHA-256 of its source photos.</p>
  </footer>
</main>
</body>
</html>
"""


def write_report(batch: Path, engine: str) -> Path:
    path = batch / "out" / engine / "report.html"
    path.write_text(render(summarize(batch, engine)))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Write the report page for the latest run of a batch.")
    ap.add_argument("batch", type=Path)
    ap.add_argument("--engine", default="truth")
    args = ap.parse_args()
    print(write_report(args.batch, args.engine))


if __name__ == "__main__":
    main()
