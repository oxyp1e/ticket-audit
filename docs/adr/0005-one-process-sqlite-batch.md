# 5. One process, SQLite, run as a batch

**Status:** accepted

## Context
Hundreds of tickets a day is about one every few minutes. A batch that is down for an hour delays tickets; it loses none.

## Decision
One Python process, SQLite for the run store, a folder as the inbox, a SQLite file as the TMS stand-in, CSV files as the hand-off to accounting. No queue, no message broker, no microservices. Reliability comes from idempotence instead: every extraction is cached and committed as it is made, outputs are written atomically, and re-running a batch rewrites byte-identical outputs.

## Consequences
- A 100-load day audits in about a second once read; the OCR free tier (≈ 5 photos a minute) is the only bottleneck.
- A network drop mid-run on the day batch was recovered by re-running: 117 saved responses reused, nothing read twice.

## Revisit when
Volume reaches several thousand tickets a day, or more than one person must work the exception queue at once. Production path: photos land in blob storage, a storage event starts a containerized job (Azure Container Apps job), the run store moves to Azure SQL / Postgres, and approved lines post to the accounting system's API instead of a CSV.
