"""Run store: documents seen, cached extractions, runs, and the append-only decision log (ADR 4).

Each extraction is committed as soon as it's made, so a run that dies halfway resumes from
the cache and never pays for (or re-reads) a document twice.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ticket_audit.domain.model import Extraction, Field

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    sha256 TEXT PRIMARY KEY, file TEXT NOT NULL, first_run INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS extractions (
    sha256 TEXT NOT NULL, engine TEXT NOT NULL, model_version TEXT NOT NULL,
    kind TEXT NOT NULL, fields TEXT NOT NULL, extracted TEXT NOT NULL,
    PRIMARY KEY (sha256, engine, model_version));
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT NOT NULL, finished TEXT,
    status TEXT NOT NULL, engine TEXT NOT NULL, model_version TEXT NOT NULL, rule_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs,
    subject TEXT NOT NULL, entry_sha256 TEXT NOT NULL, entry TEXT NOT NULL, logged TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS decision_log_no_update BEFORE UPDATE ON decision_log
    BEGIN SELECT RAISE(ABORT, 'decision log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_log_no_delete BEFORE DELETE ON decision_log
    BEGIN SELECT RAISE(ABORT, 'decision log is append-only'); END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def start_run(self, engine: str, model_version: str, rule_version: str) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO runs (started, status, engine, model_version, rule_version) VALUES (?,?,?,?,?)",
                (_now(), "running", engine, model_version, rule_version))
        return cur.lastrowid

    def fail_run(self, run_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET status='failed', finished=? WHERE run_id=?", (_now(), run_id))

    def register(self, sha256: str, file: str, run_id: int) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?)", (sha256, file, run_id))

    def cached(self, sha256: str, file: str, engine: str, model_version: str) -> Extraction | None:
        row = self.db.execute(
            "SELECT kind, fields FROM extractions WHERE sha256=? AND engine=? AND model_version=?",
            (sha256, engine, model_version)).fetchone()
        if row is None:
            return None
        fields = {k: Field(v["value"], v["confidence"]) for k, v in json.loads(row[1]).items()}
        return Extraction(file, sha256, row[0], fields, engine, model_version)

    def save(self, e: Extraction) -> None:
        fields = {k: {"value": f.value, "confidence": f.confidence} for k, f in e.fields.items()}
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?)",
                            (e.sha256, e.engine, e.model_version, e.kind, json.dumps(fields, sort_keys=True), _now()))

    def complete_run(self, run_id: int, entries: list[tuple[str, str, str]]) -> None:
        """Log every decision and mark the run complete in one transaction: all or nothing."""
        now = _now()
        with self.db:
            self.db.executemany(
                "INSERT INTO decision_log (run_id, subject, entry_sha256, entry, logged) VALUES (?,?,?,?,?)",
                [(run_id, subject, digest, entry, now) for subject, digest, entry in entries])
            self.db.execute("UPDATE runs SET status='complete', finished=? WHERE run_id=?", (now, run_id))

    def extraction_count(self, engine: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM extractions WHERE engine=?", (engine,)).fetchone()[0]
