"""The synthetic world: one carrier, its customers, pits, leases, trucks and rate sheet.

Every company and person name here is invented. Figures marked [ASSUMPTION] have
no public source and are stated as such in the README.
"""
import random
from dataclasses import dataclass, field
from datetime import date

from ticket_audit.domain.lsd import Lsd

CARRIER = "Larkspur Bulk Hauling Ltd."
CARRIER_SHORT = "LARKSPUR BULK"
TICKET_PREFIX = "LB"

PRODUCTS = ("Frac Sand 40/70", "Frac Sand 100 Mesh", "Frac Sand 30/50")

# [ASSUMPTION] B-train frac sand loads: gross up to 63,500 kg, tare 20.5-23.5 t, payload 38-42 t.
MAX_GROSS_KG = 63_500
TARE_KG = (20_500, 23_500)
PAYLOAD_KG = (38_000, 42_000)
PLANNED_T = 40.0  # nominal tonnes on the dispatch record

# [ASSUMPTION] free time on site before standby is billable.
FREE_TIME_H = 1.0
RATES_EFFECTIVE_FROM = date(2026, 1, 1)

_CUSTOMERS = [
    ("BRK", "Brackenhollow Energy Ltd.", ("Brackenhollow Energy", "Brackenhollow")),
    ("QLM", "Quillmere Resources Inc.", ("Quillmere Resources", "Quillmere Res.")),
    ("THR", "Thornbury Ridge Petroleum Ltd.", ("Thornbury Ridge", "Thornbury Ridge Pet.")),
    ("ASH", "Ashgrove Basin Energy Corp.", ("Ashgrove Basin", "Ashgrove Energy")),
    ("WXC", "Wexley Creek Oil Ltd.", ("Wexley Creek", "Wexley Creek Oil")),
]
_PITS = [
    ("FEN3", "Fenwick Silica - Pit 3", "SCALE HOUSE 2"),
    ("HAL1", "Halcrow Sand - Pit 1", "SCALE 1"),
    ("MRB2", "Marrowby Silica - Pit 2", "NORTH SCALE"),
]
_SURNAMES = [
    "Halvorsen", "Marsh", "Dube", "Kowalczyk", "Nguyen", "Fraser", "Olsen", "Petrov", "Singh",
    "Moreau", "Baker", "Tremblay", "Novak", "Ferreira", "Wiebe", "Klassen", "Bauer", "Ramos",
    "Chen", "Adeyemi", "Lindqvist", "MacLeod", "Sato", "Horvath", "Byrne", "Oyelaran", "Dumont",
    "Sorensen", "Gill", "Mercer", "Haddad", "Kaur", "Boychuk", "Lachance", "Reimer", "Toews",
]


@dataclass(frozen=True)
class Customer:
    code: str
    name: str
    aliases: tuple[str, ...]
    po: str


@dataclass(frozen=True)
class Pit:
    code: str
    name: str
    scale_house: str


@dataclass(frozen=True)
class Lease:
    code: str
    customer: str
    name: str
    lsd: str
    afe: str
    receivers: tuple[str, ...]


@dataclass(frozen=True)
class Truck:
    unit: str
    trailer: str
    driver: str


@dataclass(frozen=True)
class Lane:
    pit: str
    lease: str


@dataclass
class Rate:
    customer: str
    pit: str
    lease: str
    per_tonne: float
    standby_per_h: float
    free_time_h: float
    effective_from: date
    effective_to: date | None = None


@dataclass
class World:
    customers: dict[str, Customer]
    pits: dict[str, Pit]
    leases: dict[str, Lease]
    trucks: list[Truck]
    lanes: list[Lane]
    travel_h: dict[Lane, float]
    rates: list[Rate] = field(default_factory=list)
    weighmasters: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def rate_for(self, lane: Lane) -> Rate | None:
        return next((r for r in self.rates if r.pit == lane.pit and r.lease == lane.lease), None)


def _person(rng: random.Random) -> str:
    return f"{rng.choice('ABCDEGHJKLMNPRST')}. {rng.choice(_SURNAMES)}"


def _random_lsd(rng: random.Random) -> str:
    """Montney/Duvernay-style locations: W5 or W6, valid ranges only."""
    meridian = rng.choice((5, 5, 6))
    township = rng.randint(55, 80)
    rge = rng.randint(1, 26 if meridian == 5 else 13)
    return str(Lsd(rng.randint(1, 16), rng.randint(1, 36), township, rge, meridian))


def build_world(rng: random.Random, n_trucks: int) -> World:
    customers = {
        code: Customer(code, name, aliases, f"PO-{rng.randint(70000, 79999)}")
        for code, name, aliases in _CUSTOMERS
    }
    pits = {code: Pit(code, name, scale) for code, name, scale in _PITS}

    leases: dict[str, Lease] = {}
    for c in customers.values():
        short = c.name.split()[0]
        for _ in range(rng.randint(2, 3)):
            lsd = _random_lsd(rng)
            while (code := f"{c.code}-{lsd[:5]}") in leases:
                lsd = _random_lsd(rng)
            # Pad names follow the surface location, e.g. "Brackenhollow 4-17 Pad".
            name = f"{short} {int(lsd[0:2])}-{int(lsd[3:5])} Pad"
            afe = f"AFE 26-{rng.randint(100, 999):04d}"
            receivers = tuple(_person(rng) for _ in range(rng.randint(1, 2)))
            leases[code] = Lease(code, c.code, name, lsd, afe, receivers)

    lanes, travel_h = [], {}
    for lease in leases.values():
        for pit in rng.sample(list(pits), rng.randint(1, 2)):
            lane = Lane(pit, lease.code)
            lanes.append(lane)
            travel_h[lane] = round(rng.uniform(1.25, 3.0), 2)

    rates = [
        Rate(
            customer=leases[lane.lease].customer,
            pit=lane.pit,
            lease=lane.lease,
            per_tonne=round(9.0 + 4.2 * travel_h[lane] + rng.uniform(-0.8, 0.8), 2),
            standby_per_h=float(rng.choice((125, 135, 140, 150))),
            free_time_h=FREE_TIME_H,
            effective_from=RATES_EFFECTIVE_FROM,
        )
        for lane in lanes
    ]

    units = rng.sample(range(301, 699), n_trucks)
    trucks = [Truck(str(u), f"T-{rng.randint(100, 999):04d}", _person(rng)) for u in sorted(units)]
    weighmasters = {code: tuple(_person(rng) for _ in range(2)) for code in pits}
    return World(customers, pits, leases, trucks, lanes, travel_h, rates, weighmasters)
