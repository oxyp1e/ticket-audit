# Ticket Audit

Reads transportation tickets, matches them to dispatch records and customer rates, and produces invoice-ready lines plus an exception queue with plain-language reasons.

**All data in this repository is synthetic.** Every company, person, ticket and rate is invented. The real ticket formats of any carrier are not public; the layouts here are designed from public descriptions of frac-sand hauling in Western Canada.

Status: work in progress. Done: synthetic data generator, rule engine, the three fitness functions, Azure extraction. Next: report page, deployment.

## Run

```bash
uv sync
uv run python -m ticket_audit.synth          # generate both batches into data/generated/
uv run python -m ticket_audit data/generated/audit   # audit a batch -> out/<engine>/approved.csv, exceptions.csv
uv run python -m ticket_audit data/generated/audit --engine azure   # same, reading the photos with Azure (needs .env)
uv run pytest                                # fitness functions, rules, generator realism checks
```

## How it decides

```
Inbox ─▶ Intake ─▶ Extract ─▶ Normalize ─▶ Match ─▶ Rate check ─▶ Decide ─┬─▶ approved.csv (invoice-ready lines)
(folder) SHA-256   [engine]   dates, units, dispatch  rate sheet   rules   └─▶ exceptions.csv (plain reasons)
         dedupe    cached     names, LSD    [TMS]                      every decision ─▶ append-only decision log
```

- **Rules decide, AI only reads.** The decision engine (`domain/rules.py`) is a pure function: no I/O, same inputs give the same decisions every run. Thresholds and reason texts are data; their hash is the rule version stamped on every decision.
- **When in doubt, it's an exception.** A load is approved only when every check passes: haul ticket ↔ scale ticket (weight, truck, date, product), ticket ↔ dispatch (load number, then fields), rate on file and in effect, signature, AFE and PO, and every value that no other record confirms read with enough confidence (0.90 for money and identity fields, 0.80 otherwise). A match made without a load number is never auto-approved.
- **Tonnes are billed from the scale ticket** (printed, and checked by gross − tare = net). The driver's handwritten weight is a cross-check: if it agrees within 0.05 t its OCR confidence doesn't matter; if it disagrees, the ticket is held. On real OCR, a smudged weight was read 0.01 t off at 0.91 confidence. Billing from the scale ticket keeps the amount right anyway.
- **The one automatic adjustment:** standby earned (time on site beyond the rate's free time) but left blank on the ticket is added to the line, and flagged as recovered.
- **Provenance on every line.** Each approved line carries the SHA-256 of both source photos, the dispatch number, the rate row, the rule version, the extraction engine and model, and the hash of its decision-log entry. The log can't be edited or deleted (database triggers).
- **Safe to re-run.** Every extraction is cached by photo fingerprint and committed as it's made. A run killed halfway resumes from the cache, and re-running a batch rewrites byte-identical outputs.

### Fitness functions (`tests/test_fitness.py`)

| Characteristic | Test |
|---|---|
| Auditability | Every approved line's provenance is complete and verifies: photo hashes match the files, dispatch and rate exist, log entry hash matches |
| Data integrity | Every load gets exactly its required outcome and reasons; nothing planted is approved; nothing clean is flagged |
| Reliability | Kill a run halfway, re-run: byte-identical outputs, no document read twice, no ticket billed twice |

Each test was checked by deliberately breaking the engine (removing the signature check, widening the weight tolerance, dropping a hash, bypassing the cache, auto-approving fallback matches); all five breaks were caught.

## Results on real OCR (Azure AI Document Intelligence, free tier)

Every photo in both batches was read once by Azure; raw responses are cached, so re-running costs nothing.

| Batch | Photos | Decision fields read right | Wrong *and* confident | Planted problems held | Loads that should pass, approved |
|---|---|---|---|---|---|
| audit (30 loads) | 59 | 655 / 658 (99.5%) | 1 | 9 / 9 | 20 / 22 |
| day (100 loads) | 199 | 2,203 / 2,204 (99.95%) | 0 | 12 / 12 | 89 / 89 |

- The one confident misread: a smudged, written-over weight read as 40.48 t (true 40.49) at 0.91 confidence. Billing uses the scale ticket, so the amount is still right.
- The two held loads in the audit batch are both a real misread of one customer's PO (`75186` read as `75786`: a handwritten 1 vs 7). The system holds the ticket instead of guessing.
- Run `uv run python -m ticket_audit.evaluate data/generated/<batch> --engine azure` to reproduce (it compares with the generator's answer key, which the rules never see).

What it took: Azure's own label-value pairing was the weak spot on these forms (it glued a ticket number to the date, missed a signature box, and shifted a whole row by one). Fields are now paired with labels by position on the page; Azure's pairing is a second opinion, and when the two disagree the field goes to a human. Each case is a regression test built from a saved response (`tests/fixtures/azure/`).

## Synthetic data

Each load produces two phone photos: the driver's **haul ticket** (pre-printed form, filled in by hand, signed by the receiver at the well site) and the pit's **scale ticket** (thermal printout with gross/tare/net in kg). Dispatch, rates and master data sit in `tms.sqlite`, the stand-in for a TMS.

| Batch | Loads | Problems | Read with |
|---|---|---|---|
| `audit` | 30 | every planted problem at least once, ~19 clean | Azure AI Document Intelligence |
| `day` | 100 loads in one day (~200 ticket photos) | a realistic share, ~15% of loads | Azure AI Document Intelligence, once; results cached by photo fingerprint |

Both batches together come to about 260 OCR pages, inside the free tier's 500 a month. Development and tests run on generator truth and use no pages.

Planted problems cover all three sources the comparison uses:

| Code | Source | Problem | Required outcome |
|---|---|---|---|
| P1 | Ticket | Net tonnes on the haul ticket differ from the scale ticket | Exception |
| P2 | Ticket | No receiver signature | Exception |
| P3 | Ticket | Missing AFE / cost code | Exception |
| P4 | Ticket | Same ticket submitted twice | Second copy is an exception |
| P5 | Ticket | Long time on site, standby left blank | Standby added, if a rate is on file |
| P6 | Ticket | Written-over, smudged net weight | Billed from the scale ticket, since the two agree |
| P7 | Dispatch | Ticket with no dispatch record | Exception |
| P8 | Dispatch | Dispatched load with no ticket | Flagged as a missing ticket |
| P9 | Dispatch | Load number missing; date + unit + customer match | Matched, never auto-approved |
| P10 | Rates | No rate for the customer and route | Exception |
| P11 | Rates | Ticket dated after the rate expired | Exception |

The generator keeps the answers apart from the inputs: `truth/expected.json` is read only by tests, never by the rules. Photo file names are phone-style (`IMG_4821.jpg`), so only the content links a photo to a load.

### Assumptions (no public source)

- **[ASSUMPTION]** B-train frac-sand loads: gross weight up to 63,500 kg, tare 20.5–23.5 t, net 38–42 t.
- **[ASSUMPTION]** One hour of free time on site before standby is billable; standby written to the quarter hour.
- **[ASSUMPTION]** Per-tonne rates and standby rates are invented figures.
- **[ASSUMPTION]** Error shares in the day batch (about 8% load-level problems plus whole-job rate problems) are chosen, not measured.

Sourced: legal land descriptions follow the Alberta DLS format (AER UWI description) and every generated LSD is validated.

## Fonts

Caveat, Courier Prime and Roboto Condensed, under the SIL Open Font License (`assets/fonts/`).
