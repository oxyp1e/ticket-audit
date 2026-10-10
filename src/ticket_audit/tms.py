"""TMS adapter. The stand-in is a SQLite file; a real TMS would sit behind the same function."""
import sqlite3
from datetime import date
from pathlib import Path

from ticket_audit.domain.model import Customer, DispatchRecord, Lease, RateRow, Reference
from ticket_audit.domain.normalize import key


def load_reference(path: Path) -> Reference:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        q = lambda sql: db.execute(sql).fetchall()
        dispatch = tuple(
            DispatchRecord(no, date.fromisoformat(d), unit, cust, pit, lease, product, planned)
            for no, d, unit, cust, pit, lease, product, planned in q(
                "SELECT dispatch_no, date, unit, customer_code, pit_code, lease_code, product, planned_t "
                "FROM dispatch ORDER BY dispatch_no")
        )
        rates = tuple(
            RateRow(c, p, l, pt, sb, ft, date.fromisoformat(ef), date.fromisoformat(et) if et else None)
            for c, p, l, pt, sb, ft, ef, et in q(
                "SELECT customer_code, pit_code, lease_code, per_tonne, standby_per_h, free_time_h, "
                "effective_from, effective_to FROM rates ORDER BY customer_code, pit_code, lease_code, effective_from")
        )
        customers = {c: Customer(c, n, po) for c, n, po in q("SELECT code, name, po FROM customers")}
        aliases = {key(a): c for a, c in q("SELECT alias, customer_code FROM customer_aliases")}
        leases = {c: Lease(c, cc, n, lsd, afe) for c, cc, n, lsd, afe in
                  q("SELECT code, customer_code, name, lsd, afe FROM leases")}
        pits = dict(q("SELECT code, name FROM pits"))
    finally:
        db.close()
    return Reference(dispatch, rates, customers, aliases, leases, pits)
