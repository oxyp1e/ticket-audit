# 3. When in doubt, it's an exception

**Status:** accepted (amended after the first real OCR runs)

## Context
The goal is fewer tickets for people to check, never a wrong invoice. Ticket problems come from three sources: the ticket, dispatch, and the rate sheet.

## Decision
A load is approved only when every check passes:
- haul ticket ↔ scale ticket: weight within 0.05 t, same truck, date and product; scale gross − tare = net
- ticket ↔ dispatch: exact load-number match, then field agreement. A match on date + truck + customer without a load number is **never** auto-approved
- a rate on file and in effect on the ticket date
- receiver signature, AFE and PO present and matching master data
- confidence: money and identity fields (ticket number, weights) need ≥ 0.90; other fields ≥ 0.80, **unless an independent record confirms the value exactly** (lease land description, a known customer, dispatch date and truck, a balanced scale ticket)

The only automatic change is standby: time on site beyond the rate's free time, left blank by the driver, is added and flagged as recovered.

## Why the confidence rule was amended
On the first Azure run, handwriting scored 0.66–0.86 on fields that were read correctly; a flat floor held most clean tickets. A value that exactly matches an independent record is stronger evidence than OCR confidence. Fields no rule uses (driver name, signature text) aren't checked.

## Consequences
On real OCR the day batch held 12 of 12 planted problems and approved 89 of 89 loads that should pass; the audit batch held 9 of 9 and approved 20 of 22 (the two held were a real PO misread, 1 read as 7).
