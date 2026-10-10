"""Types that flow through the pipeline. No I/O here: the decision functions only see these."""
from dataclasses import dataclass, field
from datetime import date, time


# ── Extraction (what an engine read off a document) ──────────────────────────
@dataclass(frozen=True)
class Field:
    value: str
    confidence: float


@dataclass(frozen=True)
class Extraction:
    file: str
    sha256: str
    kind: str  # "haul" | "scale" | "unknown"
    fields: dict[str, Field]
    engine: str
    model_version: str


@dataclass(frozen=True)
class Doc:
    """Provenance of one source document."""
    file: str
    sha256: str
    engine: str
    model_version: str


@dataclass(frozen=True)
class Problem:
    code: str
    message: str


# ── Normalized documents ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class HaulTicket:
    doc: Doc
    ticket_no: str | None
    dispatch_no: str | None
    date: date | None
    unit: str | None
    trailer: str | None
    customer_code: str | None
    po: str | None
    afe: str | None
    pit_code: str | None
    scale_ticket_no: str | None
    lease_code: str | None
    lsd: str | None
    product: str | None
    net_t: float | None
    arrive: time | None
    depart: time | None
    standby_h: float | None  # None = left blank
    receiver_name: str | None
    signed: bool
    confidence: dict[str, float] = field(default_factory=dict)
    problems: tuple[Problem, ...] = ()


@dataclass(frozen=True)
class ScaleTicket:
    doc: Doc
    scale_ticket_no: str | None
    date: date | None
    unit: str | None
    product: str | None
    gross_kg: int | None
    tare_kg: int | None
    net_kg: int | None
    confidence: dict[str, float] = field(default_factory=dict)
    problems: tuple[Problem, ...] = ()


# ── Reference data (the TMS) ─────────────────────────────────────────────────
@dataclass(frozen=True)
class DispatchRecord:
    dispatch_no: str
    date: date
    unit: str
    customer_code: str
    pit_code: str
    lease_code: str
    product: str
    planned_t: float


@dataclass(frozen=True)
class RateRow:
    customer_code: str
    pit_code: str
    lease_code: str
    per_tonne: float
    standby_per_h: float
    free_time_h: float
    effective_from: date
    effective_to: date | None

    @property
    def key(self) -> str:
        return f"{self.customer_code}/{self.pit_code}/{self.lease_code}@{self.effective_from.isoformat()}"


@dataclass(frozen=True)
class Customer:
    code: str
    name: str
    po: str


@dataclass(frozen=True)
class Lease:
    code: str
    customer_code: str
    name: str
    lsd: str
    afe: str


@dataclass(frozen=True)
class Reference:
    dispatch: tuple[DispatchRecord, ...]
    rates: tuple[RateRow, ...]
    customers: dict[str, Customer]
    aliases: dict[str, str]  # normalized alias -> customer code
    leases: dict[str, Lease]
    pits: dict[str, str]  # code -> name


# ── Decisions ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Reason:
    code: str
    message: str


@dataclass(frozen=True)
class InvoiceLine:
    ticket_no: str
    date: date
    customer_code: str
    dispatch_no: str
    pit_code: str
    lease_code: str
    product: str
    net_t: float
    per_tonne: float
    tonnage_amount: float
    standby_h: float
    standby_per_h: float
    standby_amount: float
    total: float
    standby_recovered: bool


@dataclass(frozen=True)
class Decision:
    subject: str  # the source file (or dispatch number, for a missing ticket)
    kind: str  # "haul" | "missing_ticket" | "orphan_scale" | "unreadable" | "duplicate_file"
    outcome: str  # "approve" | "approve_adjusted" | "exception" | "missing_ticket"
    reasons: tuple[Reason, ...]
    ticket_no: str | None = None
    haul: HaulTicket | None = None
    scale: ScaleTicket | None = None
    dispatch: DispatchRecord | None = None
    rate: RateRow | None = None
    line: InvoiceLine | None = None  # also set for exceptions when the amount is computable ("at stake")

    @property
    def approved(self) -> bool:
        return self.outcome in ("approve", "approve_adjusted")

    @property
    def reason_codes(self) -> list[str]:
        return [r.code for r in self.reasons]
