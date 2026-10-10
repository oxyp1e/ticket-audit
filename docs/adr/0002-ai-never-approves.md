# 2. AI never makes the approve decision

**Status:** accepted

## Context
Invoices go to customers. A wrong line costs money and trust, and someone must be able to explain every decision.

## Decision
OCR reads; rules decide. The decision engine (`domain/rules.py`) is a pure function with no I/O: the same tickets, dispatch and rates give the same decisions on every run. Thresholds and reason texts are data (`CONFIG`, `REASONS`); their hash forms the **rule version** stamped on every decision. Every reason is a sentence a billing clerk can act on.

## Consequences
- Decisions are reproducible and testable; the three fitness functions run on the rules alone.
- Changing a threshold is a reviewed code change that changes the rule version, not a model retrain.
- A question-answering agent over the decision log, if added, is read-only and must cite log entries.
