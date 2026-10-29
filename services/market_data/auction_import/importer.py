"""Generic batch CSV/XLSX import. Exact fields only, no price or identity inference."""
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from ..observations.models import Candidate, utcnow
from uuid import uuid4


def rows_from(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream)
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = book.active.iter_rows(values_only=True)
            headers = next(rows, ())
            if not headers or len(set(headers)) != len(headers):
                raise ValueError("Unique column headers required")
            for values in rows:
                if any(v is not None for v in values):
                    yield dict(zip(headers, values))
        finally:
            book.close()
    else:
        raise ValueError("Use CSV or XLSX")


def sale_timestamp(value):
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    text = str(value)
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), datetime.min.time(), timezone.utc).isoformat()
    return text


def candidates(row, source_id):
    reference = row.get("source_reference") or row.get("lot")
    if not reference or not row.get("sale_date"):
        raise ValueError("Source reference/lot and sale_date required")
    evidence = {str(k): (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()}
    identity = {k: row.get(k) for k in ("producer", "wine", "vintage", "bottle_ml", "quantity",
                                       "format", "release", "edition", "market", "tax_status")}
    emitted = []
    for column, kind in (("hammer", "AUCTION_HAMMER"), ("all_in_price", "AUCTION_ALL_IN")):
        value = row.get(column)
        if value is None or str(value).strip() == "":
            continue
        # Hammer and all-in are totals for the lot: resolver must confirm lot quantity.
        c = Candidate(source_id=source_id, source_type="AUCTION", price=Decimal(str(value)),
                      currency=str(row.get("currency", "")), price_basis="PACK", price_type=kind,
                      observed_at=sale_timestamp(row["sale_date"]), source_reference=str(reference),
                      source_url=row.get("source_url"), raw_evidence=evidence,
                      identity={**identity, "currency": row.get("currency")})
        c.validate()
        emitted.append(c)
    if not emitted:
        raise ValueError("No supplied hammer or all-in price")
    return emitted


def import_auction(store, path, source_id):
    run_id = str(uuid4())
    written = rejected = duplicates = 0
    errors = []
    status = "SUCCEEDED"
    with store.connection() as db:
        db.execute("INSERT INTO source_runs(run_id,source,started_at,status) VALUES (?,?,?,'RUNNING')",
                   (run_id, source_id, utcnow().isoformat()))
    try:
        for number, row in enumerate(rows_from(path), 2):
            try:
                items = candidates(row, source_id)
                for item in items:
                    if store.ingest(item):
                        written += 1
                    else:
                        duplicates += 1
            except (ValueError, TypeError, ArithmeticError):
                rejected += 1
                errors.append({"row": number, "error": "Invalid evidence or canonical resolution; inspect original row"})
        if rejected:
            status = "PARTIAL"
    except Exception:
        status = "FAILED"
        errors.append({"error": "Import file could not be read"})
    with store.connection() as db:
        db.execute('''UPDATE source_runs SET finished_at=?,status=?,observations_written=?,
                      observations_rejected=?,error=? WHERE run_id=?''',
                   (utcnow().isoformat(), status, written, rejected,
                    "Some input rows rejected" if errors else None, run_id))
    return {"run_id": run_id, "status": status, "written": written, "rejected": rejected,
            "duplicates": duplicates, "errors": errors}
