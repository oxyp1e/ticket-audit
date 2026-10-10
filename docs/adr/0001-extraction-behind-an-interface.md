# 1. The extraction engine sits behind an interface

**Status:** accepted

## Context
Reading documents is the only probabilistic step. The rules must be testable without OCR, and the OCR engine may need to change (cost, data-residency rules in customer contracts, accuracy).

## Decision
Every engine implements one method, `extract(path, sha256) -> Extraction` (`extract/base.py`), returning fields with a confidence each, blank fields left out. Two implementations today:
- **Generator truth** (`extract/truth.py`): what the generator wrote, with the confidence an OCR engine would plausibly give. It drives the fitness functions at zero cost.
- **Azure AI Document Intelligence** (`extract/azure.py`), `prebuilt-layout` with key-value pairs, F0 tier.

A local engine (on-premises OCR) would be a third implementation; nothing else changes.

## Consequences
- The rules were finished and proven before the first real OCR page was spent.
- The extraction cache is keyed by photo hash, engine and model version, so switching engines never mixes results.
- The engine's name and model version are recorded on every decision (ADR 4).

## Revisit when
A customer contract restricts sending documents to a cloud service: add the local engine.
