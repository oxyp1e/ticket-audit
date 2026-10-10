"""The report's numbers must trace to the decisions, and the page must say it is synthetic."""
import csv
import re

import pytest

from tests.test_fitness import make_batch
from ticket_audit.extract.truth import TruthExtractor
from ticket_audit.pipeline import run_batch
from ticket_audit.report import render, summarize


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    batch = make_batch(tmp_path_factory.mktemp("report"), "audit")
    s = run_batch(batch, TruthExtractor(batch / "truth" / "documents.json"))
    return batch, s.out_dir, summarize(batch, "truth")


def test_numbers_reconcile_with_the_output_files(report):
    _, out, s = report
    approved = list(csv.DictReader((out / "approved.csv").open()))
    exceptions = list(csv.DictReader((out / "exceptions.csv").open()))
    assert s.approved + s.adjusted == len(approved)
    assert len(s.queue) == len(exceptions)
    assert s.approved_value == pytest.approx(sum(float(r["total"]) for r in approved))
    assert s.recovered == pytest.approx(sum(float(r["standby_amount"]) for r in approved
                                            if r["standby_recovered"] == "True"))
    dupes = [r for r in exceptions if "DUPLICATE_TICKET" in r["reason_codes"]]
    assert s.overbilling_prevented == pytest.approx(sum(float(r["amount_at_stake"]) for r in dupes))
    assert s.recovered > 0 and s.overbilling_prevented > 0 and s.at_stake_missing > 0


def test_page_is_labelled_synthetic_and_never_sums_the_two_headlines(report):
    _, _, s = report
    html = render(s)
    assert "Synthetic batch" in html and "All amounts are synthetic" in html
    total = f"${s.underbilling + s.overbilling_prevented:,.2f}"
    assert total not in html


def test_every_exception_links_to_its_source_photos(report):
    batch, _, s = report
    html = render(s)
    for e in s.queue:
        for doc in filter(None, e["documents"].values()):
            assert f"inbox/{doc['file']}" in html
            assert (batch / "inbox" / doc["file"]).exists()
    assert len(re.findall(r'<details class="item">', html)) == len(s.queue)
