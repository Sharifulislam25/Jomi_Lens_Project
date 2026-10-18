"""Admin GIS tools: correct a parcel's corner coordinates, move it, digitise a new parcel, retire a parcel.

Rules (each is enforced here, not only in the UI):
- the outline must be a valid polygon (3+ corners, no self-crossing) inside Gazipur Sadar upazila;
- an edit may not create NEW overlap with another parcel beyond OVERLAP_TOLERANCE_M2 (the demo scenarios that overlap
  on purpose, such as DV-023/DV-024, keep their existing overlap but an edit cannot make it bigger);
- area and perimeter are recalculated; the old and new outline go to the audit log, so every change can be traced and undone.
Editing an outline does NOT change any record or signed document: the verification checks will compare the new outline against them."""
import json
import math

from shapely.geometry import Point, Polygon

from src import vdb
from src.geo_tools import GeometryError, overlap_sqm, polygon_metrics, validate_polygon
from src.privacy import personal_data_reason

OVERLAP_TOLERANCE_M2 = 1.0
MAX_SHIFT_M = 500.0


class EditError(Exception):
    pass


def _inside_upazila(points) -> bool:
    from src.places import upazila_polygon
    return upazila_polygon().contains(Polygon(points))


def shift_points(points, east_m: float, north_m: float) -> list:
    """Move every corner by a distance in metres (east/north; negative = west/south)."""
    if abs(east_m) > MAX_SHIFT_M or abs(north_m) > MAX_SHIFT_M:
        raise EditError(f"Move at most {MAX_SHIFT_M:.0f} m at a time.")
    lat0 = sum(p[1] for p in points) / len(points)
    dlat = north_m / 111_320.0
    dlon = east_m / (111_320.0 * math.cos(math.radians(lat0)))
    return [(round(x + dlon, 7), round(y + dlat, 7)) for x, y in points]


def check_outline(con, points, parcel_id=None) -> dict:
    """Validate an outline for parcel_id (None for a new parcel). Returns metrics + overlap report or raises EditError."""
    try:
        pts = validate_polygon(points)
        m = polygon_metrics(pts)
    except GeometryError as exc:
        raise EditError(str(exc)) from exc
    if not _inside_upazila(pts):
        raise EditError("The outline must be inside Gazipur Sadar upazila.")
    old = vdb.get_parcel(con, parcel_id) if parcel_id else None
    old_pts = vdb.parcel_points(old) if old else None
    problems, overlaps = [], []
    for other in vdb.list_parcels(con):
        if other["parcel_id"] == parcel_id:
            continue
        op = vdb.parcel_points(other)
        after = overlap_sqm(pts, op)
        before = overlap_sqm(old_pts, op) if old_pts else 0.0
        if after > 0:
            overlaps.append({"parcel_id": other["parcel_id"], "before_m2": round(before, 1), "after_m2": round(after, 1)})
        if after > max(before, 0.0) + OVERLAP_TOLERANCE_M2:
            problems.append(f"{other['parcel_id']} ({after:.1f} m² shared, was {before:.1f} m²)")
    if problems:
        raise EditError("The new outline would overlap another parcel more than before: " + "; ".join(problems) + ". Adjust the corners.")
    return {"points": pts, "metrics": m, "overlaps": overlaps}


def _geojson(pts) -> str:
    return json.dumps({"type": "Polygon", "coordinates": [[list(p) for p in pts] + [list(pts[0])]]})


def update_outline(con, admin, parcel_id, points, reason: str) -> dict:
    p = vdb.get_parcel(con, parcel_id)
    if not p:
        raise EditError("No such parcel.")
    why = (reason or "").strip()
    if len(why) < 5:
        raise EditError("Write a short reason for the change (at least 5 characters); it goes in the audit log.")
    if personal_data_reason(why):
        raise EditError("The reason looks like it contains personal data.")
    chk = check_outline(con, points, parcel_id)
    pts, m = chk["points"], chk["metrics"]
    old_pts = vdb.parcel_points(p)
    con.execute("UPDATE parcels SET geometry_geojson = ?, area_calculated = ?, perimeter_calculated = ?, updated_at = ? WHERE parcel_id = ?",
                (_geojson(pts), m["area_sqm"], m["perimeter_m"], vdb.utcnow(), parcel_id))
    con.commit()
    vdb.audit(con, admin["username"], "admin", "parcel_outline_edit", parcel_id,
              {"reason": why[:200], "old": [list(x) for x in old_pts], "new": [list(x) for x in pts],
               "old_area_sqm": round(p["area_calculated"] or 0, 1), "new_area_sqm": round(m["area_sqm"], 1)})
    return chk


def next_parcel_id(con) -> str:
    n = 0
    for (pid,) in con.execute("SELECT parcel_id FROM parcels WHERE parcel_id LIKE 'JL-%'"):
        try:
            n = max(n, int(pid[3:]))
        except ValueError:
            pass
    return f"JL-{n + 1:04d}"


def create_parcel(con, admin, points, title, mouza, asking_price_bdt=None) -> str:
    t, mz = (title or "").strip()[:80], (mouza or "").strip()[:40]
    if len(t) < 3 or not mz:
        raise EditError("Give the parcel a title (3+ characters) and a mouza.")
    if personal_data_reason(t) or personal_data_reason(mz):
        raise EditError("Title or mouza looks like personal data.")
    if asking_price_bdt is not None and not (0 <= int(asking_price_bdt) <= 10_000_000_000):
        raise EditError("The price is out of range.")
    chk = check_outline(con, points)
    pts, m = chk["points"], chk["metrics"]
    pid = next_parcel_id(con)
    now = vdb.utcnow()
    con.execute("INSERT INTO parcels(parcel_id,geometry_geojson,area_calculated,area_unit,perimeter_calculated,boundary_type,boundary_source,boundary_source_date,"
                "administrative_area,is_synthetic,created_at,updated_at,scenario_code,scenario_title,scenario_description,expected_overall,mouza,asking_price_bdt,"
                "created_by,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, _geojson(pts), m["area_sqm"], "sqm", m["perimeter_m"], "user_drawn", f"Digitised by admin '{admin['username']}' in JomiLens (demo)",
                 now[:10], f"{mz}, Gazipur Sadar, Gazipur (demo label)", 1, now, now, None, t,
                 "Parcel digitised by an administrator. No land records are linked yet, so most checks will say 'not available'.", None, mz,
                 None if asking_price_bdt is None else int(asking_price_bdt), admin["username"], "active"))
    con.commit()
    vdb.audit(con, admin["username"], "admin", "parcel_create", pid, {"title": t, "mouza": mz, "area_sqm": round(m["area_sqm"], 1), "points": [list(x) for x in pts]})
    return pid


def set_parcel_status(con, admin, parcel_id, status: str, reason: str):
    if status not in ("active", "retired"):
        raise EditError("Unknown status.")
    if not vdb.get_parcel(con, parcel_id):
        raise EditError("No such parcel.")
    if len((reason or "").strip()) < 5:
        raise EditError("Write a short reason (at least 5 characters).")
    con.execute("UPDATE parcels SET status = ?, updated_at = ? WHERE parcel_id = ?", (status, vdb.utcnow(), parcel_id))
    con.commit()
    vdb.audit(con, admin["username"], "admin", f"parcel_{status}", parcel_id, {"reason": reason.strip()[:200]})


def outline_history(con, parcel_id):
    return [dict(r) for r in con.execute("SELECT ts, actor, action, detail_json FROM audit_log WHERE target = ? AND action LIKE 'parcel_%' ORDER BY id DESC",
                                         (parcel_id,))]


def point_inside_upazila(lon, lat) -> bool:
    from src.places import upazila_polygon
    return upazila_polygon().contains(Point(lon, lat))
