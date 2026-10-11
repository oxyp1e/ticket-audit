"""What broke while building this, what changed, and the measured effect. Shown on the site.

Every entry is something that happened on this system's own runs; numbers come from the run
outputs and `python -m ticket_audit.evaluate`. Batches: audit (30 loads, 59 photos), day (100 loads,
199 photos), both read by Azure AI Document Intelligence.
"""

IMPROVEMENTS = [
    {
        "date": "2026-10-09",
        "title": "A smudged weight was misread with fairly high confidence",
        "found": "On the first test photo of a smudged, written-over weight, Azure read 40.49 t as 10.48 t at 0.85 "
                 "confidence; clean fields scored 0.93–1.00.",
        "change": "Confidence alone is never enough on a money field. The driver's weight is checked against the "
                  "scale ticket, an independent printed record, in addition to the confidence floor.",
        "effect": "A misread like this is held as a weight mismatch whatever its confidence.",
        "evidence": "docs/adr/0003-when-in-doubt-exception.md",
    },
    {
        "date": "2026-10-09",
        "title": "Correct handwriting scored low confidence",
        "found": "First Azure reads: land descriptions read correctly scored 0.66–0.86, customer names as low as "
                 "0.69. A flat 0.80 floor would have held most clean tickets.",
        "change": "A value that exactly matches an independent record (the lease's land description, a known "
                  "customer, the dispatch date and truck) doesn't need high OCR confidence. Money and identity fields "
                  "keep a 0.90 floor.",
        "effect": "Clean tickets pass on agreement between records, not on how neat the handwriting is.",
        "evidence": "docs/adr/0003-when-in-doubt-exception.md",
    },
    {
        "date": "2026-10-09",
        "title": "Azure paired labels with the wrong values",
        "found": "First Azure run on the audit batch: 12 approved, 20 held, against 20 and 9 on generator truth. "
                 "Azure's key-value pairing glued a scale ticket number to the date, paired UNIT with the trailer, "
                 "missed the receiver boxes on one ticket and shifted a whole row on another. The text itself was "
                 "read correctly.",
        "change": "Fields are read by position: the handwriting under each box label, and the value on each receipt "
                  "row corrected for the photo's tilt. Azure's pairing became a second opinion; where the two "
                  "disagree, the field goes to a person. Saved responses were re-mapped at no OCR cost.",
        "effect": "Audit batch: 17 approved, 12 held, every planted problem still held.",
        "evidence": "docs/adr/0006-position-based-field-pairing.md",
    },
    {
        "date": "2026-10-09",
        "title": "An empty standby box picked up a neighbouring value",
        "found": "A regression test built from a saved response showed a blank standby box mapped to 40.90 (the net "
                 "weight, from Azure's shifted pairing) at full confidence. On a clean ticket that could have billed "
                 "40.9 hours of standby.",
        "change": "When a box looks empty by position but Azure pairs a value with it, the value gets confidence "
                  "0.5, so a person checks it.",
        "effect": "Caught by a test before it reached any output.",
        "evidence": "tests/test_azure_mapping.py",
    },
    {
        "date": "2026-10-09",
        "title": "A confident misread passed the floor; clean tickets didn't",
        "found": "The smudged weight was read as 40.48 t (true 40.49) at 0.91, above the 0.90 floor. Meanwhile two "
                 "clean tickets read at 0.86 were held although they matched the scale exactly.",
        "change": "Tonnes are billed from the scale ticket (printed, and checked by gross − tare = net). The driver's "
                  "weight is a cross-check: within 0.05 t its confidence doesn't matter; outside it the ticket is held.",
        "effect": "Audit batch: 19 approved plus 1 with standby added; the two still held are a real misread of one "
                  "customer's PO (75186 read as 75786), held correctly.",
        "evidence": "docs/adr/0007-bill-from-the-scale-ticket.md",
    },
    {
        "date": "2026-10-09",
        "title": "The network dropped mid-run",
        "found": "Azure reset the connection after 117 of the day batch's 199 photos. The run failed and nothing was "
                 "approved.",
        "change": "Re-ran the same command: the 117 saved responses were reused and only the rest were read. Dropped "
                  "connections and timeouts are now retried with backoff.",
        "effect": "The reliability fitness function, happening for real: no photo read twice, identical output.",
        "evidence": "docs/runbook.md",
    },
    {
        "date": "2026-10-10",
        "title": "Day batch: eight clean tickets held by parsing gaps",
        "found": "First evaluation of the day batch: 81 of 89 loads that should pass were approved. Causes: "
                 "handwriting touching its label, \"STANDBY (h)\" split so \"(h)\" was read as the value, a date "
                 "written \"2026- 10-01\", and \"WE\" read for the W6 meridian.",
        "change": "A first fix measured the search window in label heights and made things worse (41 of 89): labels "
                  "are small next to tall handwriting. Replaced by a structural rule: a value sits below its label "
                  "and above the next label in the same column. Label fragments are ignored; spaced dates and WE→W6 "
                  "normalized.",
        "effect": "Day batch: 89 of 89 approved, 12 of 12 problems held, 2,203 of 2,204 fields read correctly: the "
                  "same outcome as the answer key.",
        "evidence": "tests/fixtures/azure/",
    },
    {
        "date": "2026-10-09",
        "title": "Regenerating test data would have deleted the OCR results",
        "found": "The generator replaced each batch folder, including the saved Azure responses: about 260 free-tier "
                 "pages to rebuild.",
        "change": "The generator replaces only the inputs. Rendering was checked byte-for-byte: all 258 photos come "
                  "out identical, so a regenerated batch still matches its saved responses.",
        "effect": "No page has been paid for twice.",
        "evidence": "src/ticket_audit/synth/__main__.py",
    },
]
