# 7. Bill tonnes from the scale ticket

**Status:** accepted

## Context
Each load has two weights: the driver's handwritten net on the haul ticket and the scale's printed gross/tare/net. On real OCR, a smudged, written-over handwritten weight was read as 40.48 t (true 40.49) at 0.91 confidence: wrong, and confident enough to pass a 0.90 floor. The same floor held clean tickets whose handwriting scored 0.86 while matching the scale exactly.

## Decision
Invoice lines bill the scale ticket's net weight: it is printed, and checked by gross − tare = net. The handwritten weight is a cross-check: within 0.05 t of the scale, its OCR confidence doesn't matter; outside it, the ticket is held as a weight mismatch.

## Consequences
- The smudged-weight case is billed at the right amount.
- **[ASSUMPTION]** Per-tonne billing from certified scale weights is common practice; to confirm with the carrier.
