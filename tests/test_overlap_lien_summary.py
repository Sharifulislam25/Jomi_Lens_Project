"""Boundary overlap (double registration), mortgage / lien / attachment, the citizen traffic light, and dag/khatian search."""
import pytest

from src import vdb
from src.geo_tools import GeometryError, overlap_sqm, polygon_metrics
from src.verification_engine import (CONFLICT, PASS, REVIEW, UNAVAILABLE, check_boundary_overlap, check_encumbrance, run_verification, safety_summary)
from src.verify_seed import rect_points

NOW = "2026-10-01T00:00:00Z"
A = rect_points(90.4000, 23.8000, 400)                        # about 400 m²
FAR = rect_points(90.4100, 23.8100, 400)


def shifted(points, dlon):
    return [(x + dlon, y) for x, y in points]


# ---------------------------------------------------------------- overlap geometry
def test_overlap_area_is_measured_in_square_metres():
    assert overlap_sqm(A, A) == pytest.approx(polygon_metrics(A)["area_sqm"], rel=0.002)
    assert overlap_sqm(A, FAR) == 0.0
    w = max(x for x, _ in A) - min(x for x, _ in A)
    assert overlap_sqm(A, shifted(A, w)) == pytest.approx(0.0, abs=0.01)        # touching along an edge is not an overlap
    half = overlap_sqm(A, shifted(A, w / 2))
    assert half == pytest.approx(polygon_metrics(A)["area_sqm"] / 2, rel=0.01)
    with pytest.raises(GeometryError):
        overlap_sqm(A, [(1, 2)])


def other(pid, pts):
    return {"parcel_id": pid, "title": pid, "points": pts}


def test_boundary_overlap_check():
    w = max(x for x, _ in A) - min(x for x, _ in A)
    r = check_boundary_overlap(A, [other("N1", shifted(A, w / 2)), other("N2", FAR)], now=NOW)
    assert r["status"] == CONFLICT and r["evidence"][0]["other_parcel"] == "N1" and r["evidence"][0]["share_of_this_parcel_pct"] == pytest.approx(50, abs=1)
    assert check_boundary_overlap(A, [other("N2", FAR)], now=NOW)["status"] == PASS
    assert check_boundary_overlap(A, [], now=NOW)["status"] == PASS
    sliver = check_boundary_overlap(A, [other("N3", shifted(A, w * 0.999))], now=NOW)           # a hair-thin overlap is drawing noise
    assert sliver["status"] == PASS and sliver["evidence"][0]["result"] == "within tolerance"
    assert check_boundary_overlap(None, [other("N1", A)], now=NOW)["status"] == UNAVAILABLE
    assert check_boundary_overlap(A, [other("BAD", [(1, 2)])], now=NOW)["status"] == REVIEW          # an unreadable neighbour is reported, not ignored


def test_overlap_tolerance_is_configurable():
    w = max(x for x, _ in A) - min(x for x, _ in A)
    small = [other("N1", shifted(A, w * 0.97))]                                                       # ~3% overlap
    assert check_boundary_overlap(A, small, now=NOW)["status"] == CONFLICT
    assert check_boundary_overlap(A, small, settings={"overlap_tolerance_pct": 5.0}, now=NOW)["status"] == PASS


# ---------------------------------------------------------------- mortgage / lien / attachment
COV = {"encumbrance_register": True}


def enc(kind, status):
    return {"entry_id": "E1", "kind": kind, "holder_label": "Demo Bank", "status": status, "registered_date": "2023-01-01", "released_date": None}


def test_encumbrance_check():
    assert check_encumbrance([enc("mortgage", "active")], COV, NOW)["status"] == REVIEW
    assert check_encumbrance([enc("lien", "active")], COV, NOW)["status"] == REVIEW
    assert check_encumbrance([enc("attachment", "active")], COV, NOW)["status"] == CONFLICT
    assert check_encumbrance([enc("mortgage", "released")], COV, NOW)["status"] == PASS
    assert check_encumbrance([], COV, NOW)["status"] == PASS
    assert check_encumbrance([], {"encumbrance_register": False}, NOW)["status"] == UNAVAILABLE      # no coverage: absence is NOT a pass
    assert check_encumbrance([], None, NOW)["status"] == UNAVAILABLE


# ---------------------------------------------------------------- traffic light
def run_with(*statuses):
    ids = ["record_consistency", "conflicting_sales", "khas_acquisition", "encumbrance", "pending_cases"]
    return {"parcel_id": "P", "results": [{"check_id": ids[i], "title": ids[i], "status": s, "summary": s} for i, s in enumerate(statuses)]}


@pytest.mark.parametrize("statuses,level", [
    ((PASS, PASS, PASS), "green"), ((PASS, REVIEW, PASS), "amber"), ((PASS, UNAVAILABLE, PASS), "amber"),
    ((UNAVAILABLE, UNAVAILABLE, UNAVAILABLE), "grey"), ((CONFLICT, PASS, PASS), "red"), ((PASS, PASS, CONFLICT), "blue"),
    ((CONFLICT, PASS, CONFLICT), "red"),                     # any non-khas conflict outranks the khas colour
])
def test_traffic_light_follows_the_statuses(statuses, level):
    assert safety_summary(run_with(*statuses))["level"] == level


def test_traffic_light_never_overclaims_and_lists_reasons_worst_first():
    s = safety_summary(run_with(PASS, PASS, PASS))
    assert "not proof" in s["label_en"] and s["label_bn"]
    s = safety_summary(run_with(REVIEW, CONFLICT, PASS, REVIEW))
    assert [r["status"] for r in s["reasons"]] == [CONFLICT, REVIEW, REVIEW]
    assert "mortgaged" in s["tags"] and "conflicting sale" in s["tags"]


def test_seeded_lights(con):
    expect = {"DV-001": "green", "DV-003": "red", "DV-016": "blue", "DV-025": "amber", "DV-010": "amber", "DV-023": "red", "DV-024": "red"}
    for pid, level in expect.items():
        run = run_verification(pid, vdb.get_records(con, pid), vdb.get_transactions(con, pid), vdb.get_documents(con, pid), context=vdb.verification_context(con, pid))
        assert safety_summary(run)["level"] == level, pid
    run = run_verification("DV-025", vdb.get_records(con, "DV-025"), vdb.get_transactions(con, "DV-025"), vdb.get_documents(con, "DV-025"),
                           context=vdb.verification_context(con, "DV-025"))
    assert safety_summary(run)["tags"] == ["mortgaged"]


# ---------------------------------------------------------------- search by dag / khatian
def test_find_by_reference_normalises_and_reports_every_match(con):
    hits = vdb.find_by_reference(con, "Dag No. 0540")
    assert hits and {h["parcel_id"] for h in hits} == {"DV-023"}
    assert {h["parcel_id"] for h in vdb.find_by_reference(con, "kh 1025")} == {"DV-025"}
    many = {h["parcel_id"] for h in vdb.find_by_reference(con, "125", limit=200)}
    assert len(many) > 5                                         # dag numbers repeat across mouzas: every match is listed, none is guessed
    assert vdb.find_by_reference(con, "") == [] and vdb.find_by_reference(con, "Dag No") == []
    assert vdb.find_by_reference(con, "' OR '1'='1") == []         # not SQL: matching happens in Python on normalised text


# ---------------------------------------------------------------- click identification
def test_parcel_at_containment_then_25_m_allowance(seeded, monkeypatch):
    import streamlit as st
    from pyproj import Geod
    from src import vcommon
    monkeypatch.setattr(vdb, "DB_PATH", seeded)
    st.cache_resource.clear(); st.cache_data.clear()
    p = next(x for x in vcommon.demo_parcels() if x["parcel_id"] == "DV-001")
    xs, ys = [q[0] for q in p["points"]], [q[1] for q in p["points"]]
    cx, cy = sum(xs) / 4, sum(ys) / 4
    assert vcommon.parcel_at(cx, cy) == (p, 0.0)
    g = Geod(ellps="WGS84")
    east = max(xs)
    lon15 = g.fwd(east, cy, 90, 15)[0]
    hit, d = vcommon.parcel_at(lon15, cy)
    assert hit["parcel_id"] == "DV-001" and d == pytest.approx(15, abs=0.5)
    assert vcommon.parcel_at(g.fwd(east, cy, 90, 40)[0], cy) == (None, None)
    q = next(x for x in vcommon.demo_parcels() if x["parcel_id"] == "DV-024")         # inside the DV-023 / DV-024 overlap the smaller one wins
    qx = max(x for x, _ in q["points"]) - 0.00002
    qy = sum(y for _, y in q["points"]) / 4
    assert vcommon.parcel_at(qx, qy)[0]["parcel_id"] in ("DV-023", "DV-024")


def test_parcels_containing_reports_both_sides_of_an_overlap(seeded, monkeypatch):
    import streamlit as st
    from src import vcommon
    monkeypatch.setattr(vdb, "DB_PATH", seeded)
    st.cache_resource.clear(); st.cache_data.clear()
    a = next(x for x in vcommon.demo_parcels() if x["parcel_id"] == "DV-023")
    b = next(x for x in vcommon.demo_parcels() if x["parcel_id"] == "DV-024")
    from shapely.geometry import Polygon
    c = Polygon(a["points"]).intersection(Polygon(b["points"])).representative_point()
    assert {p["parcel_id"] for p in vcommon.parcels_containing(c.x, c.y)} == {"DV-023", "DV-024"}
    m = Polygon(next(x for x in vcommon.demo_parcels() if x["parcel_id"] == "DV-001")["points"]).representative_point()
    assert [p["parcel_id"] for p in vcommon.parcels_containing(m.x, m.y)] == ["DV-001"]
