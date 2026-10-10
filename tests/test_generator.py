"""The generator's own checks: every planted problem is present, and the data is internally plausible.

Plausibility is checked against public facts where they exist (LSD format) and against the
README's stated assumptions otherwise (weights, free time).
"""
from collections import Counter, defaultdict

import pytest

from ticket_audit.domain.lsd import is_valid_lsd
from ticket_audit.synth.__main__ import BATCHES, build, truth
from ticket_audit.synth.batch import EXPECTED
from ticket_audit.synth.world import MAX_GROSS_KG, PAYLOAD_KG, TARE_KG

ALL_CODES = {c for c in EXPECTED if c}


@pytest.fixture(scope="module", params=list(BATCHES))
def batch(request):
    return build(BATCHES[request.param], seed=7)


def test_every_planted_problem_is_present(batch):
    assert {ld.planted for ld in batch.loads} - {None} == ALL_CODES


def test_audit_batch_has_each_problem_once_and_mostly_clean():
    b = build(BATCHES["audit"], seed=7)
    counts = Counter(ld.planted for ld in b.loads)
    assert all(counts[c] >= 1 for c in ALL_CODES)
    assert counts[None] >= 14


def test_same_seed_same_batch():
    a, b = build(BATCHES["audit"], seed=7), build(BATCHES["audit"], seed=7)
    assert truth(a) == truth(b)


def test_different_seed_different_batch():
    assert truth(build(BATCHES["audit"], seed=7)) != truth(build(BATCHES["audit"], seed=8))


def test_lsds_are_valid(batch):
    assert all(is_valid_lsd(lease.lsd) for lease in batch.world.leases.values())
    assert all(is_valid_lsd(d.fields["lsd"]) for d in batch.documents if d.kind == "haul")


def test_weights_are_plausible(batch):
    for ld in batch.loads:
        assert TARE_KG[0] <= ld.tare_kg <= TARE_KG[1] + 10
        assert ld.gross_kg <= MAX_GROSS_KG
        assert PAYLOAD_KG[0] - 10 <= ld.net_kg <= PAYLOAD_KG[1] + 10


def test_times_follow_the_haul(batch):
    for ld in batch.loads:
        assert ld.time_in < ld.time_out < ld.arrive < ld.depart
        travel = (ld.arrive - ld.time_out).total_seconds() / 3600
        assert travel == pytest.approx(batch.world.travel_h[ld.lane], rel=0.1)


def test_no_truck_is_in_two_places_at_once(batch):
    by_truck = defaultdict(list)
    for ld in batch.loads:
        by_truck[ld.truck.unit].append(ld)
    for loads in by_truck.values():
        loads.sort(key=lambda ld: ld.time_in)
        for a, b in zip(loads, loads[1:]):
            assert a.depart < b.time_in


def test_clean_tickets_agree_with_scale_and_dispatch(batch):
    docs = {(d.load_id, d.kind): d for d in batch.documents}
    for ld in batch.loads:
        if ld.planted is not None:
            continue
        haul, scale = docs[(ld.load_id, "haul")].fields, docs[(ld.load_id, "scale")].fields
        assert float(haul["net_t"]) * 1000 == int(scale["net_kg"].replace(",", ""))
        assert haul["dispatch_no"] == ld.dispatch_no
        assert haul["scale_ticket_no"] == scale["scale_ticket_no"]
        assert haul["afe"] and haul["receiver_signature"]
        assert haul["standby_h"] == ("" if ld.standby_h == 0 else f"{ld.standby_h:g}")


def test_ticket_numbers_unique_except_planted_duplicates(batch):
    hauls = Counter(d.fields["ticket_no"] for d in batch.documents if d.kind == "haul")
    dup_loads = {ld.ticket_no for ld in batch.loads if ld.planted == "P4"}
    assert {t for t, n in hauls.items() if n > 1} == dup_loads
    assert len(batch.duplicates) == len(dup_loads)


def test_planted_problems_look_the_way_the_spec_says(batch):
    docs = defaultdict(dict)
    for d in batch.documents:
        docs[d.load_id].setdefault(d.kind, d)
    rates = {(r.pit, r.lease): r for r in batch.world.rates}
    for ld in batch.loads:
        haul = docs[ld.load_id].get("haul")
        scale = docs[ld.load_id].get("scale")
        match ld.planted:
            case "P1":
                assert abs(float(haul.fields["net_t"]) * 1000 - ld.net_kg) >= 1000
            case "P2":
                assert haul.fields["receiver_signature"] == ""
            case "P3":
                assert haul.fields["afe"] == ""
            case "P5":
                assert haul.fields["standby_h"] == "" and ld.standby_h >= 1.0
            case "P6":
                assert haul.illegible == ["net_t"]
            case "P8":
                assert haul is None and scale is None
            case "P9":
                assert haul.fields["dispatch_no"] == ""
            case "P10":
                assert (ld.lane.pit, ld.lane.lease) not in rates
            case "P11":
                r = rates[(ld.lane.pit, ld.lane.lease)]
                assert r.effective_to is not None and ld.day > r.effective_to


def test_files_do_not_reveal_the_load(batch):
    assert all(d.file.startswith("IMG_") for d in batch.documents)
    assert all(d.load_id not in d.file for d in batch.documents)
