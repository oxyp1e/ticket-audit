"""The three fitness functions (CLAUDE.md §3). If any of these fail, the system is not fit to run.

1. Auditability:   every approved line carries full, verifiable provenance.
2. Data integrity: every planted problem lands in exceptions; nothing planted is approved; nothing clean is flagged.
3. Reliability:    a run killed mid-batch, then re-run, gives identical output with nothing read twice.
"""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from ticket_audit.domain.rules import RULE_VERSION
from ticket_audit.extract.truth import TruthExtractor
from ticket_audit.pipeline import run_batch, sha256_file
from ticket_audit.synth.__main__ import BATCHES, write_batch


def make_batch(root: Path, name: str) -> Path:
    """Generate a batch with placeholder files instead of photos (rendering is tested separately)."""
    write_batch(BATCHES[name], seed=7, out=root, render=False)
    batch = root / name
    for d in json.loads((batch / "truth" / "documents.json").read_text())["documents"]:
        (batch / "inbox" / d["file"]).write_text(json.dumps({"file": d["file"], **d["fields"]}))
    return batch


def read_csv(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module", params=list(BATCHES))
def audited(request, tmp_path_factory):
    batch = make_batch(tmp_path_factory.mktemp(request.param), request.param)
    summary = run_batch(batch, TruthExtractor(batch / "truth" / "documents.json"))
    return batch, summary


# ── 1. Auditability ──────────────────────────────────────────────────────────
def test_every_approved_line_has_verifiable_provenance(audited):
    batch, s = audited
    lines = read_csv(s.out_dir / "approved.csv")
    assert lines, "nothing approved: the check would pass vacuously"

    tms = sqlite3.connect(batch / "tms.sqlite")
    dispatch = {r[0] for r in tms.execute("SELECT dispatch_no FROM dispatch")}
    rates = {f"{c}/{p}/{l}@{ef}" for c, p, l, ef in
             tms.execute("SELECT customer_code, pit_code, lease_code, effective_from FROM rates")}
    log = sqlite3.connect(s.out_dir / "store.sqlite")
    entries = dict(log.execute("SELECT entry_sha256, entry FROM decision_log WHERE run_id=?", (s.run_id,)))

    for line in lines:
        assert all(line[c] != "" for c in line), f"blank provenance in {line['ticket_no']}"
        assert sha256_file(batch / "inbox" / line["haul_file"]) == line["haul_sha256"]
        assert sha256_file(batch / "inbox" / line["scale_file"]) == line["scale_sha256"]
        assert line["dispatch_no"] in dispatch
        assert line["rate_key"] in rates
        assert line["rule_version"] == RULE_VERSION
        entry = entries[line["log_entry_sha256"]]
        assert hashlib.sha256(entry.encode()).hexdigest() == line["log_entry_sha256"]
        assert json.loads(entry)["documents"]["haul"]["sha256"] == line["haul_sha256"]


def test_decision_log_is_append_only(audited):
    _, s = audited
    log = sqlite3.connect(s.out_dir / "store.sqlite")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        log.execute("UPDATE decision_log SET entry='{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        log.execute("DELETE FROM decision_log")


# ── 2. Data integrity ────────────────────────────────────────────────────────
def test_every_load_gets_exactly_the_outcome_it_should(audited):
    batch, s = audited
    expected = json.loads((batch / "truth" / "expected.json").read_text())
    approved = {r["haul_file"]: r for r in read_csv(s.out_dir / "approved.csv")}
    exceptions = {r["subject"]: r for r in read_csv(s.out_dir / "exceptions.csv")}
    duplicate_files = {d["file"] for d in expected["duplicates"]}
    accounted = set()

    for load in expected["loads"]:
        hauls = [f for f in load["files"]["haul"]]
        accounted |= set(hauls)
        if load["outcome"] == "missing_ticket":
            row = exceptions[load["dispatch_no"]]
            assert row["reason_codes"] == "MISSING_TICKET"
            accounted.add(load["dispatch_no"])
            continue
        if load["planted"] == "P4":
            # One copy is billed; the other is held as a duplicate. Which one depends on submission order.
            outcomes = sorted("approved" if f in approved else exceptions[f]["reason_codes"] for f in hauls)
            assert outcomes == ["DUPLICATE_TICKET", "approved"], load["load_id"]
            continue
        (haul,) = [f for f in hauls if f not in duplicate_files]
        if load["outcome"] in ("approve", "approve_adjusted"):
            assert haul in approved, f"{load['load_id']} ({load['planted'] or 'clean'}) was not approved: " \
                                     f"{exceptions.get(haul, {}).get('reasons')}"
            assert (approved[haul]["standby_recovered"] == "True") == (load["outcome"] == "approve_adjusted")
        else:
            assert haul not in approved, f"planted {load['planted']} on {load['load_id']} was approved"
            assert exceptions[haul]["reason_codes"].split(";") == load["reasons"], load["load_id"]

    # Nothing else was flagged: no orphan scale tickets, unreadable documents or stray missing tickets.
    assert set(exceptions) - accounted == set()


def test_planted_issues_caught_n_of_n(audited):
    batch, s = audited
    expected = json.loads((batch / "truth" / "expected.json").read_text())
    planted = [l for l in expected["loads"] if l["outcome"] in ("exception", "missing_ticket")]
    flagged = {r["subject"] for r in read_csv(s.out_dir / "exceptions.csv")}
    caught = [l for l in planted if (set(l["files"]["haul"]) | {l["dispatch_no"]}) & flagged]
    assert len(caught) == len(planted) > 0


# ── 3. Reliability ───────────────────────────────────────────────────────────
class CrashingExtractor:
    """Reads normally, then dies after `limit` documents, like a process killed mid-batch."""

    def __init__(self, inner, limit: int):
        self.inner, self.limit, self.calls = inner, limit, 0
        self.name, self.model_version = inner.name, inner.model_version

    def extract(self, path, sha256):
        if self.calls >= self.limit:
            raise KeyboardInterrupt("killed mid-batch")
        self.calls += 1
        return self.inner.extract(path, sha256)


@pytest.mark.parametrize("name", list(BATCHES))
def test_killed_run_resumes_with_identical_output(name, tmp_path):
    clean = make_batch(tmp_path / "clean", name)
    crashed = make_batch(tmp_path / "crashed", name)
    truth = lambda b: TruthExtractor(b / "truth" / "documents.json")
    n_docs = len(list((crashed / "inbox").iterdir()))

    reference = run_batch(clean, truth(clean))

    with pytest.raises(KeyboardInterrupt):
        run_batch(crashed, CrashingExtractor(truth(crashed), limit=n_docs // 2))
    resumed = run_batch(crashed, truth(crashed))
    again = run_batch(crashed, truth(crashed))

    for out in ("approved.csv", "exceptions.csv"):
        assert (resumed.out_dir / out).read_bytes() == (reference.out_dir / out).read_bytes()
        assert (again.out_dir / out).read_bytes() == (reference.out_dir / out).read_bytes()

    assert resumed.extracted_now == n_docs - n_docs // 2  # the rest came from the cache
    assert again.extracted_now == 0                       # nothing read twice

    store = sqlite3.connect(crashed / "out" / "truth" / "store.sqlite")
    assert store.execute("SELECT COUNT(*) FROM extractions").fetchone()[0] == n_docs
    assert [r[0] for r in store.execute("SELECT status FROM runs ORDER BY run_id")] == \
           ["failed", "complete", "complete"]
    tickets = [r["ticket_no"] for r in read_csv(again.out_dir / "approved.csv")]
    assert len(tickets) == len(set(tickets)), "a ticket was billed twice"


def test_every_ticket_decision_shows_every_check(audited):
    """The trace: each haul decision lists all checks; failed checks and blocking reasons agree."""
    from ticket_audit.domain.rules import ADJUSTMENTS, CHECKS
    batch, s = audited
    log = sqlite3.connect(s.out_dir / "store.sqlite")
    for (raw,) in log.execute("SELECT entry FROM decision_log WHERE run_id=?", (s.run_id,)):
        e = json.loads(raw)
        if e["kind"] != "haul":
            continue
        assert [c["key"] for c in e["checks"]] == [k for k, *_ in CHECKS]
        failed = {c["key"] for c in e["checks"] if c["status"] == "fail"}
        blocking = {r["code"] for r in e["reasons"] if r["code"] not in ADJUSTMENTS}
        owners = {k for k, _, _, codes in CHECKS if set(codes) & blocking}
        assert failed == owners, e["subject"]
        if e["outcome"] in ("approve", "approve_adjusted"):
            assert all(c["status"] in ("pass", "adjust") for c in e["checks"]), e["subject"]
