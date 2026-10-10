# 6. Pair values with labels by position; Azure's key-value pairs are a second opinion

**Status:** accepted

## Context
Azure's text recognition was accurate, but its label-value pairing failed on these forms: it glued a scale ticket number to the date, missed the receiver boxes on one ticket, and shifted a whole row of boxes by one on another (net weight paired with the land description).

## Decision
Fields are paired by layout: on the haul ticket, the handwriting below a box label and above the next label in the same column; on the scale receipt, the value on the label's row, corrected for the photo's tilt. Azure's own pairing is a second reading: if the two disagree, or Azure pairs a value with a box that looks empty, the field's confidence drops to 0.5, so any field that matters goes to a person. Raw responses are saved, and the mapping is re-applied to them without new calls.

## Consequences
- Day batch: 2,203 of 2,204 decision fields read correctly, none wrong with high confidence.
- Each failure seen is a regression test built from a saved response (`tests/fixtures/azure/`).
- A real carrier's ticket layout needs its own label list; the method stays the same. A trained custom model is the alternative once real tickets exist.
