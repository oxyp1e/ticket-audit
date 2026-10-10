"""The decision engine. Pure and deterministic: same inputs, same decisions, every run.

Approval needs every check to pass. Anything uncertain, missing or inconsistent becomes an
exception with a plain reason (ADR 3). Thresholds and reason texts are data (CONFIG, REASONS),
and their hash is part of the rule version recorded on every decision.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ticket_audit.domain.model import (
    Decision, DispatchRecord, HaulTicket, InvoiceLine, RateRow, Reason, Reference, ScaleTicket,
)
from ticket_audit.domain.normalize import key

CONFIG = {
    "weight_tolerance_t": 0.05,         # haul-ticket net vs scale net
    "scale_balance_tolerance_kg": 10,   # gross - tare vs printed net
    "standby_tolerance_h": 0.25,        # written standby vs time on site
    # Money and identity fields need this confidence even when another record agrees. The one
    # exception: printed scale weights that balance (gross - tare = net), see _corroborated.
    "min_confidence_critical": 0.90,
    "critical_fields": ["ticket_no", "net_t", "gross_kg", "tare_kg", "net_kg"],
    # Other fields need this, unless an independent record confirms the value exactly
    # (master data, dispatch, the scale ticket): the agreement is stronger evidence than OCR confidence.
    "min_confidence": 0.80,
    # Read but not used by any rule: their confidence doesn't matter.
    "unused_fields": ["trailer", "driver", "receiver_name", "receiver_signature", "carrier", "weighmaster",
                      "driver_signature", "time_in", "time_out", "pit", "scale_house"],
}

# Every reason the engine can give. Exceptions block approval; STANDBY_RECOVERED adjusts the line.
REASONS = {
    "DUPLICATE_TICKET": "Ticket already submitted",
    "WEIGHT_MISMATCH": "Net weight differs from the scale ticket",
    "SCALE_INCONSISTENT": "Scale ticket gross minus tare does not equal net",
    "SCALE_MISMATCH": "Scale ticket is for a different truck, date or product",
    "NO_SCALE_TICKET": "No scale ticket found for this load",
    "NO_SIGNATURE": "No receiver signature",
    "MISSING_COST_CODE": "No AFE / cost code",
    "COST_CODE_MISMATCH": "AFE / cost code does not match the lease",
    "MISSING_PO": "No PO number",
    "PO_MISMATCH": "PO number does not match the customer",
    "LOW_CONFIDENCE": "A critical value could not be read with confidence",
    "UNREADABLE_FIELD": "A required value is blank or unreadable",
    "UNKNOWN_CUSTOMER": "Customer not recognized",
    "UNKNOWN_ORIGIN": "Pit or terminal not recognized",
    "UNKNOWN_LEASE": "Lease not recognized",
    "INVALID_LSD": "Land description is not a valid DLS location",
    "LSD_MISMATCH": "Land description does not match the lease",
    "NO_DISPATCH_MATCH": "No dispatched load matches this ticket",
    "FALLBACK_MATCH": "Matched to dispatch without a load number; needs confirmation",
    "AMBIGUOUS_MATCH": "Several dispatched loads could match this ticket",
    "DISPATCH_MISMATCH": "Ticket disagrees with the dispatched load",
    "NO_RATE": "No rate on file for this customer and route",
    "RATE_EXPIRED": "The rate for this route had expired on the ticket date",
    "AMBIGUOUS_RATE": "More than one rate applies on the ticket date",
    "STANDBY_MISMATCH": "Written standby does not match time on site",
    "STANDBY_RECOVERED": "Standby earned but not written on the ticket; added to the invoice line",
    "MISSING_TICKET": "Load was dispatched but no ticket came back",
    "ORPHAN_SCALE_TICKET": "Scale ticket does not belong to any haul ticket",
    "UNREADABLE_DOCUMENT": "Document could not be identified as a haul or scale ticket",
    "DUPLICATE_FILE": "Identical file already submitted",
}
ADJUSTMENTS = {"STANDBY_RECOVERED"}

RULES_REVISION = "1.0"
RULE_VERSION = "rules-{}+{}".format(
    RULES_REVISION,
    hashlib.sha256(json.dumps([CONFIG, REASONS], sort_keys=True).encode()).hexdigest()[:8],
)


@dataclass(frozen=True)
class BatchResult:
    decisions: tuple[Decision, ...]

    @property
    def approved(self) -> list[Decision]:
        return [d for d in self.decisions if d.approved]

    @property
    def exceptions(self) -> list[Decision]:
        return [d for d in self.decisions if not d.approved]


def _r(code: str, detail: str = "") -> Reason:
    return Reason(code, f"{REASONS[code]}: {detail}" if detail else REASONS[code])


def _hours_on_site(arrive: time, depart: time) -> float:
    a = datetime.combine(date(2000, 1, 1), arrive)
    d = datetime.combine(date(2000, 1, 1), depart)
    if d < a:  # past midnight
        d += timedelta(days=1)
    return (d - a).total_seconds() / 3600


def billable_standby(arrive: time, depart: time, free_time_h: float) -> float:
    return round(max(0.0, _hours_on_site(arrive, depart) - free_time_h) * 4) / 4


def _low_confidence(conf: dict[str, float], corroborated: set[str], prefix: str) -> list[str]:
    low = []
    for name, c in sorted(conf.items()):
        if name in CONFIG["unused_fields"]:
            continue
        if name in CONFIG["critical_fields"] and name not in corroborated:
            floor = CONFIG["min_confidence_critical"]
        elif name in CONFIG["critical_fields"]:
            continue
        elif name in corroborated:
            continue
        else:
            floor = CONFIG["min_confidence"]
        if c < floor:
            low.append(f"{prefix}{name} ({c:.2f})")
    return low


def _corroborated(h: HaulTicket, s: ScaleTicket | None, d: DispatchRecord | None, lease, customer,
                  primary_match: bool, standby_ok: bool) -> tuple[set[str], set[str]]:
    """Fields whose value an independent record confirms exactly, for the haul and the scale ticket."""
    haul, scale = set(), set()
    if h.customer_code:
        haul.add("customer")
    if h.lease_code:
        haul.add("lease")
    if h.pit_code:
        haul.add("origin")
    if lease and h.lsd == lease.lsd:
        haul.add("lsd")
    if lease and h.afe and key(h.afe) == key(lease.afe):
        haul.add("afe")
    if customer and h.po and key(h.po) == key(customer.po):
        haul.add("po")
    if d and primary_match:
        haul.add("dispatch_no")
    if standby_ok:
        haul.add("standby_h")
    for name, value in (("date", h.date), ("unit", h.unit), ("product", h.product)):
        others = [getattr(d, name, None) if name != "product" else (key(d.product) if d else None),
                  getattr(s, name, None)]
        if value is not None and value in others:
            haul.add(name)
        if s is not None and getattr(s, name) is not None and getattr(s, name) == value:
            scale.add(name)
    if s is not None:
        haul.add("scale_ticket_no")
        scale.add("scale_ticket_no")
        if None not in (s.gross_kg, s.tare_kg, s.net_kg) and \
                abs(s.gross_kg - s.tare_kg - s.net_kg) <= CONFIG["scale_balance_tolerance_kg"]:
            scale |= {"gross_kg", "tare_kg", "net_kg"}  # printed and arithmetically consistent
    return haul, scale


def _match_dispatch(h: HaulTicket, by_no: dict[str, DispatchRecord], dispatch: tuple[DispatchRecord, ...],
                    claimed: set[str]) -> tuple[DispatchRecord | None, list[Reason]]:
    if h.dispatch_no and h.dispatch_no in by_no:
        return by_no[h.dispatch_no], []
    candidates = [d for d in dispatch
                  if d.dispatch_no not in claimed and d.date == h.date and d.unit == h.unit
                  and d.customer_code == h.customer_code and h.date is not None]
    written = f"load number {h.dispatch_no} is not in dispatch" if h.dispatch_no else "no load number written"
    if len(candidates) == 1:
        return candidates[0], [_r("FALLBACK_MATCH", f"{written}; date, unit and customer match {candidates[0].dispatch_no}")]
    if len(candidates) > 1:
        nos = ", ".join(d.dispatch_no for d in candidates)
        return None, [_r("AMBIGUOUS_MATCH", f"{written}; candidates {nos}")]
    return None, [_r("NO_DISPATCH_MATCH", f"{written}; no load for unit {h.unit} on {h.date} for this customer")]


def _dispatch_differences(h: HaulTicket, d: DispatchRecord) -> list[str]:
    pairs = [("date", h.date, d.date), ("unit", h.unit, d.unit), ("customer", h.customer_code, d.customer_code),
             ("origin", h.pit_code, d.pit_code), ("lease", h.lease_code, d.lease_code)]
    diffs = [f"{n} {a} vs {b}" for n, a, b in pairs if a is not None and a != b]
    if h.product and h.product != key(d.product):
        diffs.append(f"product {h.product} vs {key(d.product)}")
    return diffs


def _scale_checks(h: HaulTicket, s: ScaleTicket) -> list[Reason]:
    reasons = []
    if None not in (s.gross_kg, s.tare_kg, s.net_kg):
        if abs(s.gross_kg - s.tare_kg - s.net_kg) > CONFIG["scale_balance_tolerance_kg"]:
            reasons.append(_r("SCALE_INCONSISTENT", f"{s.gross_kg:,} - {s.tare_kg:,} != {s.net_kg:,} kg"))
    if h.net_t is not None and s.net_kg is not None:
        if abs(h.net_t - s.net_kg / 1000) > CONFIG["weight_tolerance_t"]:
            reasons.append(_r("WEIGHT_MISMATCH", f"{h.net_t:.2f} t on the ticket, {s.net_kg / 1000:.2f} t on "
                                                 f"scale ticket {s.scale_ticket_no}"))
    diffs = [f"{n} {a} vs {b}" for n, a, b in
             [("unit", h.unit, s.unit), ("date", h.date, s.date), ("product", h.product, s.product)]
             if a is not None and b is not None and a != b]
    if diffs:
        reasons.append(_r("SCALE_MISMATCH", "; ".join(diffs)))
    return reasons


def _find_rate(h: HaulTicket, customer: str | None, rates: tuple[RateRow, ...]) -> tuple[RateRow | None, list[Reason]]:
    lane = f"{customer}/{h.pit_code}/{h.lease_code}"
    rows = [r for r in rates if (r.customer_code, r.pit_code, r.lease_code) == (customer, h.pit_code, h.lease_code)]
    if not rows:
        return None, [_r("NO_RATE", lane)]
    if h.date is None:
        return None, []
    live = [r for r in rows if r.effective_from <= h.date and (r.effective_to is None or h.date <= r.effective_to)]
    if not live:
        ended = max((r.effective_to for r in rows if r.effective_to), default=None)
        return None, [_r("RATE_EXPIRED", f"{lane} ended {ended}, ticket dated {h.date}")]
    if len(live) > 1:
        return None, [_r("AMBIGUOUS_RATE", lane)]
    return live[0], []


def _decide_haul(h: HaulTicket, ref: Reference, scales: dict[str, ScaleTicket], by_no, claimed,
                 seen: dict[str, str]) -> Decision:
    reasons: list[Reason] = [_r(p.code, p.message) for p in h.problems]

    # Duplicates: the same ticket number, or a second ticket claiming the same scale ticket.
    first = (seen.get(f"t:{h.ticket_no}") if h.ticket_no else None) or \
            (seen.get(f"s:{h.scale_ticket_no}") if h.scale_ticket_no else None)
    if first:
        reasons.append(_r("DUPLICATE_TICKET", f"{h.ticket_no} was already submitted as {first}"))
    else:
        if h.ticket_no:
            seen[f"t:{h.ticket_no}"] = h.doc.file
        if h.scale_ticket_no:
            seen[f"s:{h.scale_ticket_no}"] = h.doc.file

    s = scales.get(h.scale_ticket_no) if h.scale_ticket_no else None
    if h.scale_ticket_no and s is None:
        reasons.append(_r("NO_SCALE_TICKET", f"scale ticket {h.scale_ticket_no} not received"))
    if s is not None:
        reasons += [_r(p.code, p.message) for p in s.problems]
        reasons += _scale_checks(h, s)

    if not h.signed:
        reasons.append(_r("NO_SIGNATURE"))
    lease = ref.leases.get(h.lease_code) if h.lease_code else None
    customer = ref.customers.get(h.customer_code) if h.customer_code else None
    if h.afe is None:
        reasons.append(_r("MISSING_COST_CODE"))
    elif lease and key(h.afe) != key(lease.afe):
        reasons.append(_r("COST_CODE_MISMATCH", f"{h.afe} vs {lease.afe} for {lease.name}"))
    if h.po is None:
        reasons.append(_r("MISSING_PO"))
    elif customer and key(h.po) != key(customer.po):
        reasons.append(_r("PO_MISMATCH", f"{h.po} vs {customer.po}"))

    primary_match = bool(h.dispatch_no and h.dispatch_no in by_no)
    d, match_reasons = _match_dispatch(h, by_no, ref.dispatch, claimed)
    reasons += match_reasons
    if d is not None:
        claimed.add(d.dispatch_no)
        diffs = _dispatch_differences(h, d)
        if diffs:
            reasons.append(_r("DISPATCH_MISMATCH", f"{d.dispatch_no}: " + "; ".join(diffs)))

    rate, rate_reasons = (None, [])
    if h.pit_code and h.lease_code and (h.customer_code or d):
        rate, rate_reasons = _find_rate(h, h.customer_code or d.customer_code, ref.rates)
    reasons += rate_reasons

    standby_h, recovered, standby_ok = h.standby_h or 0.0, False, False
    if rate and h.arrive and h.depart:
        earned = billable_standby(h.arrive, h.depart, rate.free_time_h)
        if h.standby_h is None and earned > 0:
            standby_h, recovered = earned, True
            reasons.append(_r("STANDBY_RECOVERED", f"{_hours_on_site(h.arrive, h.depart):.2f} h on site, "
                                                   f"{rate.free_time_h:g} h free, {earned:g} h billable"))
        elif h.standby_h is not None and abs(h.standby_h - earned) > CONFIG["standby_tolerance_h"]:
            reasons.append(_r("STANDBY_MISMATCH", f"{h.standby_h:g} h written, {earned:g} h by the times on the ticket"))
        elif h.standby_h is not None:
            standby_ok = True

    haul_ok, scale_ok = _corroborated(h, s, d, lease, customer, primary_match, standby_ok)
    low = _low_confidence(h.confidence, haul_ok, "")
    if s is not None:
        low += _low_confidence(s.confidence, scale_ok, "scale ")
    if low:
        reasons.append(_r("LOW_CONFIDENCE", ", ".join(low)))

    line = None
    if rate and h.net_t is not None and h.ticket_no and h.date:
        tonnage = round(h.net_t * rate.per_tonne, 2)
        standby_amount = round(standby_h * rate.standby_per_h, 2)
        line = InvoiceLine(h.ticket_no, h.date, rate.customer_code, d.dispatch_no if d else "", rate.pit_code,
                           rate.lease_code, d.product if d else (h.product or ""), h.net_t, rate.per_tonne,
                           tonnage, standby_h, rate.standby_per_h, standby_amount,
                           round(tonnage + standby_amount, 2), recovered)

    blocking = [r for r in reasons if r.code not in ADJUSTMENTS]
    if blocking or line is None or d is None:
        outcome = "exception"
    else:
        outcome = "approve_adjusted" if recovered else "approve"
    return Decision(h.doc.file, "haul", outcome, tuple(reasons), h.ticket_no, h, s, d, rate, line)


def decide(hauls: list[HaulTicket], scales: list[ScaleTicket], unreadable: list[str], ref: Reference,
           duplicate_files: dict[str, str] | None = None) -> BatchResult:
    """Decide a whole batch. Documents are taken in file order, so 'first submitted' is well defined."""
    hauls = sorted(hauls, key=lambda h: h.doc.file)
    scales = sorted(scales, key=lambda s: s.doc.file)
    by_scale_no: dict[str, ScaleTicket] = {}
    for s in scales:
        if s.scale_ticket_no:
            by_scale_no.setdefault(s.scale_ticket_no, s)
    by_no = {d.dispatch_no: d for d in ref.dispatch}

    # Exact load-number matches are claimed first, so a fallback can never steal a load.
    claimed = {h.dispatch_no for h in hauls if h.dispatch_no in by_no}
    seen: dict[str, str] = {}
    decisions = [_decide_haul(h, ref, by_scale_no, by_no, claimed, seen) for h in hauls]

    referenced = {h.scale_ticket_no for h in hauls}
    for s in scales:
        if s.scale_ticket_no not in referenced or by_scale_no.get(s.scale_ticket_no) is not s:
            decisions.append(Decision(s.doc.file, "orphan_scale", "exception",
                                      (_r("ORPHAN_SCALE_TICKET", f"scale ticket {s.scale_ticket_no}"),), scale=s))
    for d in sorted(ref.dispatch, key=lambda d: d.dispatch_no):
        if d.dispatch_no not in claimed:
            decisions.append(Decision(d.dispatch_no, "missing_ticket", "missing_ticket",
                                      (_r("MISSING_TICKET", f"{d.dispatch_no}, unit {d.unit}, {d.date}"),), dispatch=d))
    for f in sorted(unreadable):
        decisions.append(Decision(f, "unreadable", "exception", (_r("UNREADABLE_DOCUMENT"),)))
    for f, original in sorted((duplicate_files or {}).items()):
        decisions.append(Decision(f, "duplicate_file", "exception", (_r("DUPLICATE_FILE", f"identical to {original}"),)))
    return BatchResult(tuple(decisions))
