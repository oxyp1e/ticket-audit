"""Generate synthetic batches.

    uv run python -m ticket_audit.synth                 # both batches, rendered
    uv run python -m ticket_audit.synth audit --no-render

Layout of data/generated/<batch>/:
    inbox/            ticket photos (the inbox stand-in)
    tms.sqlite        dispatch, rates and master data (the TMS stand-in)
    truth/documents.json  what each photo says: generator-truth extraction engine only
    truth/expected.json   planted problems and required outcomes: tests only
    manifest.json
"""
import argparse
import hashlib
import json
import random
import shutil
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ticket_audit.synth.batch import EXPECTED, Batch, make_batch
from ticket_audit.synth.render import render_job
from ticket_audit.synth.world import CARRIER, PLANNED_T, build_world

GENERATOR_VERSION = "0.1.0"
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "data" / "generated"


@dataclass(frozen=True)
class BatchSpec:
    name: str
    days: list[date]
    trucks: int
    loads: int
    mode: str


BATCHES = {
    # Every planted problem at least once; read with real OCR.
    "audit": BatchSpec("audit", [date(2026, 9, 28) + timedelta(days=i) for i in range(5)], 8, 30, "audit"),
    # One full day (~200 ticket photos), all read with real OCR once and cached: fits the free tier.
    "day": BatchSpec("day", [date(2026, 10, 1)], 45, 100, "volume"),
}


def build(spec: BatchSpec, seed: int) -> Batch:
    world = build_world(random.Random(f"{seed}:world"), spec.trucks)
    return make_batch(spec.name, seed, world, spec.days, spec.loads, spec.mode)


def write_tms(batch: Batch, path: Path) -> None:
    w = batch.world
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE customers (code TEXT PRIMARY KEY, name TEXT NOT NULL, po TEXT NOT NULL);
        CREATE TABLE customer_aliases (alias TEXT PRIMARY KEY, customer_code TEXT NOT NULL REFERENCES customers);
        CREATE TABLE pits (code TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE leases (code TEXT PRIMARY KEY, customer_code TEXT NOT NULL REFERENCES customers,
                             name TEXT NOT NULL, lsd TEXT NOT NULL, afe TEXT NOT NULL);
        CREATE TABLE trucks (unit TEXT PRIMARY KEY, trailer TEXT NOT NULL, driver TEXT NOT NULL);
        CREATE TABLE dispatch (dispatch_no TEXT PRIMARY KEY, date TEXT NOT NULL, unit TEXT NOT NULL,
                               trailer TEXT NOT NULL, driver TEXT NOT NULL,
                               customer_code TEXT NOT NULL REFERENCES customers,
                               pit_code TEXT NOT NULL REFERENCES pits, lease_code TEXT NOT NULL REFERENCES leases,
                               product TEXT NOT NULL, planned_t REAL NOT NULL);
        CREATE TABLE rates (customer_code TEXT NOT NULL, pit_code TEXT NOT NULL, lease_code TEXT NOT NULL,
                            per_tonne REAL NOT NULL, standby_per_h REAL NOT NULL, free_time_h REAL NOT NULL,
                            effective_from TEXT NOT NULL, effective_to TEXT);
    """)
    db.executemany("INSERT INTO customers VALUES (?,?,?)", [(c.code, c.name, c.po) for c in w.customers.values()])
    db.executemany("INSERT INTO customer_aliases VALUES (?,?)",
                   [(a, c.code) for c in w.customers.values() for a in (c.name, *c.aliases)])
    db.executemany("INSERT INTO pits VALUES (?,?)", [(p.code, p.name) for p in w.pits.values()])
    db.executemany("INSERT INTO leases VALUES (?,?,?,?,?)",
                   [(l.code, l.customer, l.name, l.lsd, l.afe) for l in w.leases.values()])
    db.executemany("INSERT INTO trucks VALUES (?,?,?)", [(t.unit, t.trailer, t.driver) for t in w.trucks])
    db.executemany("INSERT INTO dispatch VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (ld.dispatch_no, ld.day.isoformat(), ld.truck.unit, ld.truck.trailer, ld.truck.driver,
         ld.customer, ld.lane.pit, ld.lane.lease, ld.product, PLANNED_T)
        for ld in batch.loads if ld.planted != "P7"  # P7: the load never made it into dispatch
    ])
    db.executemany("INSERT INTO rates VALUES (?,?,?,?,?,?,?,?)", [
        (r.customer, r.pit, r.lease, r.per_tonne, r.standby_per_h, r.free_time_h,
         r.effective_from.isoformat(), r.effective_to.isoformat() if r.effective_to else None)
        for r in w.rates
    ])
    db.commit()
    db.close()


def truth(batch: Batch) -> tuple[dict, dict]:
    documents = {"documents": [
        {"file": d.file, "kind": d.kind, "fields": d.fields, "illegible": d.illegible} for d in batch.documents
    ]}
    files: dict[str, dict] = {}
    for d in batch.documents:
        slot = files.setdefault(d.load_id, {"haul": [], "scale": []})
        slot[d.kind].append(d.file)
    loads = []
    for ld in batch.loads:
        outcome, reasons = EXPECTED[ld.planted]
        loads.append({
            "load_id": ld.load_id, "dispatch_no": ld.dispatch_no, "ticket_no": ld.ticket_no,
            "planted": ld.planted, "outcome": outcome, "reasons": reasons,
            "files": files.get(ld.load_id, {"haul": [], "scale": []}),
            "net_kg": ld.net_kg, "on_site_h": round(ld.on_site_h, 2), "standby_h": ld.standby_h,
        })
    return documents, {"loads": loads, "duplicates": batch.duplicates}


def write_batch(spec: BatchSpec, seed: int, out: Path, render: bool) -> dict:
    batch = build(spec, seed)
    root = out / spec.name
    if root.exists():
        shutil.rmtree(root)
    (root / "inbox").mkdir(parents=True)
    (root / "truth").mkdir()
    write_tms(batch, root / "tms.sqlite")
    documents, expected = truth(batch)
    (root / "truth" / "documents.json").write_text(json.dumps(documents, indent=1))
    (root / "truth" / "expected.json").write_text(json.dumps(expected, indent=1))
    if render:
        jobs = [(d.kind, d.fields, d.illegible, f"{seed}:{spec.name}:{d.file}", root / "inbox" / d.file)
                for d in batch.documents]
        with ProcessPoolExecutor() as pool:
            list(pool.map(render_job, jobs, chunksize=8))
    planted: dict[str, int] = {}
    for ld in batch.loads:
        planted[ld.planted or "clean"] = planted.get(ld.planted or "clean", 0) + 1
    digest = hashlib.sha256(json.dumps([documents, expected], sort_keys=True).encode()).hexdigest()
    manifest = {
        "batch": spec.name, "seed": seed, "generator_version": GENERATOR_VERSION, "carrier": CARRIER,
        "synthetic": True, "days": [d.isoformat() for d in spec.days], "loads": len(batch.loads),
        "documents": len(batch.documents), "planted": dict(sorted(planted.items())), "truth_sha256": digest,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic ticket batches.")
    ap.add_argument("batches", nargs="*", default=list(BATCHES), choices=list(BATCHES))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-render", action="store_true", help="skip the photos (fast; truth and TMS only)")
    args = ap.parse_args()
    for name in args.batches:
        m = write_batch(BATCHES[name], args.seed, args.out, render=not args.no_render)
        print(f"{m['batch']}: {m['loads']} loads, {m['documents']} documents, planted {m['planted']}")


if __name__ == "__main__":
    main()
