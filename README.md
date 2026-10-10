# Ticket Audit

Reads transportation tickets, matches them to dispatch records and customer rates, and produces invoice-ready lines plus an exception queue with plain-language reasons.

**All data in this repository is synthetic.** Every company, person, ticket and rate is invented. The real ticket formats of any carrier are not public; the layouts here are designed from public descriptions of frac-sand hauling in Western Canada.

Status: work in progress — the synthetic data generator is done; the rule engine is next.

## Run

```bash
uv sync
uv run python -m ticket_audit.synth          # generate both batches into data/generated/
uv run pytest                                # generator realism checks + tests
```

## Synthetic data

Each load produces two phone photos: the driver's **haul ticket** (pre-printed form, filled in by hand, signed by the receiver at the well site) and the pit's **scale ticket** (thermal printout with gross/tare/net in kg). Dispatch, rates and master data sit in `tms.sqlite`, the stand-in for a TMS.

| Batch | Loads | Problems | Read with |
|---|---|---|---|
| `audit` | 30 | every planted problem at least once, ~19 clean | Azure AI Document Intelligence |
| `day` | 300 (one day at "hundreds of tickets" volume) | a realistic share, ~15% of loads | generator truth (no OCR: the free tier covers 500 pages a month) |

Planted problems cover all three sources the comparison uses:

| Code | Source | Problem | Required outcome |
|---|---|---|---|
| P1 | Ticket | Net tonnes on the haul ticket differ from the scale ticket | Exception |
| P2 | Ticket | No receiver signature | Exception |
| P3 | Ticket | Missing AFE / cost code | Exception |
| P4 | Ticket | Same ticket submitted twice | Second copy is an exception |
| P5 | Ticket | Long time on site, standby left blank | Standby added, if a rate is on file |
| P6 | Ticket | Written-over, smudged net weight | Exception |
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
