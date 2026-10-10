"""Turns the world into a batch: dispatched loads, the tickets they produce, and planted problems.

Outputs are split so the rules can never see the answers:
- documents: what each ticket photo says (used to render, and by the generator-truth extraction engine)
- dispatch + rates: the TMS stand-in
- expected: which load carries which planted problem and the outcome it must get (tests only)
"""
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ticket_audit.synth.world import (
    CARRIER_SHORT, FREE_TIME_H, MAX_GROSS_KG, PAYLOAD_KG, PLANNED_T, PRODUCTS, TARE_KG,
    TICKET_PREFIX, Lane, Truck, World,
)

# Planted problems (spec §3) and the outcome each must get.
EXPECTED = {
    None: ("approve", []),
    "P1": ("exception", ["WEIGHT_MISMATCH"]),
    "P2": ("exception", ["NO_SIGNATURE"]),
    "P3": ("exception", ["MISSING_COST_CODE"]),
    "P4": ("approve", []),  # the original; the second copy is the exception (see duplicates)
    "P5": ("approve_adjusted", ["STANDBY_RECOVERED"]),
    "P6": ("exception", ["LOW_CONFIDENCE"]),
    "P7": ("exception", ["NO_DISPATCH_MATCH"]),
    "P8": ("missing_ticket", ["MISSING_TICKET"]),
    "P9": ("exception", ["FALLBACK_MATCH"]),
    "P10": ("exception", ["NO_RATE"]),
    "P11": ("exception", ["RATE_EXPIRED"]),
}
LOAD_LEVEL = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]
# Share of loads hit by each load-level problem in a volume batch (at least one of each).
# [ASSUMPTION] chosen to give roughly 8% load-level problems; no public figure exists for real error rates.
VOLUME_RATES = {"P1": 0.015, "P2": 0.01, "P3": 0.01, "P4": 0.005, "P5": 0.02,
                "P6": 0.01, "P7": 0.005, "P8": 0.005, "P9": 0.005}


@dataclass
class Load:
    day: date
    truck: Truck
    lane: Lane
    customer: str
    product: str
    time_in: datetime
    time_out: datetime
    arrive: datetime
    depart: datetime
    tare_kg: int
    gross_kg: int
    load_id: str = ""
    dispatch_no: str = ""
    ticket_no: str = ""
    scale_ticket_no: str = ""
    receiver: str = ""
    weighmaster: str = ""
    planted: str | None = None

    @property
    def net_kg(self) -> int:
        return self.gross_kg - self.tare_kg

    @property
    def on_site_h(self) -> float:
        return (self.depart - self.arrive).total_seconds() / 3600

    @property
    def standby_h(self) -> float:
        """Billable standby a careful driver would write: time on site beyond free time, to the quarter hour."""
        return round(max(0.0, self.on_site_h - FREE_TIME_H) * 4) / 4


@dataclass
class Document:
    file: str
    kind: str  # "haul" | "scale"
    load_id: str
    fields: dict[str, str]
    illegible: list[str] = field(default_factory=list)


@dataclass
class Batch:
    name: str
    seed: int
    world: World
    loads: list[Load]
    documents: list[Document]
    duplicates: list[dict]


def _h(hours: float) -> timedelta:
    return timedelta(hours=hours)


def schedule(world: World, rng: random.Random, days: list[date], target: int) -> list[Load]:
    """Simulate truck days: each truck works a job (lane) and cycles pit -> site -> pit."""
    loads: list[Load] = []
    for day in days:
        for truck in world.trucks:
            if rng.random() < 0.1:  # truck down for the day
                continue
            lane = rng.choice(world.lanes)
            product = rng.choice(PRODUCTS)
            clock = datetime.combine(day, time(5)) + timedelta(minutes=rng.randint(0, 120))
            while clock.date() == day and clock.hour < 19:
                if rng.random() < 0.15:  # dispatcher moves the truck to another job
                    lane, product = rng.choice(world.lanes), rng.choice(PRODUCTS)
                travel = world.travel_h[lane]
                time_in = clock
                time_out = time_in + timedelta(minutes=rng.randint(15, 35))
                arrive = time_out + _h(travel * rng.uniform(0.92, 1.08))
                site = rng.uniform(0.6, 1.0) if rng.random() > 0.25 else rng.uniform(2.0, 4.0)
                depart = arrive + _h(site)
                tare = round(rng.randint(*TARE_KG), -1)
                gross = min(MAX_GROSS_KG, round(tare + rng.randint(*PAYLOAD_KG), -1))
                loads.append(Load(day, truck, lane, world.leases[lane.lease].customer, product,
                                  time_in, time_out, arrive, depart, tare, gross))
                clock = depart + _h(travel * rng.uniform(0.92, 1.08)) + timedelta(minutes=rng.randint(0, 20))
    if len(loads) < target:
        raise ValueError(f"only {len(loads)} loads scheduled, need {target}: add trucks or days")
    loads = sorted(rng.sample(loads, target), key=lambda ld: (ld.time_in, ld.truck.unit))
    _number(world, rng, loads)
    return loads


def _number(world: World, rng: random.Random, loads: list[Load]) -> None:
    """Dispatch numbers in time order; each truck has its own ticket book; each pit its own scale sequence."""
    dispatch_start = rng.randint(400, 900)
    books = {t.unit: 104000 + i * 300 + rng.randint(0, 99) for i, t in enumerate(world.trucks)}
    scale_seq = {code: rng.randint(80000, 95000) for code in world.pits}
    for i, ld in enumerate(loads):
        ld.load_id = f"L{i + 1:04d}"
        ld.dispatch_no = f"D-26-{dispatch_start + i:04d}"
        books[ld.truck.unit] += 1
        ld.ticket_no = f"{TICKET_PREFIX}-{books[ld.truck.unit]}"
        scale_seq[ld.lane.pit] += 1
        ld.scale_ticket_no = f"{scale_seq[ld.lane.pit]:07d}"
        ld.receiver = rng.choice(world.leases[ld.lane.lease].receivers)
        ld.weighmaster = rng.choice(world.weighmasters[ld.lane.pit])


def plant(world: World, rng: random.Random, loads: list[Load], mode: str) -> None:
    """Plant problems. Rate problems hit whole lanes (a missing rate affects every load on that job)."""
    by_lane: dict[Lane, list[Load]] = {}
    for ld in loads:
        by_lane.setdefault(ld.lane, []).append(ld)
    lanes = sorted(by_lane, key=lambda ln: (len(by_lane[ln]), ln.pit, ln.lease))

    no_rate = lanes[0]  # the least-used lane: a job set up in dispatch whose rate was never entered
    world.rates.remove(world.rate_for(no_rate))
    for ld in by_lane[no_rate]:
        ld.planted = "P10"

    # Expired rate: the rate ends the day before the lane's last working day.
    expired = min(lanes[1:], key=lambda ln: sum(ld.day == max(x.day for x in by_lane[ln]) for ld in by_lane[ln]))
    last_day = max(ld.day for ld in by_lane[expired])
    world.rate_for(expired).effective_to = last_day - timedelta(days=1)
    for ld in by_lane[expired]:
        if ld.day == last_day:
            ld.planted = "P11"

    # Matching on date + unit + customer is only meaningful when that key is unique.
    key_count = Counter((ld.day, ld.truck.unit, ld.customer) for ld in loads)
    eligible = {
        "P5": lambda ld: ld.standby_h >= 1.0,
        "P7": lambda ld: key_count[(ld.day, ld.truck.unit, ld.customer)] == 1,
        "P9": lambda ld: key_count[(ld.day, ld.truck.unit, ld.customer)] == 1,
    }
    if mode == "audit":
        quotas = {code: 1 for code in LOAD_LEVEL}
    else:
        quotas = {code: max(1, round(share * len(loads))) for code, share in VOLUME_RATES.items()}
    free = [ld for ld in loads if ld.planted is None]
    rng.shuffle(free)
    # Most constrained problems first, so they still find an eligible load.
    for code in sorted(quotas, key=lambda c: c not in eligible):
        ok = eligible.get(code, lambda ld: True)
        picks = [ld for ld in free if ld.planted is None and ok(ld)][: quotas[code]]
        if len(picks) < quotas[code]:
            raise ValueError(f"only {len(picks)} eligible loads for {code}: change the seed or batch size")
        for ld in picks:
            ld.planted = code


_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d", "%d-%b-%y", "%b %d %Y")  # unambiguous only: no 03/04/26


def _written_time(t: datetime, rng: random.Random) -> str:
    return t.strftime("%H:%M") if rng.random() < 0.6 else f"{t.hour}:{t.minute:02d}"


def _haul_fields(world: World, ld: Load, rng: random.Random) -> tuple[dict[str, str], list[str]]:
    cust = world.customers[ld.customer]
    lease = world.leases[ld.lane.lease]
    net_t = ld.net_kg / 1000
    if ld.planted == "P1":
        net_t += rng.choice((-1, 1)) * rng.uniform(1.0, 3.0)
    standby = "" if ld.planted == "P5" or ld.standby_h == 0 else f"{ld.standby_h:g}"
    f = {
        "ticket_no": ld.ticket_no,
        "dispatch_no": "" if ld.planted == "P9" else ld.dispatch_no,
        "date": ld.day.strftime(rng.choice(_DATE_FORMATS)),
        "unit": ld.truck.unit,
        "trailer": ld.truck.trailer,
        "driver": ld.truck.driver,
        "customer": cust.name if rng.random() < 0.6 else rng.choice(cust.aliases),
        "po": cust.po,
        "afe": "" if ld.planted == "P3" else lease.afe,
        "origin": world.pits[ld.lane.pit].name,
        "scale_ticket_no": ld.scale_ticket_no,
        "lease": lease.name,
        "lsd": lease.lsd,
        "product": ld.product,
        "net_t": f"{net_t:.2f}",
        "arrive": _written_time(ld.arrive, rng),
        "depart": _written_time(ld.depart, rng),
        "standby_h": standby,
        "receiver_name": ld.receiver,
        "receiver_signature": "" if ld.planted == "P2" else ld.receiver,
    }
    return f, (["net_t"] if ld.planted == "P6" else [])


def _scale_fields(world: World, ld: Load) -> dict[str, str]:
    pit = world.pits[ld.lane.pit]
    return {
        "scale_ticket_no": ld.scale_ticket_no,
        "pit": pit.name,
        "scale_house": pit.scale_house,
        "date": ld.day.isoformat(),
        "time_in": ld.time_in.strftime("%H:%M"),
        "time_out": ld.time_out.strftime("%H:%M"),
        "carrier": CARRIER_SHORT,
        "unit": ld.truck.unit,
        "trailer": ld.truck.trailer,
        "product": ld.product.upper(),
        "gross_kg": f"{ld.gross_kg:,}",
        "tare_kg": f"{ld.tare_kg:,}",
        "net_kg": f"{ld.net_kg:,}",
        "weighmaster": ld.weighmaster,
        "driver_signature": ld.truck.driver,
    }


def build_documents(world: World, rng: random.Random, loads: list[Load]) -> tuple[list[Document], list[dict]]:
    """Ticket photos get phone-style file names, so nothing but their content links them to a load."""
    pending: list[tuple[str, str, dict, list]] = []
    duplicates = []
    for ld in loads:
        if ld.planted == "P8":  # dispatched, but no ticket ever came back
            continue
        fields, illegible = _haul_fields(world, ld, rng)
        pending.append((ld.load_id, "haul", fields, illegible))
        pending.append((ld.load_id, "scale", _scale_fields(world, ld), []))
        if ld.planted == "P4":  # the same ticket photographed and submitted again
            pending.append((ld.load_id, "haul", dict(fields), list(illegible)))
    names = rng.sample(range(1000, 9999), len(pending))
    docs, seen = [], set()
    for (load_id, kind, fields, illegible), n in zip(pending, names):
        doc = Document(f"IMG_{n}.jpg", kind, load_id, fields, illegible)
        if kind == "haul" and (load_id, kind) in seen:
            duplicates.append({"file": doc.file, "load_id": load_id, "outcome": "exception",
                               "reasons": ["DUPLICATE_TICKET"]})
        seen.add((load_id, kind))
        docs.append(doc)
    return sorted(docs, key=lambda d: d.file), duplicates


def make_batch(name: str, seed: int, world: World, days: list[date], target: int, mode: str) -> Batch:
    rng = random.Random(f"{seed}:{name}:loads")
    loads = schedule(world, rng, days, target)
    plant(world, rng, loads, mode)
    docs, duplicates = build_documents(world, rng, loads)
    return Batch(name, seed, world, loads, docs, duplicates)
