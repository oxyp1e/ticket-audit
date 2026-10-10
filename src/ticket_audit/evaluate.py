"""Compare a run with the generator's answer key: how well the engine read, and whether the
decisions were right. Reads truth/, so it is an evaluation tool, never part of the pipeline.

    uv run python -m ticket_audit.evaluate data/generated/audit --engine azure
"""
import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from ticket_audit.domain.normalize import key, parse_number
from ticket_audit.domain.rules import CONFIG

# Fields the rules use; the rest (driver, trailer, signature text) only need to be present.
DECISION_FIELDS = {
    "haul": ["ticket_no", "dispatch_no", "date", "unit", "customer", "po", "afe", "origin", "scale_ticket_no",
             "lease", "lsd", "product", "net_t", "arrive", "depart", "standby_h"],
    "scale": ["scale_ticket_no", "date", "unit", "product", "gross_kg", "tare_kg", "net_kg"],
}
NUMERIC = {"net_t", "gross_kg", "tare_kg", "net_kg", "standby_h"}


def _same(name: str, got: str, want: str) -> bool:
    if name in NUMERIC:
        return parse_number(got) == parse_number(want)
    if name == "lsd":
        from ticket_audit.domain.normalize import normalize_lsd
        return normalize_lsd(got) == want
    return key(got) == key(want)


def field_accuracy(batch: Path, engine: str) -> dict:
    truth = {d["file"]: d for d in json.loads((batch / "truth" / "documents.json").read_text())["documents"]}
    db = sqlite3.connect(batch / "out" / engine / "store.sqlite")
    files = dict(db.execute("SELECT sha256, file FROM documents"))
    version = db.execute("SELECT model_version FROM runs WHERE status='complete' ORDER BY run_id DESC").fetchone()[0]
    stats = defaultdict(lambda: {"read": 0, "right": 0, "missed": 0, "confidently_wrong": 0})
    kind_right = 0
    rows = db.execute("SELECT sha256, kind, fields FROM extractions WHERE model_version=?", (version,)).fetchall()
    for sha, kind, raw in rows:
        t = truth[files[sha]]
        kind_right += kind == t["kind"]
        got = json.loads(raw)
        for name in DECISION_FIELDS[t["kind"]]:
            want = t["fields"].get(name, "")
            if not want:
                continue
            s = stats[f"{t['kind']}.{name}"]
            s["read"] += 1
            if name not in got:
                s["missed"] += 1
            elif _same(name, got[name]["value"], want):
                s["right"] += 1
            else:
                critical = name in CONFIG["critical_fields"]
                floor = CONFIG["min_confidence_critical"] if critical else CONFIG["min_confidence"]
                if got[name]["confidence"] >= floor:
                    s["confidently_wrong"] += 1
    total = sum(s["read"] for s in stats.values())
    right = sum(s["right"] for s in stats.values())
    return {"documents": len(rows), "kind_correct": kind_right, "fields_read": total, "fields_right": right,
            "field_accuracy": round(right / total, 4) if total else None,
            "confidently_wrong": sum(s["confidently_wrong"] for s in stats.values()),
            "by_field": dict(sorted(stats.items()))}


def outcomes(batch: Path, engine: str) -> dict:
    expected = json.loads((batch / "truth" / "expected.json").read_text())
    out = batch / "out" / engine
    approved = {r["haul_file"]: r for r in csv.DictReader((out / "approved.csv").open())}
    exceptions = {r["subject"]: r for r in csv.DictReader((out / "exceptions.csv").open())}
    dup_files = {d["file"] for d in expected["duplicates"]}
    result = {"planted": 0, "planted_caught": 0, "planted_missed": [], "clean": 0, "clean_approved": 0,
              "clean_held": [], "standby_recovered": 0}
    for load in expected["loads"]:
        hauls = [f for f in load["files"]["haul"] if f not in dup_files]
        haul = hauls[0] if hauls else None
        if load["planted"] == "P4":
            # Either copy may be billed, depending on submission order; exactly one must be held as a duplicate.
            both = load["files"]["haul"]
            billed = [f for f in both if f in approved]
            held = [f for f in both if "DUPLICATE_TICKET" in exceptions.get(f, {}).get("reason_codes", "")]
            result["clean"] += 1
            result["planted"] += 1
            if len(billed) == 1:
                result["clean_approved"] += 1
            else:
                result["clean_held"].append({"load": load["load_id"], "planted": "P4", "file": both[0],
                                             "reasons": exceptions.get(both[0], {}).get("reasons", "")})
            if len(held) == 1:
                result["planted_caught"] += 1
            else:
                result["planted_missed"].append({"load": load["load_id"], "planted": "P4"})
            continue
        if load["planted"] in (None, "P5"):  # these must be approved (P5 with standby added)
            result["clean"] += 1
            if haul in approved:
                result["clean_approved"] += 1
                result["standby_recovered"] += approved[haul]["standby_recovered"] == "True"
            else:
                row = exceptions.get(haul, {})
                result["clean_held"].append({"load": load["load_id"], "planted": load["planted"], "file": haul,
                                             "reasons": row.get("reasons", "not in output")})
            continue
        result["planted"] += 1
        subject = load["dispatch_no"] if load["planted"] == "P8" else haul
        if subject in exceptions:
            result["planted_caught"] += 1
        else:
            result["planted_missed"].append({"load": load["load_id"], "planted": load["planted"], "file": subject})
    result["touchless_rate"] = round(len(approved) / max(1, len(approved) + sum(
        1 for r in exceptions.values() if r["kind"] == "haul")), 4)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate a run against the generator's answer key.")
    ap.add_argument("batch", type=Path)
    ap.add_argument("--engine", default="azure")
    args = ap.parse_args()
    acc, res = field_accuracy(args.batch, args.engine), outcomes(args.batch, args.engine)
    (args.batch / "out" / args.engine / "evaluation.json").write_text(json.dumps({"fields": acc, "outcomes": res}, indent=1))
    print(f"{args.batch.name} / {args.engine}")
    print(f"  documents classified correctly: {acc['kind_correct']}/{acc['documents']}")
    print(f"  decision fields read correctly: {acc['fields_right']}/{acc['fields_read']} ({acc['field_accuracy']:.1%}); "
          f"confidently wrong: {acc['confidently_wrong']}")
    for name, s in acc["by_field"].items():
        if s["right"] < s["read"]:
            print(f"    {name:24} {s['right']}/{s['read']}  missed {s['missed']}  confidently wrong {s['confidently_wrong']}")
    print(f"  planted problems caught: {res['planted_caught']}/{res['planted']}  missed: {res['planted_missed'] or 'none'}")
    print(f"  loads that should pass: {res['clean_approved']}/{res['clean']} approved "
          f"(standby recovered {res['standby_recovered']}); touchless rate {res['touchless_rate']:.0%}")
    for h in res["clean_held"]:
        print(f"    held {h['load']} ({h['planted'] or 'clean'}) {h['file']}: {h['reasons'][:140]}")


if __name__ == "__main__":
    main()
