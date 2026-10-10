from datetime import date, time

import pytest

from ticket_audit.domain.lsd import is_valid_lsd
from ticket_audit.domain.normalize import key, normalize_lsd, parse_date, parse_number, parse_time
from ticket_audit.domain.rules import billable_standby


@pytest.mark.parametrize("raw, fixed", [
    ("04-17-062-20WS", "04-17-062-20W5"),   # seen from Azure on a real test photo
    ("4-17-62-20W5", "04-17-062-20W5"),
    ("O4-17-O62-20W5", "04-17-062-20W5"),
    (" 04-17-062-20 W5 ", "04-17-062-20W5"),
])
def test_lsd_ocr_confusions_are_undone(raw, fixed):
    assert normalize_lsd(raw) == fixed
    assert is_valid_lsd(normalize_lsd(raw))


def test_lsd_that_is_wrong_stays_wrong():
    assert not is_valid_lsd(normalize_lsd("04-37-062-20W5"))


@pytest.mark.parametrize("text", ["2026-09-28", "28-Sep-26", "Sep 28 2026"])
def test_date_formats_drivers_use(text):
    assert parse_date(text) == date(2026, 9, 28)


def test_ambiguous_or_garbled_dates_are_not_guessed():
    assert parse_date("28/09/26") is None
    assert parse_date("2O26-09-28") is None


def test_times_and_numbers():
    assert parse_time("9:40") == time(9, 40)
    assert parse_time("25:10") is None
    assert parse_number("41,200 kg") == 41200
    assert parse_number("40.49") == 40.49


def test_names_compare_without_case_or_punctuation():
    assert key("Brackenhollow Energy Ltd.") == key("BRACKENHOLLOW ENERGY LTD")


@pytest.mark.parametrize("arrive, depart, hours", [
    (time(9, 40), time(10, 30), 0.0),   # inside free time
    (time(9, 40), time(13, 10), 2.5),   # 3.5 h on site, 1 h free
    (time(23, 30), time(2, 0), 1.5),    # past midnight
])
def test_billable_standby(arrive, depart, hours):
    assert billable_standby(arrive, depart, free_time_h=1.0) == hours
