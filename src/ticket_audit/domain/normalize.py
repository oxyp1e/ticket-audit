"""Raw extracted text -> typed tickets. Pure functions: master data is passed in, nothing is read.

Anything that can't be parsed or resolved becomes a Problem on the ticket; the rules turn
problems into exceptions. Normalization never guesses a value.
"""
import re
from datetime import date, datetime, time

from ticket_audit.domain.lsd import is_valid_lsd
from ticket_audit.domain.model import Doc, Extraction, HaulTicket, Problem, Reference, ScaleTicket

DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%b %d %Y", "%b %d/%y")

# Fields a haul ticket must carry. Blank optional fields are judged by specific rules
# (dispatch number, AFE, PO, signature, standby).
HAUL_REQUIRED = ("ticket_no", "date", "unit", "customer", "origin", "scale_ticket_no",
                 "lease", "lsd", "product", "net_t", "arrive", "depart")
SCALE_REQUIRED = ("scale_ticket_no", "date", "unit", "product", "gross_kg", "tare_kg", "net_kg")


def key(text: str) -> str:
    """Comparison key for names: case, spacing and punctuation don't matter."""
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def parse_date(text: str) -> date | None:
    text = re.sub(r"\s*([-/])\s*", r"\1", text.strip())  # "2026- 10-01" -> "2026-10-01"
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(text: str) -> time | None:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", text)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        return None
    return time(int(m[1]), int(m[2]))


def parse_number(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_lsd(text: str) -> str:
    """Undo common OCR confusions in a DLS location, then zero-pad. Validity is checked separately."""
    t = re.sub(r"\s+", "", text.upper())
    t = re.sub(r"W[S$]$", "W5", t)
    t = re.sub(r"W[GbE]$", "W6", t)
    head, sep, mer = t.rpartition("W")
    head = head.translate(str.maketrans("OIL", "011"))
    parts = head.split("-")
    if sep and len(parts) == 4 and all(p.isdigit() for p in parts):
        widths = (2, 2, 3, 2)
        head = "-".join(p.zfill(w) for p, w in zip(parts, widths))
    return f"{head}{sep}{mer}"


def _digits(text: str) -> str | None:
    """The ticket number is the first run of digits; anything after it belongs to another field."""
    m = re.search(r"\d{4,}", text.replace(" ", ""))
    return m.group() if m else None


def _ident(text: str) -> str:
    return re.sub(r"\s+", "", text.upper())


def _doc(e: Extraction) -> Doc:
    return Doc(e.file, e.sha256, e.engine, e.model_version)


def normalize_haul(e: Extraction, ref: Reference) -> HaulTicket:
    f = {k: v.value.strip() for k, v in e.fields.items() if v.value.strip()}
    conf = {k: v.confidence for k, v in e.fields.items() if v.value.strip()}
    problems: list[Problem] = []

    for name in HAUL_REQUIRED:
        if name not in f:
            problems.append(Problem("UNREADABLE_FIELD", f"Required field '{name}' is blank or unreadable"))

    def parsed(name, parser, label):
        if name not in f:
            return None
        value = parser(f[name])
        if value is None:
            problems.append(Problem("UNREADABLE_FIELD", f"{label} '{f[name]}' could not be read"))
        return value

    customer_code = None
    if "customer" in f:
        customer_code = ref.aliases.get(key(f["customer"]))
        if customer_code is None:
            problems.append(Problem("UNKNOWN_CUSTOMER", f"Customer '{f['customer']}' is not in the customer list"))

    pit_code = None
    if "origin" in f:
        pit_code = next((c for c, name in ref.pits.items() if key(name) == key(f["origin"])), None)
        if pit_code is None:
            problems.append(Problem("UNKNOWN_ORIGIN", f"Origin '{f['origin']}' is not a known pit or terminal"))

    lsd = None
    if "lsd" in f:
        lsd = normalize_lsd(f["lsd"])
        if not is_valid_lsd(lsd):
            problems.append(Problem("INVALID_LSD", f"Land description '{f['lsd']}' is not a valid DLS location"))
            lsd = None

    lease_code = None
    if "lease" in f:
        by_name = next((l.code for l in ref.leases.values() if key(l.name) == key(f["lease"])), None)
        by_lsd = next((l.code for l in ref.leases.values() if l.lsd == lsd), None) if lsd else None
        if by_name and by_lsd and by_name != by_lsd:
            problems.append(Problem("LSD_MISMATCH", f"Lease '{f['lease']}' is not at {lsd}"))
        lease_code = by_name or by_lsd
        if lease_code is None:
            problems.append(Problem("UNKNOWN_LEASE", f"Lease '{f['lease']}' is not in the lease list"))

    standby = None
    if "standby_h" in f:
        standby = parsed("standby_h", parse_number, "Standby hours")

    return HaulTicket(
        doc=_doc(e),
        ticket_no=_ident(f["ticket_no"]) if "ticket_no" in f else None,
        dispatch_no=_ident(f["dispatch_no"]) if "dispatch_no" in f else None,
        date=parsed("date", parse_date, "Date"),
        unit=_ident(f["unit"]) if "unit" in f else None,
        trailer=_ident(f["trailer"]) if "trailer" in f else None,
        customer_code=customer_code,
        po=_ident(f["po"]) if "po" in f else None,
        afe=f["afe"].upper() if "afe" in f else None,
        pit_code=pit_code,
        scale_ticket_no=_digits(f["scale_ticket_no"]) if "scale_ticket_no" in f else None,
        lease_code=lease_code,
        lsd=lsd,
        product=key(f["product"]) if "product" in f else None,
        net_t=parsed("net_t", parse_number, "Net weight"),
        arrive=parsed("arrive", parse_time, "Arrival time"),
        depart=parsed("depart", parse_time, "Departure time"),
        standby_h=standby,
        receiver_name=f.get("receiver_name"),
        signed="receiver_signature" in f,
        confidence=conf,
        problems=tuple(problems),
    )


def normalize_scale(e: Extraction) -> ScaleTicket:
    f = {k: v.value.strip() for k, v in e.fields.items() if v.value.strip()}
    conf = {k: v.confidence for k, v in e.fields.items() if v.value.strip()}
    problems = [Problem("UNREADABLE_FIELD", f"Required field '{n}' is blank or unreadable")
                for n in SCALE_REQUIRED if n not in f]

    def kg(name):
        if name not in f:
            return None
        v = parse_number(f[name])
        if v is None:
            problems.append(Problem("UNREADABLE_FIELD", f"Scale {name} '{f[name]}' could not be read"))
            return None
        return int(round(v))

    day = parse_date(f["date"]) if "date" in f else None
    if "date" in f and day is None:
        problems.append(Problem("UNREADABLE_FIELD", f"Scale date '{f['date']}' could not be read"))
    return ScaleTicket(
        doc=_doc(e),
        scale_ticket_no=_digits(f["scale_ticket_no"]) if "scale_ticket_no" in f else None,
        date=day,
        unit=_ident(f["unit"]) if "unit" in f else None,
        product=key(f["product"]) if "product" in f else None,
        gross_kg=kg("gross_kg"),
        tare_kg=kg("tare_kg"),
        net_kg=kg("net_kg"),
        confidence=conf,
        problems=tuple(problems),
    )
