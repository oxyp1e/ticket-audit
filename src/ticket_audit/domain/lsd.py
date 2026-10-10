"""Alberta Dominion Land Survey (DLS) legal subdivision, e.g. 04-17-062-20W5.

Ranges from the AER UWI description: LSD 1-16, section 1-36, township 1-126,
range 1-30, meridian W4/W5/W6 in Alberta; W6 has at most 14 ranges.
"""
import re
from dataclasses import dataclass

_PATTERN = re.compile(r"^(\d{2})-(\d{2})-(\d{3})-(\d{2})W([456])$")
MAX_RANGE = {4: 30, 5: 30, 6: 14}


@dataclass(frozen=True)
class Lsd:
    lsd: int
    section: int
    township: int
    range: int
    meridian: int

    def __str__(self) -> str:
        return f"{self.lsd:02d}-{self.section:02d}-{self.township:03d}-{self.range:02d}W{self.meridian}"


def parse_lsd(text: str) -> Lsd | None:
    """Return the LSD if `text` is a valid DLS location in canonical form, else None."""
    m = _PATTERN.match(text)
    if not m:
        return None
    lsd, section, township, rge, meridian = (int(g) for g in m.groups())
    if not (1 <= lsd <= 16 and 1 <= section <= 36 and 1 <= township <= 126):
        return None
    if not 1 <= rge <= MAX_RANGE[meridian]:
        return None
    return Lsd(lsd, section, township, rge, meridian)


def is_valid_lsd(text: str) -> bool:
    return parse_lsd(text) is not None
