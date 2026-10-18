"""CSV export that is safe to open in Excel/LibreOffice: a cell that starts with = + - @ (or a tab / carriage return) is
prefixed with ' so the spreadsheet shows it as text instead of running it as a formula (CSV formula injection)."""
import csv
import io

_DANGER = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    if v is None:
        return ""
    s = str(v)
    if s.startswith(_DANGER) and not _is_number(s):
        return "'" + s
    return s


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def to_csv(rows: list, columns=None) -> bytes:
    cols = columns or (list(rows[0].keys()) if rows else [])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([safe_cell(r.get(c)) for c in cols])
    return buf.getvalue().encode("utf-8-sig")
