"""Shared helpers for the JomiLens Verify pages."""
import json
from contextlib import closing

import streamlit as st

from src import i18n, vdb, vstate
from src.geo_tools import GeometryError, polygon_metrics
from src.verification_engine import CONFLICT, NOT_RUN, PASS, REVIEW, UNAVAILABLE

DISCLAIMER = "Prototype for demonstration only. Not an official land record, legal opinion, ownership certificate, or proof of title."   # PDF/report text (English)
SYNTH_NOTE = "All parcels, records, transactions and documents in the demo are SYNTHETIC (fictional). No real person or land record is shown."
BOUNDARY_LABELS = {
    "official_verified": ("Official boundary (authenticated source)", "#1b9e77"),
    "synthetic_demo": ("Synthetic demo parcel", "#d81b60"),
    "user_drawn": ("User-drawn polygon", "#1f78b4"),
    "approximate_feature": ("Approximate mapped feature (OpenStreetMap)", "#e07a5f"),
    "unknown": ("Unknown boundary type", "#777777")}
BADGE = {PASS: "green", REVIEW: "orange", CONFLICT: "red", UNAVAILABLE: "gray", NOT_RUN: "gray"}


def badge(status: str) -> str:
    return f":{BADGE.get(status, 'gray')}-badge[{i18n.status_text(status)}]"


@st.cache_resource
def db_path():
    return vdb.ensure_db()


def connect():
    return vdb.connect(db_path())


@st.cache_data(show_spinner=False)
def demo_parcels() -> list:
    """All synthetic demo parcels with geometry points and scenario text."""
    with closing(connect()) as con:
        rows = vdb.list_parcels(con)
    out = []
    for r in rows:
        ring = json.loads(r["geometry_geojson"])["coordinates"][0]
        out.append({**r, "points": [tuple(p) for p in ring][:-1]})
    return out


def parcel_label(p) -> str:
    return f"{p['parcel_id']} · {p.get('scenario_title') or 'Parcel'}"


def get_parcel(key):
    """Parcel dict for the current selection key, or None."""
    if not key:
        return None
    for p in demo_parcels():
        if p["parcel_id"] == key:
            return p
    c = st.session_state.get("vp_custom")
    return c if c and c.get("parcel_id") == key else None


def set_custom_parcel(parcel_id, points, boundary_type, source, label, admin=""):
    """Select a NON-database parcel (user-drawn or mapped feature). It is kept only in this browser session."""
    st.session_state["vp_custom"] = {"parcel_id": parcel_id, "points": [tuple(p) for p in points], "boundary_type": boundary_type,
                                     "boundary_source": source, "boundary_source_date": None, "administrative_area": admin,
                                     "is_synthetic": 0, "scenario_title": label, "scenario_description": "", "expected_overall": None}
    vstate.select_parcel(st.session_state, parcel_id)


def metrics_for(p):
    try:
        return polygon_metrics(p["points"]), None
    except GeometryError as exc:
        return None, str(exc)


def parcel_picker(key="vp_pick") -> dict:
    """Selectbox over demo parcels (+ the user's drawn plot / mapped feature if present). Keeps session results in sync."""
    parcels = demo_parcels()
    options = [p["parcel_id"] for p in parcels]
    labels = {p["parcel_id"]: parcel_label(p) for p in parcels}
    mp = st.session_state.get("mp_points")
    if mp:
        options.append("USER-DRAWN"); labels["USER-DRAWN"] = "USER-DRAWN · my drawn plot (from My Plot, this session only)"
    c = st.session_state.get("vp_custom")
    if c and c["parcel_id"] not in options:
        options.append(c["parcel_id"]); labels[c["parcel_id"]] = f"{c['parcel_id']} · {c['scenario_title']}"
    cur = vstate.current_key(st.session_state)
    if cur not in options:
        cur = options[0]
    choice = st.selectbox("Parcel", options, index=options.index(cur), format_func=lambda k: labels[k], key=key)
    if choice == "USER-DRAWN" and (not c or c["parcel_id"] != "USER-DRAWN" or c["points"] != [tuple(p) for p in mp]):
        set_custom_parcel("USER-DRAWN", mp, "user_drawn", "Drawn by the user in this session (not an official boundary)", "My drawn plot")
    else:
        vstate.select_parcel(st.session_state, choice)
    return get_parcel(choice)


def parcel_boundary_badge(p) -> str:
    label, _ = BOUNDARY_LABELS.get(p["boundary_type"], BOUNDARY_LABELS["unknown"])
    return label


def legend_html() -> str:
    rows = [("#d81b60", "Synthetic demo parcel (fictional, dashed outline)"), ("#1f78b4", "User-drawn polygon (My Plot / profile)"),
            ("#e07a5f", "Approximate mapped feature: building, land use, water (OpenStreetMap volunteers)"),
            ("#1b9e77", "Official verified boundary: NONE available in this prototype")]
    items = "".join(f"<div style='margin:2px 0'><span style='display:inline-block;width:14px;height:14px;background:{c};border-radius:3px;"
                    f"margin-right:8px;vertical-align:middle;{'opacity:.35' if c == '#1b9e77' else ''}'></span>{t}</div>" for c, t in rows)
    return f"<div style='font-size:.9rem'>{items}</div>"


def results_table(evidence) -> list:
    """Flatten evidence dicts into rows of strings for display."""
    rows = []
    for e in evidence:
        rows.append({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else ("" if v is None else str(v))) for k, v in e.items()})
    return rows


def reference_search(prefix: str, on_show=None):
    """Search box: find synthetic demo parcels by dag or khatian number (normalised, so 'Dag No. 0540' finds '540').
    Lists EVERY match (dag numbers repeat between mouzas and surveys) instead of guessing one. on_show(parcel) adds a 'Show on map' button."""
    from src.nav import PAGES
    q = st.text_input(i18n.t("find_ref"), key=f"{prefix}_ref", placeholder="e.g. 540, Dag No. 0125, KH-1025")
    if not q:
        return
    with closing(connect()) as con:
        hits = vdb.find_by_reference(con, q, limit=60)
    if not hits:
        st.info("No synthetic parcel has that dag or khatian number. Real land records are not searched by this prototype.")
        return
    by_parcel = {}
    for h in hits:
        by_parcel.setdefault(h["parcel_id"], []).append(h)
    st.caption(f"{len(by_parcel)} parcel(s) match. Dag numbers repeat across mouzas and survey generations, so check the location and the khatian too.")
    for pid, rows in list(by_parcel.items())[:12]:
        where = "; ".join(sorted({f"{r['field']} {r['value']} in {r['survey_gen'] + ' survey' if r['survey_gen'] else r['record_type']}" for r in rows}))
        c1, c2, c3 = st.columns([5, 1.4, 1.4])
        c1.markdown(f"**{pid}** · {rows[0]['title']}  \n<span style='font-size:.85rem;opacity:.75'>{rows[0]['area']} · matched {where}</span>", unsafe_allow_html=True)
        if c2.button(i18n.t("open_profile"), key=f"{prefix}_open_{pid}"):
            vstate.select_parcel(st.session_state, pid)
            st.switch_page(PAGES["v_profile"])
        if on_show and c3.button("🗺️ Map", key=f"{prefix}_map_{pid}"):
            on_show(next(p for p in demo_parcels() if p["parcel_id"] == pid))
    if len(by_parcel) > 12:
        st.caption(f"... and {len(by_parcel) - 12} more. Add the khatian number to narrow the search.")


NEAR_M = 25.0


def parcel_at(lon: float, lat: float, near_m: float = NEAR_M):
    """(parcel, distance_m) for the synthetic parcel containing the point; otherwise the nearest one within near_m metres
    (geodesic distance to its boundary); else (None, None). Containment always wins; if several parcels contain the point
    (an overlap), the smallest is returned."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import nearest_points
    from src.geo_tools import GEOD
    pt = Point(lon, lat)
    inside, near = [], []
    for p in demo_parcels():
        poly = Polygon(p["points"])
        if poly.contains(pt):
            inside.append((poly.area, p))
            continue
        q = nearest_points(poly.exterior, pt)[0]
        d = GEOD.inv(lon, lat, q.x, q.y)[2]
        if d <= near_m:
            near.append((d, p))
    if inside:
        return min(inside, key=lambda x: x[0])[1], 0.0
    if near:
        d, p = min(near, key=lambda x: x[0])
        return p, d
    return None, None


def parcels_containing(lon: float, lat: float) -> list:
    """Every synthetic parcel whose boundary contains the point. More than one means the point is inside a boundary overlap."""
    from shapely.geometry import Point, Polygon
    pt = Point(lon, lat)
    return [p for p in demo_parcels() if Polygon(p["points"]).contains(pt)]
