# Ticket Audit

A working system for one problem: transportation tickets arrive by the hundred, and before invoicing someone compares each one against dispatch and the customer's rates. This system reads the haul and scale tickets, does that comparison with explicit rules, bills what is right, and holds everything uncertain for a person with a plain reason and a next step.

**All data here is synthetic.** Every company, person, ticket and rate is invented; the ticket layouts are designed from public descriptions of frac-sand hauling in Western Canada, not from any carrier's real forms.

**Live:** https://ticket-audit.ashydesert-36a868a4.canadacentral.azurecontainerapps.io (access code on request). The site walks through the same steps as this README, and every ticket in both batches can be opened to see what was read, every check with the values it compared, and the decision.

This README follows the build: problem → process mapping → architecture → development → testing → deployment → improvement.

## 1. Problem

> "…receives hundreds of paper/PDF tickets every day and staff manually compare those tickets against dispatch information and customer rates before invoicing…"

The hard part isn't reading a ticket; it's the **three-way comparison**, where errors come from three places:

| Source | What goes wrong |
|---|---|
| The ticket | net weight differs from the scale ticket · no receiver signature · no AFE / cost code · standby earned but not written · the same ticket sent twice · an unreadable value |
| Dispatch | a ticket for a load dispatch never recorded · a dispatched load whose ticket never came back · no load number on the ticket |
| The rate sheet | no rate for this customer and route · the rate expired before the ticket date |

Each is planted in the synthetic batches (P1–P11 below), so the system is checked against a known answer.

## 2. Process mapping

Today, a person does every check on every ticket. With the system, the same checks run on every ticket the same way, and the person works only the exception queue: in the day batch, 12 items for 100 tickets, each saying what failed and what to do. The individual steps of today's process are an assumption from the posting's wording; mapping the real process with the billing team comes first in production.

## 3. Architecture

```
Inbox ─▶ Intake ─▶ Read ─▶ Normalize ─▶ Match ─▶ Rate check ─▶ Decide ─┬─▶ approved.csv (invoice-ready lines)
(folder) SHA-256  [engine]  dates, names,  dispatch  rate sheet   pure    └─▶ exception queue (reasons + next step)
         dedupe   cached    LSD            [TMS]                  rules    every step ─▶ append-only decision log
```

**AI reads; rules decide.** Reading a photo is the only probabilistic step and sits behind an engine interface (Azure AI Document Intelligence, a local engine, or generator truth for tests). Decisions are a pure function with no I/O: the same inputs give the same decisions on every run.

| Characteristic | Means here | Fitness function (automated, `tests/test_fitness.py`) |
|---|---|---|
| Auditability | every invoice line traceable and replayable | every approved line's photo hashes, dispatch, rate and decision-log entry verify |
| Data integrity | nothing wrong reaches an invoice; anything uncertain is held | every load gets exactly its required outcome; nothing planted is approved; nothing clean is flagged |
| Reliability | no ticket lost or processed twice, even through a crash | a run killed halfway, re-run, gives byte-identical output; nothing read twice |

Deliberately not optimized: throughput (hundreds a day is one every few minutes) and availability (a batch that is down an hour delays tickets, loses none).

Decisions, each with its reasoning and evidence:

1. [The OCR engine sits behind an interface](docs/adr/0001-extraction-behind-an-interface.md)
2. [AI never makes the approve decision](docs/adr/0002-ai-never-approves.md)
3. [When in doubt, it's an exception](docs/adr/0003-when-in-doubt-exception.md)
4. [An append-only decision log with provenance](docs/adr/0004-append-only-decision-log.md)
5. [One process, SQLite, run as a batch](docs/adr/0005-one-process-sqlite-batch.md)
6. [Read fields by position; Azure's key-value pairing is a second opinion](docs/adr/0006-position-based-field-pairing.md)
7. [Bill tonnes from the scale ticket](docs/adr/0007-bill-from-the-scale-ticket.md)
8. [The deployed system is read-only and holds no OCR key](docs/adr/0008-deployment-read-only.md)

## 4. Development: the rules

A load is approved only when all 14 checks pass (`CHECKS` in [`domain/rules.py`](src/ticket_audit/domain/rules.py); the site's rule table is generated from it):

ticket read completely and resolved against master data · not already submitted · scale ticket found · scale ticket adds up (gross − tare = net) · driver's weight within 0.05 t of the scale · scale ticket is this load · signed by the receiver · AFE matches the lease · PO matches the customer · matched to dispatch by load number · agrees with dispatch · exactly one rate in effect · standby consistent with time on site · read with enough confidence (0.90 for money and identity fields; 0.80 for others unless another record confirms the value exactly).

- Tonnes are billed from the scale ticket; the handwritten weight is a cross-check.
- The one automatic change: standby earned on site but left blank is added and flagged as recovered.
- A match to dispatch without a load number is never auto-approved.
- Every decision records every check, passed or failed, with the values it compared, plus the SHA-256 of its photos, the rule version (a hash of the rule table) and the OCR model. The decision log can't be edited or deleted.

## 5. Testing

- **Fitness functions** for the three characteristics, on both batches.
- **Deliberate breaks:** the build applies five known bugs one at a time (signature check removed, weight tolerance widened, fallback match auto-approved, a photo hash dropped, the cache bypassed) and fails if the tests don't catch each one ([`scripts/build_info.py`](scripts/build_info.py)). The results are shown on the live site for the exact build it runs.
- **Real OCR** on every synthetic photo, compared with the generator's answer key (which only the evaluation reads, never the rules):

| Batch | Photos | Fields read right | Wrong *and* confident | Planted problems held | Loads that should pass, approved |
|---|---|---|---|---|---|
| audit (30 loads, a week) | 59 | 655 / 658 | 1 | 9 / 9 | 20 / 22 |
| day (100 loads, one day) | 199 | 2,203 / 2,204 | 0 | 12 / 12 | 89 / 89 |

The confident misread is a smudged weight (40.48 t for 40.49) that is billed correctly from the scale ticket. The two held loads in the audit batch are one real PO misread (a handwritten 1 read as 7), held correctly. Synthetic tickets prove the engineering, not accuracy on real tickets; that needs a pilot (section 8).

## 6. Deployment

Azure Container Apps (consumption, scale to zero), free tiers only, $1 budget alert. At startup the container audits both batches from the saved Azure responses with a page budget of zero: it holds no OCR key and can't call Azure. Read-only, access code, rate-limited sign-in, strict content security policy. [Runbook](docs/runbook.md) for OCR, network, budget, storage and deployment failures; all fail closed.

## 7. Improvement

What broke while building it, what changed, and the measured effect, all on this system's own runs ([`improvements.py`](src/ticket_audit/improvements.py), shown on the site). For example:

- Azure's key-value pairing glued a ticket number to the date and shifted a row of boxes: fields are now read by position, with Azure's pairing as a second opinion (audit batch 12 → 17 approved, every planted problem still held).
- A first fix for day-batch parsing gaps made things worse (81 → 41 of 89 approved); a structural rule replaced it (→ 89 of 89).
- The network dropped after 117 of 199 photos: the re-run reused every saved response and read only the rest.

## 8. Limits and next step

- Assumed, not sourced: B-train weights (gross ≤ 63,500 kg, net 38–42 t), one hour of free time, the rates, the error shares. Sourced: land descriptions follow the Alberta DLS format and every one is validated.
- Stand-ins: a folder for the inbox, SQLite for the TMS, CSV for accounting. Not built: owner-operator settlements, multi-user review, accounting integration.
- **Next step: a shadow-mode pilot.** Real tickets and the rate sheet's structure; fit the field reader to the real forms; run alongside billing for two weeks without invoicing anything, comparing decisions with the team's daily; go live only on agreed numbers.

## Run it

```bash
uv sync
uv run python -m ticket_audit.synth                         # generate both batches into data/generated/
uv run python -m ticket_audit data/generated/day            # audit with generator truth (no OCR, no cost)
uv run python -m ticket_audit data/generated/day --engine azure --max-pages 200   # read the photos with Azure (.env)
uv run python -m ticket_audit.evaluate data/generated/day --engine azure          # compare with the answer key
uv run pytest                                               # 76 tests, including the fitness functions
uv run uvicorn ticket_audit.web:app                         # the site (needs ACCESS_CODE, SESSION_SECRET)
deploy/deploy.sh                                            # build (tests run in the build), push, deploy
```

### Synthetic batches and planted problems

Each load produces two phone photos: the driver's haul ticket (pre-printed form, filled in by hand, signed by the receiver) and the pit's scale ticket (thermal printout, kg). Photo names are phone-style (`IMG_4821.jpg`), so only the content links a photo to a load.

| Code | Source | Planted problem | Required outcome |
|---|---|---|---|
| P1 | Ticket | Net weight differs from the scale ticket | Held |
| P2 | Ticket | No receiver signature | Held |
| P3 | Ticket | Missing AFE / cost code | Held |
| P4 | Ticket | Same ticket submitted twice | Second copy held |
| P5 | Ticket | Long time on site, standby left blank | Standby added |
| P6 | Ticket | Written-over, smudged net weight | Billed from the scale ticket |
| P7 | Dispatch | Ticket with no dispatch record | Held |
| P8 | Dispatch | Dispatched load with no ticket | Flagged as missing |
| P9 | Dispatch | No load number; date, truck and customer match | Held for confirmation |
| P10 | Rates | No rate for the customer and route | Held |
| P11 | Rates | Ticket dated after the rate expired | Held |

Fonts: Caveat, Courier Prime and Roboto Condensed, SIL Open Font License (`assets/fonts/`).
