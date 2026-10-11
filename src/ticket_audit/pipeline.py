"""Intake -> extract -> normalize -> decide -> outputs. The only module that does I/O in sequence.

Outputs are a deterministic function of the inbox, the TMS and the rule version: re-running a
batch rewrites identical files, so a crashed run is fixed by simply running it again.
"""
import csv
import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from ticket_audit.domain.model import Decision
from ticket_audit.domain.normalize import normalize_haul, normalize_scale
from ticket_audit.domain.rules import RULE_VERSION, BatchResult, decide
from ticket_audit.extract.base import Extractor
from ticket_audit.store import Store
from ticket_audit.tms import load_reference

DOCUMENT_TYPES = {".jpg", ".jpeg", ".png", ".pdf", ".tif", ".tiff"}

APPROVED_COLUMNS = [
    "ticket_no", "date", "customer_code", "dispatch_no", "pit_code", "lease_code", "product", "net_t",
    "per_tonne", "tonnage_amount", "standby_h", "standby_per_h", "standby_amount", "total", "standby_recovered",
    "haul_file", "haul_sha256", "scale_file", "scale_sha256", "rate_key", "rule_version", "engine",
    "model_version", "log_entry_sha256",
]
EXCEPTION_COLUMNS = ["subject", "kind", "ticket_no", "outcome", "reason_codes", "reasons",
                     "amount_at_stake", "log_entry_sha256"]


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    out_dir: Path
    documents: int
    extracted_now: int
    approved: int
    approved_adjusted: int
    exceptions: int
    missing_tickets: int


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def log_entry(d: Decision, engine: str, model_version: str) -> dict:
    """Everything needed to replay a decision: source documents, inputs as read, rule version, outcome."""
    def doc(t):
        return {"file": t.doc.file, "sha256": t.doc.sha256} if t else None

    def inputs(t):
        if t is None:
            return None
        data = asdict(t)
        data.pop("doc")
        return data

    return {
        "subject": d.subject, "kind": d.kind, "outcome": d.outcome, "ticket_no": d.ticket_no,
        "reasons": [asdict(r) for r in d.reasons],
        "rule_version": RULE_VERSION, "engine": engine, "model_version": model_version,
        "documents": {"haul": doc(d.haul), "scale": doc(d.scale)},
        "inputs": {"haul": inputs(d.haul), "scale": inputs(d.scale),
                   "dispatch": asdict(d.dispatch) if d.dispatch else None,
                   "rate": asdict(d.rate) if d.rate else None},
        "line": asdict(d.line) if d.line else None,
        "checks": [asdict(c) for c in d.checks],
    }


def _canonical(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, default=str, separators=(",", ":"))


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _csv(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_outputs(out: Path, result: BatchResult, digests: dict[str, str], engine: str, model_version: str) -> None:
    approved = []
    for d in result.approved:
        line = asdict(d.line)
        line.update({
            "date": d.line.date.isoformat(), "haul_file": d.haul.doc.file, "haul_sha256": d.haul.doc.sha256,
            "scale_file": d.scale.doc.file, "scale_sha256": d.scale.doc.sha256, "rate_key": d.rate.key,
            "rule_version": RULE_VERSION, "engine": engine, "model_version": model_version,
            "log_entry_sha256": digests[d.subject],
        })
        approved.append(line)
    exceptions = [{
        "subject": d.subject, "kind": d.kind, "ticket_no": d.ticket_no or "", "outcome": d.outcome,
        "reason_codes": ";".join(d.reason_codes), "reasons": " | ".join(r.message for r in d.reasons),
        "amount_at_stake": f"{d.line.total:.2f}" if d.line else "", "log_entry_sha256": digests[d.subject],
    } for d in result.exceptions]
    _write_atomic(out / "approved.csv", _csv(APPROVED_COLUMNS, approved))
    _write_atomic(out / "exceptions.csv", _csv(EXCEPTION_COLUMNS, exceptions))


def run_batch(batch_dir: Path, extractor: Extractor, out_dir: Path | None = None) -> RunSummary:
    out = out_dir or batch_dir / "out" / extractor.name
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / "store.sqlite")
    run_id = store.start_run(extractor.name, extractor.model_version, RULE_VERSION)
    try:
        files = sorted(p for p in (batch_dir / "inbox").iterdir() if p.suffix.lower() in DOCUMENT_TYPES)
        extractions, seen, duplicate_files, extracted_now = [], {}, {}, 0
        for path in files:
            digest = sha256_file(path)
            if digest in seen:  # byte-identical resubmission: never read twice
                duplicate_files[path.name] = seen[digest]
                continue
            seen[digest] = path.name
            store.register(digest, path.name, run_id)
            e = store.cached(digest, path.name, extractor.name, extractor.model_version)
            if e is None:
                e = extractor.extract(path, digest)
                store.save(e)
                extracted_now += 1
            extractions.append(e)

        ref = load_reference(batch_dir / "tms.sqlite")
        hauls = [normalize_haul(e, ref) for e in extractions if e.kind == "haul"]
        scales = [normalize_scale(e) for e in extractions if e.kind == "scale"]
        unreadable = [e.file for e in extractions if e.kind not in ("haul", "scale")]
        result = decide(hauls, scales, unreadable, ref, duplicate_files)

        entries, digests = [], {}
        for d in result.decisions:
            text = _canonical(log_entry(d, extractor.name, extractor.model_version))
            digests[d.subject] = hashlib.sha256(text.encode()).hexdigest()
            entries.append((d.subject, digests[d.subject], text))
        store.complete_run(run_id, entries)
        write_outputs(out, result, digests, extractor.name, extractor.model_version)
    except BaseException:
        store.fail_run(run_id)
        raise
    finally:
        store.close()

    return RunSummary(
        run_id, out, len(files), extracted_now,
        sum(d.outcome == "approve" for d in result.decisions),
        sum(d.outcome == "approve_adjusted" for d in result.decisions),
        sum(d.outcome == "exception" for d in result.decisions),
        sum(d.outcome == "missing_ticket" for d in result.decisions),
    )
