"""Field mapping from saved Azure responses (synthetic tickets). Runs offline: no pages spent."""
import json
from pathlib import Path

import pytest

from ticket_audit.domain.normalize import key, normalize_lsd, parse_number
from ticket_audit.extract.azure import AzureExtractor

FIXTURES = Path(__file__).parent / "fixtures" / "azure"
CHECKED = {
    "haul": ["ticket_no", "dispatch_no", "date", "unit", "customer", "po", "afe", "origin", "scale_ticket_no",
             "lease", "lsd", "product", "net_t", "arrive", "depart", "standby_h", "receiver_name"],
    "scale": ["scale_ticket_no", "date", "unit", "product", "gross_kg", "tare_kg", "net_kg"],
}


def same(name, got, want):
    if name in ("net_t", "gross_kg", "tare_kg", "net_kg", "standby_h"):
        return parse_number(got) == parse_number(want)
    if name == "lsd":
        return normalize_lsd(got) == want
    return key(got) == key(want)


@pytest.fixture
def extractor():
    return AzureExtractor("https://example.invalid/", "unused")


@pytest.mark.parametrize("label", ["haul-clean", "haul-shifted-pairs", "haul-overlapping-value",
                                   "haul-split-label", "scale"])
def test_every_field_lands_where_it_belongs(extractor, label):
    result = json.loads((FIXTURES / f"{label}.json").read_text())
    truth = json.loads((FIXTURES / f"{label}.truth.json").read_text())
    kind = extractor.classify(result["content"])
    assert kind == truth["kind"]
    fields = extractor.map_fields(result, kind)
    for name in CHECKED[kind]:
        want = truth["fields"].get(name, "")
        if want:
            assert name in fields, f"{name} missing"
            assert same(name, fields[name].value, want), f"{name}: {fields[name].value!r} vs {want!r}"
        else:  # blank on the ticket: absent, or low enough that a human checks it
            assert name not in fields or fields[name].confidence <= 0.5, \
                f"{name} should be blank, got {fields[name].value!r} at {fields[name].confidence}"


def test_shifted_azure_pairing_lowers_confidence(extractor):
    """Azure paired 'NET WEIGHT' with the land description here; the disagreement must send it to a human."""
    result = json.loads((FIXTURES / "haul-shifted-pairs.json").read_text())
    fields = extractor.map_fields(result, "haul")
    assert fields["net_t"].confidence <= 0.5


def test_saved_responses_are_reused_not_paid_for(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    doc = tmp_path / "IMG_0001.jpg"
    doc.write_bytes(b"x")
    (raw / "abc.json").write_text((FIXTURES / "scale.json").read_text())
    ex = AzureExtractor("https://example.invalid/", "unused", raw_dir=raw, max_pages=0)
    assert ex.extract(doc, "abc").kind == "scale"  # max_pages=0: any real call would raise
