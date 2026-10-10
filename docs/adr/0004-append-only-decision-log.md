# 4. An append-only decision log with provenance

**Status:** accepted

## Context
Every invoice line must be traceable and replayable: which documents, which reading, which rule.

## Decision
Each run logs one entry per decision in the run store (`store.py`): the source documents' SHA-256, every input as read, the dispatch record and rate row used, the reasons, the rule version, and the engine and model version. Database triggers reject `UPDATE` and `DELETE` on the log. Every approved line in `approved.csv` carries the hash of its log entry, both photo hashes, the dispatch number and the rate key.

## Consequences
- The auditability fitness function verifies all of this on every test run: photo hashes match the files, the log entry hashes to the value on the line.
- Entries are written in the same transaction that marks the run complete: a crashed run leaves no half-written decisions.
