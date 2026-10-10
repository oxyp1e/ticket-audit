import pytest

from ticket_audit.domain.lsd import is_valid_lsd, parse_lsd


@pytest.mark.parametrize("text", ["04-17-062-20W5", "16-36-126-30W4", "01-01-001-14W6"])
def test_valid(text):
    assert is_valid_lsd(text)
    assert str(parse_lsd(text)) == text


@pytest.mark.parametrize("text", [
    "17-17-062-20W5",  # LSD > 16
    "04-37-062-20W5",  # section > 36
    "04-17-127-20W5",  # township > 126
    "04-17-062-31W5",  # range > 30
    "04-17-062-15W6",  # W6 has at most 14 ranges
    "04-17-062-20W3",  # not an Alberta meridian
    "04-17-062-20WS",  # OCR confusion, not canonical
    "4-17-62-20W5",    # not zero-padded
])
def test_invalid(text):
    assert not is_valid_lsd(text)
