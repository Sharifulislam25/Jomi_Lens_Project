"""Pre-plotted land map: every mapped area (mostly buildings, plus some land-use zones, water, campuses and parks) in the
Joydebpur focus area of Gazipur Sadar, Gazipur. Source: OpenStreetMap (Overpass extract, closed ways only; ODbL),
compacted by tools/build_landmap_from_extract.py. These are OpenStreetMap areas, NOT official land parcels."""
import sqlite3
import struct
from pathlib import Path

import numpy as np
import streamlit as st
from shapely import wkb as shp_wkb
from shapely.geometry import Point, Polygon

DB = Path(__file__).resolve().parent.parent / "data" / "landmap" / "areas.sqlite"
KIND_NAMES = ["building", "landuse", "water", "amenity", "leisure", "natural"]
KIND_COLORS = {"building": "#e07a5f", "landuse": "#81b29a", "water": "#3d85c6", "amenity": "#f2cc8f", "leisure": "#6aa84f", "natural": "#8e7cc3"}
TILE = 0.004


def available() -> bool:
    return DB.exists()


@st.cache_resource
def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True, check_same_thread=False)


def decode(b: bytes) -> list:
    """Compact geometry blob -> [(lon, lat), ...]"""
    if b[0] == 1:
        return list(shp_wkb.loads(b[1:]).exterior.coords)[:-1]
    x0, y0, _n = struct.unpack_from("<iiH", b, 1)
    d = np.frombuffer(b, dtype="<i2", offset=11).reshape(-1, 2).astype(np.int64)
    xs = np.concatenate([[x0], x0 + np.cumsum(d[:, 0])]) / 1e6
    ys = np.concatenate([[y0], y0 + np.cumsum(d[:, 1])]) / 1e6
    return list(zip(xs.tolist(), ys.tolist()))


def _tile_rows(minx, miny, maxx, maxy):
    tx0, tx1 = int((minx - 88) / TILE) - 1, int((maxx - 88) / TILE) + 1
    ty0, ty1 = int((miny - 20) / TILE) - 1, int((maxy - 20) / TILE) + 1
    return [(ty * 100000 + tx0, ty * 100000 + tx1) for ty in range(ty0, ty1 + 1)]


def _label(kind, sub, name):
    if name:
        return name
    return (sub or "building").replace("_", " ").capitalize() if kind == 0 else (sub or KIND_NAMES[kind]).replace("_", " ").capitalize()


def query_view(minx, miny, maxx, maxy, kinds=None, max_small=3000, max_big=1500) -> dict:
    """Features in a map view. Returns {features: [...], truncated: bool}. kinds = set of kind names (None = all)."""
    kinds = set(kinds or KIND_NAMES)
    con = _con()
    feats, truncated = [], False
    if "building" in kinds:
        for lo, hi in _tile_rows(minx, miny, maxx, maxy):
            if len(feats) >= max_small:
                truncated = True
                break
            for fid, kind, sub, area, osm, g in con.execute("SELECT id,kind,sub,area,osm,g FROM small WHERE tile BETWEEN ? AND ? LIMIT ?",
                                                             (lo, hi, max_small - len(feats) + 1)):
                if len(feats) >= max_small:
                    truncated = True
                    break
                feats.append({"id": f"s{fid}", "kind": "building", "sub": sub or "yes", "name": "", "label": _label(0, sub, ""),
                              "area_m2": area, "osm": osm, "points": decode(g)})
    n_big = 0
    for fid, kind, sub, name, area, osm, g in con.execute(
            "SELECT id,kind,sub,name,area,osm,g FROM big WHERE maxx>=? AND minx<=? AND maxy>=? AND miny<=? ORDER BY area DESC LIMIT ?",
            (minx, maxx, miny, maxy, max_big + 1)):
        if KIND_NAMES[kind] not in kinds:
            continue
        n_big += 1
        if n_big > max_big:
            truncated = True
            break
        feats.append({"id": f"b{fid}", "kind": KIND_NAMES[kind], "sub": sub, "name": name or "", "label": _label(kind, sub, name),
                      "area_m2": area, "osm": osm, "points": decode(g)})
    return {"features": feats, "truncated": truncated}


def at_point(lon: float, lat: float) -> list:
    """Every pre-plotted area containing the point (plus buildings within ~35 m), smallest first."""
    con, pt, out = _con(), Point(lon, lat), []
    d = TILE * 1.1
    for lo, hi in _tile_rows(lon - d, lat - d, lon + d, lat + d):
        for fid, kind, sub, area, osm, g in con.execute("SELECT id,kind,sub,area,osm,g FROM small WHERE tile BETWEEN ? AND ?", (lo, hi)):
            pts = decode(g)
            poly = Polygon(pts)
            cx = poly.contains(pt)
            dist = 0 if cx else poly.distance(pt) * 111_000
            if cx or dist <= 35:
                out.append({"label": _label(0, sub, ""), "kind": "building" if sub in (None, "yes") else f"building: {sub}", "area_m2": area,
                            "contains": cx, "dist_m": round(dist), "osm_id": osm, "points": pts})
    for fid, kind, sub, name, area, osm, g in con.execute("SELECT id,kind,sub,name,area,osm,g FROM big WHERE minx<=? AND maxx>=? AND miny<=? AND maxy>=?",
                                                          (lon, lon, lat, lat)):
        pts = decode(g)
        if Polygon(pts).contains(pt):
            out.append({"label": _label(kind, sub, name), "kind": f"{KIND_NAMES[kind]}: {sub}" if sub else KIND_NAMES[kind], "area_m2": area,
                        "contains": True, "dist_m": 0, "osm_id": osm, "points": pts})
    out.sort(key=lambda o: (not o["contains"], o["dist_m"], o["area_m2"]))
    return out[:14]


@st.cache_data
def stats() -> dict:
    con = _con()
    counts = {n: 0 for n in KIND_NAMES}
    counts["building"] += con.execute("SELECT COUNT(*) FROM small").fetchone()[0]
    for kind, c in con.execute("SELECT kind, COUNT(*) FROM big GROUP BY kind"):
        counts[KIND_NAMES[kind]] += c
    return counts
