# Ticket Audit — Brief for every agent working on this system

This file is the binding brief for this repository. It contains no private material and is safe to make public.

## 1. What this is
A **working, deployed mini-system** that automates the ticket-audit process described in Bizi Transport's job posting (application question 2): paper/PDF tickets are read, matched against dispatch records and customer rates, and turned into invoice-ready lines; everything uncertain goes to an exception queue with a plain reason.

**Framing (binding):** this is **not a demo**. Never call it a demo in code, UI, README, commit messages or docs. Call it "the system". The audience rejects basic demos and wants solutions that work in production, so production-grade engineering is the point: tests that prove the claims, failure handling, monitoring, a runbook and recorded decisions.

Honest limit (say it, don't hide it): it runs on **synthetic data**, so it proves the engineering standard, not Bizi's production. "Give me your real tickets and it starts earning in shadow mode."

## 2. Non-negotiables
1. **Synthetic data only.** No real company data, no real customer or company names on tickets. Never ingest the private application folder (research, evidence, résumé, outreach) into this repo or its wiki.
2. **No secrets committed.** Keys in `.env` (gitignored); `.env.example` committed.
3. **AI never makes the approve decision.** AI reads documents (and, read-only, answers questions about decisions). Rules decide.
4. **Fail closed.** Any uncertainty, missing data or dependency failure → exception, never approval.
5. **Never write "savings over your staff".** The money figure is "billing exposure found in this batch".

## 3. Architecture characteristics (top 3 + secondary) and their fitness functions
| # | Characteristic | Meaning here | Fitness function (automated test, must pass) |
|---|---|---|---|
| 1 | Auditability | Every invoice line is traceable and replayable: source document, rule, model version | Every approved line carries full provenance, or the run fails |
| 2 | Data integrity | Nothing wrong ever reaches an invoice; anything uncertain becomes an exception | Every planted error lands in exceptions; zero planted errors approved |
| 3 | Reliability | No ticket lost, none processed twice; a run that dies halfway resumes cleanly | Kill a run mid-batch → rerun → identical output, no duplicates |
| 4 | Modifiability (secondary) | OCR engine, TMS, accounting each behind an interface | Justified by testability (generator-truth engine tests the rules with no OCR) |

**Deliberately not optimized:** scale/throughput (hundreds of tickets/day ≈ one every few minutes: no queues, no Kafka, no microservices) and availability (batch process; downtime means tickets wait, nothing is lost).

## 4. Style
Pipeline (pipes and filters) at the core; interfaces at the edges for every external system; **business decisions are pure, deterministic functions with no I/O.**

```
Inbox ─▶ Intake ─▶ Extract ─▶ Normalize ─▶ Match ─▶ Rate check ─▶ Decide ─┬─▶ Draft invoice lines (CSV → accounting stand-in)
(folder) hash+ID   [engine    units,dates  dispatch  rate sheet   rules,   └─▶ Exception queue + report
                   interface]              [TMS]     tolerance    reasons
                    ├ Azure AI Document Intelligence (F0)        every step appends to ─▶ Decision log (provenance)
                    ├ local OCR (co-brain PaddleOCR-VL, fallback)
                    └ generator truth (tests)
```
Stand-ins, labelled as such in the README: folder = inbox, SQLite = TMS, CSV = draft invoices to accounting.

## 5. Decisions to record as ADRs
1. Extraction engine behind an interface (Azure / local / generator truth). Driver: testability + Azure→local fallback.
2. AI never makes the approve decision; rules are data (a table); reasons are readable; outcome is identical every run.
3. When in doubt, it's an exception: approval needs every check to pass; fallback-key matches (date + unit + customer) are never auto-approved; critical fields (quantity, ticket number) need higher confidence.
4. Append-only decision log with provenance: document hash, engine + model version, rule version, inputs.
5. One process, SQLite, batch; the trigger to revisit, and the production path (storage trigger → containerized job on Azure Container Apps).

## 6. Scope
**In:** synthetic generator (`python -m ticket_audit.synth`): frac-sand loads, each a driver haul ticket + pit scale ticket rendered as phone photos (tilt, shadow, blur, JPEG; scanned PDFs also accepted); dispatch + rates in SQLite. Two batches: **audit** (30 loads, every planted problem, read with real OCR) and **day** (100 loads in one day, ~200 photos, a realistic share of problems, read with real OCR once and cached; freeze the rendering before that run). The problem is the three-way comparison ticket ↔ dispatch ↔ rates; planted problems P1–P11 (codes and required outcomes in `src/ticket_audit/synth/batch.py`): weight mismatch vs scale ticket, missing signature, missing PO/AFE, duplicate, unbilled standby, smudged handwritten weight (billed from the scale ticket when the two agree), ticket without a load, load without a ticket, fallback-key match, no rate, expired rate; the pipeline; report page; `approved.csv` with source references; extraction accuracy vs generator truth (field hit rate); deployment.
**Out (README "production next steps"):** real TMS/accounting integration, owner-operator settlements, Power Automate approvals (diagram only), multi-user auth, training on real layouts.

## 7. The report
- Headline: **Underbilling found $X** (split into *recovered* — auto-applied because every check passed — and *at stake* — waiting in the exception queue) · **Overbilling prevented $Y** (duplicates). Two numbers, never summed.
- Baseline stated in small print: compared with an invoice built from dispatch alone.
- Integrity line: "Planted issues caught: N of N".
- Labelled "synthetic batch" on screen.
- Then: touchless rate, exceptions by type; each exception shows reason, fields, confidence, link to the source document.

## 8. AI beyond extraction (stretch — only after the fitness functions pass)
A question-answering agent over the decision log ("why was T-1042 flagged?"). Read-only. Every answer cites decision-log entries; an answer citing an entry or field that doesn't exist is rejected. Runs locally (gpt-oss-20b via MLX), no API bill.

## 9. Deployment safeguards (public endpoint)
Azure Container Apps, personal Azure free account only (never an employer or client tenant). Access code; preloaded synthetic batches; upload size/page/rate limits; auto-delete uploads; visible "synthetic data only — do not upload real documents" notice; Document Intelligence on F0 tier only; never upgrade to pay-as-you-go; $1 budget alert; one resource group `rg-ticket-audit`.

## 10. Build order and deadline
1. Generator + dispatch/rates → 2. decision engine on generator truth + the three fitness functions → 3. Azure extraction (checkpoint Wed; else local engine) → 4. report, decision log, runbook, ADRs → 5. deploy with safeguards → 6. stretch agent.
**Deadline: Tuesday 2026-10-13.** Ship what works; no "one more thing".

## 11. Definition of done
One command runs everything · fitness functions pass · every planted problem caught with a readable reason · no clean ticket flagged (or explained) · every approved line links to its source · deployed behind access code with safeguards live · runbook covers Azure/OCR/database failure (fails closed) · README: problem, diagram, decisions, run instructions, honest limits, next steps.
