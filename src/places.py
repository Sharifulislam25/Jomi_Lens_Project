"""Joydebpur place search (live OpenStreetMap search), the focus area and administrative lookups.
Focus area = the project-defined box around Joydebpur (about 5 km x 5.5 km) clipped to Gazipur Sadar upazila (BBS/OCHA, generalised).
It is the same area as the MERN version of the project. It is not an administrative boundary."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st
from pyproj import Geod
from shapely.geometry import MultiPolygon, Point, Polygon, shape

ADMIN = Path(__file__).resolve().parent.parent / "data" / "admin"
GEOD = Geod(ellps="WGS84")
UA = "JomiLensPrototype/0.1 (student prototype)"
SIMPLIFY_DEG = 0.00002          # about 2 m
MAX_OUTLINE_KM = 2.5            # larger outlines are too big for one imagery window


@st.cache_resource
def _layer(level: int) -> gpd.GeoDataFrame:
    g = gpd.read_file(ADMIN / f"bd_adm{level}.geojson")[["shapeName", "geometry"]]
    g.sindex  # build the spatial index once
    return g


FOCUS_FILE = ADMIN / "joydebpur_focus.geojson"
FOCUS_NAME = "Joydebpur, Gazipur Sadar, Gazipur"
FOCUS_NAME_BN = "জয়দেবপুর, গাজীপুর সদর, গাজীপুর"
FOCUS_CENTER = (23.99804, 90.42031)          # lat, lon: Joydebpur Junction railway station (OpenStreetMap)


@st.cache_resource
def _focus_layer() -> gpd.GeoDataFrame:
    """Two polygons: the Gazipur Sadar upazila (kind=upazila) and the Joydebpur focus area (kind=focus)."""
    g = gpd.read_file(FOCUS_FILE)
    return g


@st.cache_resource
def coverage():
    """Polygon of the Joydebpur focus area."""
    g = _focus_layer()
    return g[g["kind"] == "focus"].geometry.union_all()


@st.cache_resource
def upazila_polygon():
    """Gazipur Sadar upazila (generalised): the wider area in which admins may digitise parcels."""
    g = _focus_layer()
    return g[g["kind"] == "upazila"].geometry.union_all()


@st.cache_data
def coverage_upazilas() -> gpd.GeoDataFrame:
    """The focus polygon as a one-row layer (name in column shapeName, for map tooltips)."""
    g = _focus_layer()
    f = g[g["kind"] == "focus"].copy()
    f["shapeName"] = "Joydebpur focus area"
    return f[["shapeName", "geometry"]].reset_index(drop=True)


@st.cache_data
def landmarks() -> list:
    """Named places in the focus area (OpenStreetMap extract + two Nominatim look-ups): [{name, lat, lon, kind, ...}]."""
    f = Path(__file__).resolve().parent.parent / "data" / "landmap" / "landmarks.json"
    return json.loads(f.read_text()) if f.exists() else []


def in_coverage(lon: float, lat: float) -> bool:
    return bool(coverage().contains(Point(lon, lat)))


@st.cache_data
def _hierarchy() -> pd.DataFrame:
    return pd.read_csv(ADMIN / "hierarchy.csv")


def locate(lon: float, lat: float) -> dict:
    """Division / district / upazila (BBS) of a point, plus the area group (Joydebpur inside the focus area, else the upazila)."""
    a3 = _layer(3)
    pt = Point(lon, lat)
    hit = a3[a3.geometry.contains(pt)]
    if hit.empty:                                   # simplified boundaries can leave tiny gaps: use the nearest area
        nearest = a3.sindex.nearest(pt)[1]
        hit = a3.iloc[[int(nearest[0])]] if len(nearest) else hit
    if hit.empty:
        return {"division": "", "district": "", "upazila": "", "area_group": ""}
    upz = hit.iloc[0].shapeName
    h = _hierarchy()
    cand = h[h.upazila == upz]
    if len(cand) > 1:
        cand = cand.assign(d=(cand.lat - lat) ** 2 + (cand.lon - lon) ** 2).sort_values("d")
    r = cand.iloc[0]
    group = "Joydebpur" if coverage().contains(pt) else upz
    return {"division": r.division, "district": r.district, "upazila": upz, "area_group": group}


def window_points(lon: float, lat: float, size_m: float) -> list:
    """Square analysis window (side = size_m) centred on a point: [(lon, lat), ...]."""
    h = size_m / 2
    n = GEOD.fwd(lon, lat, 0, h)[1]
    s = GEOD.fwd(lon, lat, 180, h)[1]
    e = GEOD.fwd(lon, lat, 90, h)[0]
    w = GEOD.fwd(lon, lat, 270, h)[0]
    return [(w, n), (e, n), (e, s), (w, s)]


def _outline(geojson):
    """Largest polygon outline from a Nominatim geometry, simplified, or None."""
    if not geojson or geojson.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    g = shape(geojson)
    if isinstance(g, MultiPolygon):
        g = max(g.geoms, key=lambda p: p.area)
    minx, miny, maxx, maxy = g.bounds
    g = g.simplify(min(SIMPLIFY_DEG, max(maxx - minx, maxy - miny) * 0.02), preserve_topology=True)
    if not isinstance(g, Polygon) or len(g.exterior.coords) < 4:
        return None
    minx, miny, maxx, maxy = g.bounds
    if max(maxx - minx, maxy - miny) * 111 > MAX_OUTLINE_KM:
        return {"too_big": True}
    return {"points": [tuple(p) for p in g.exterior.coords][:-1]}


@st.cache_data(ttl=3600, show_spinner=False)
def search_places(query: str, limit: int = 8) -> tuple:
    """Live search limited to the coverage area. Returns (results, error)."""
    if not query.strip():
        return [], None
    minx, miny, maxx, maxy = coverage().bounds
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": limit, "polygon_geojson": 1, "countrycodes": "bd", "accept-language": "en",
        "viewbox": f"{minx},{maxy},{maxx},{miny}", "bounded": 1})
    raw = None
    for attempt in range(2):                      # one retry (the free service limits requests per second)
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20).read()
            break
        except Exception:
            time.sleep(2)
    if raw is None:
        return _photon(query, limit)              # fallback provider
    out = []
    for r in json.loads(raw):
        lon, lat = float(r["lon"]), float(r["lat"])
        if not in_coverage(lon, lat):
            continue
        parts = [p.strip() for p in r["display_name"].split(",")]
        ol = _outline(r.get("geojson"))
        out.append({"name": ", ".join(parts[:2]), "full": r["display_name"], "lat": lat, "lon": lon,
                    "kind": f"{r.get('class', '')}/{r.get('type', '')}", "osm": f"{r.get('osm_type', '')} {r.get('osm_id', '')}",
                    "points": (ol or {}).get("points"), "outline_too_big": bool((ol or {}).get("too_big"))})
    return out, None


def _photon(query: str, limit: int) -> tuple:
    """Fallback search (Photon / OpenStreetMap data): points only."""
    minx, miny, maxx, maxy = coverage().bounds
    url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": query, "limit": limit, "lang": "en", "bbox": f"{minx},{miny},{maxx},{maxy}"})
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20).read())
    except Exception as exc:
        return [], f"Place search is unavailable right now ({exc}). Check your internet connection and try again in a minute."
    out = []
    for f in data.get("features", []):
        lon, lat = f["geometry"]["coordinates"][:2]
        pr = f["properties"]
        if not in_coverage(lon, lat):
            continue
        name = ", ".join(x for x in [pr.get("name"), pr.get("district") or pr.get("city")] if x) or query
        out.append({"name": name, "full": name, "lat": lat, "lon": lon, "kind": f"{pr.get('osm_key', '')}/{pr.get('osm_value', '')}",
                    "osm": f"{pr.get('osm_type', '')} {pr.get('osm_id', '')}", "points": None, "outline_too_big": False})
    return out, None


# ---------------------------------------------------------------- precise outlines (buildings, campuses, lakes, landuse)
MIRRORS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]


def _overpass(body: str):
    """Run an Overpass query on the first mirror that answers. Returns (elements, error)."""
    last = None
    for m in MIRRORS:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(m + "?data=" + urllib.parse.quote(body), headers={"User-Agent": UA}), timeout=18).read()
            return json.loads(raw)["elements"], None
        except Exception as exc:
            last = exc
    return None, str(last)


def _kind(tags: dict) -> str:
    if "building" in tags:
        return "building" if tags["building"] == "yes" else f"building: {tags['building']}"
    for k in ("amenity", "leisure", "landuse", "natural", "shop", "industrial"):
        if k in tags:
            return f"{k}: {tags[k]}"
    return "area"


def _outline_cache_file(lon: float, lat: float) -> Path:
    return Path(__file__).resolve().parent.parent / "cache" / "outlines" / f"{round(lon, 4)}_{round(lat, 4)}.json"


@st.cache_data(ttl=86400, show_spinner=False)
def polygons_near(lon: float, lat: float) -> tuple:
    """Real OpenStreetMap outlines at a point: every building / campus / lake / landuse polygon that CONTAINS the point, plus
    buildings within ~35 m. Returns (list, error). Smallest first (usually the building, then the compound, then the landuse)."""
    from src import landmap
    if landmap.available():                      # pre-plotted local data: instant, offline, no busy services
        return landmap.at_point(lon, lat), None
    d = 0.0012  # about 130 m
    s_, w_, n_, e_ = lat - d, lon - d, lat + d, lon + d
    body = ("[out:json][timeout:25];(" + "".join(f'way["{k}"]({s_},{w_},{n_},{e_});' for k in ("building", "landuse", "amenity", "leisure")) +
            f'way["natural"="water"]({s_},{w_},{n_},{e_});' + ");out geom tags;")
    f = _outline_cache_file(lon, lat)
    if f.exists():                                   # answered before: works even if the services are down
        els, err = json.loads(f.read_text()), None
    else:
        els, err = _overpass(body)
        if els is not None:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(els))
    if els is None:
        return [], err
    pt, out, seen = Point(lon, lat), [], set()
    for el in els:
        g = el.get("geometry")
        tags = el.get("tags", {})
        if el.get("type") != "way" or not g or len(g) < 4 or g[0] != g[-1] or el["id"] in seen:
            continue
        if tags.get("boundary") == "administrative" or "place" in tags:
            continue
        pts = [(p["lon"], p["lat"]) for p in g][:-1]
        poly = Polygon(pts)
        if not poly.is_valid or poly.area == 0:
            continue
        contains = poly.contains(pt)
        dist = 0 if contains else poly.distance(pt) * 111_000
        if not contains and not ("building" in tags and dist <= 35):
            continue
        area = abs(GEOD.polygon_area_perimeter([p[0] for p in pts], [p[1] for p in pts])[0])
        if area < 15 or area > 3e6:
            continue
        minx, miny, maxx, maxy = poly.bounds
        simp = poly.simplify(min(1e-5, max(maxx - minx, maxy - miny) * 0.02), preserve_topology=True)
        if not isinstance(simp, Polygon) or len(simp.exterior.coords) < 4:
            continue
        seen.add(el["id"])
        kind = _kind(tags)
        out.append({"label": tags.get("name:en") or tags.get("name") or kind.split(": ")[-1].capitalize(), "kind": kind,
                    "area_m2": round(area), "contains": contains, "dist_m": round(dist), "osm_id": el["id"],
                    "points": [tuple(p) for p in simp.exterior.coords][:-1]})
    out.sort(key=lambda o: (not o["contains"], o["area_m2"]))
    return out[:12], None


@st.cache_data(ttl=3600, show_spinner=False)
def reverse_outline(lon: float, lat: float):
    """Fallback: the OpenStreetMap feature at this point (building / site) from the reverse geocoder, or None."""
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "zoom": 19, "format": "jsonv2", "polygon_geojson": 1, "accept-language": "en"})
    try:
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15).read())
    except Exception:
        return None
    ol = _outline(r.get("geojson"))
    if not ol or not ol.get("points"):
        return None
    pts = ol["points"]
    area = abs(GEOD.polygon_area_perimeter([p[0] for p in pts], [p[1] for p in pts])[0])
    return {"label": (r.get("name") or r.get("display_name", "").split(",")[0] or "Feature"), "kind": f"{r.get('category', '')}: {r.get('type', '')}",
            "area_m2": round(area), "contains": True, "dist_m": 0, "osm_id": r.get("osm_id"), "points": pts}
