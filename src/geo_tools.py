"""Geometry validation and measurement.

Area method: each polygon is projected to a Lambert Azimuthal Equal-Area (LAEA) CRS centred on its own centroid
(WGS84 datum, metres) and measured there, so the result is an equal-area measurement with negligible distortion for plots.
A geodesic (ellipsoidal) area is computed as an independent cross-check. Perimeter and side lengths are geodesic.
Coordinates are (lon, lat) in EPSG:4326 everywhere in this project.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

from pyproj import CRS, Geod, Transformer
from shapely.geometry import MultiPolygon, Point, Polygon, shape
import numpy as np
import shapely
from shapely import union_all as unary_union
from shapely.validation import explain_validity

GEOD = Geod(ellps="WGS84")
SQM_PER_DECIMAL = 40.4686
SQFT_PER_SQM = 10.7639
# Conversion factors to square metres (katha and bigha vary by region: these are the common Dhaka-region values).
AREA_UNITS = {"sqm": 1.0, "sqft": 1 / SQFT_PER_SQM, "decimal": SQM_PER_DECIMAL, "katha": 720 / SQFT_PER_SQM,
              "bigha": 33 * SQM_PER_DECIMAL, "acre": 100 * SQM_PER_DECIMAL, "hectare": 10_000.0}
MAX_VERTICES = 5000
MAX_PARTS = 20
MAX_GEOJSON_BYTES = 2_000_000
MIN_AREA_SQM = 1.0
BORDER_TOLERANCE_DEG = 0.005   # the bundled national outline is generalised (about 0.4 km), so allow a small margin
ADMIN = Path(__file__).resolve().parent.parent / "data" / "admin"


class GeometryError(ValueError):
    """A geometry problem described in plain language (safe to show to users)."""


def to_sqm(value: float, unit: str) -> float:
    if unit not in AREA_UNITS:
        raise ValueError(f"Unknown area unit: {unit!r}")
    return float(value) * AREA_UNITS[unit]


def from_sqm(value_sqm: float, unit: str) -> float:
    if unit not in AREA_UNITS:
        raise ValueError(f"Unknown area unit: {unit!r}")
    return float(value_sqm) / AREA_UNITS[unit]


def dms(value: float, pos: str, neg: str) -> str:
    """Decimal degrees -> degrees, minutes, seconds text (e.g. 24° 11' 24.00'' N)."""
    hemi = pos if value >= 0 else neg
    v = abs(value)
    d = int(v)
    m = int((v - d) * 60)
    s = round((v - d - m / 60) * 3600, 2)
    if s >= 60:
        s, m = 0.0, m + 1
    if m >= 60:
        m, d = 0, d + 1
    return f"{d}° {m}' {s:.2f}\" {hemi}"


@lru_cache(maxsize=1)
def bangladesh_outline():
    """Union of the 8 BBS/OCHA division polygons (generalised). Used for real point-in-country tests (not a rectangle)."""
    gj = json.loads((ADMIN / "bd_adm1.geojson").read_text())
    return unary_union([shape(f["geometry"]) for f in gj["features"]])


def in_bangladesh(lon: float, lat: float) -> bool:
    """True if the point lies inside Bangladesh (generalised national outline plus a ~0.5 km margin)."""
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lon) and math.isfinite(lat)) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return False
    pt = Point(lon, lat)
    outline = bangladesh_outline()
    return bool(outline.contains(pt) or outline.distance(pt) <= BORDER_TOLERANCE_DEG)


def validate_polygon(coords, require_in_bangladesh: bool = True) -> list:
    """Return a clean ring [(lon, lat), ...] (no closing duplicate) or raise GeometryError with a clear message."""
    if not isinstance(coords, (list, tuple)):
        raise GeometryError("The polygon must be a list of (longitude, latitude) points.")
    pts = []
    for i, p in enumerate(coords, start=1):
        try:
            lon, lat = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise GeometryError(f"Point {i} is not a pair of numbers.")
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise GeometryError(f"Point {i} is not a finite number.")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            hint = " The values look swapped (latitude and longitude in the wrong order)." if in_bangladesh(lat, lon) else ""
            raise GeometryError(f"Point {i} is out of range. Longitude must be -180..180 and latitude -90..90.{hint}")
        if not pts or (lon, lat) != pts[-1]:      # drop consecutive duplicates
            pts.append((lon, lat))
    if len(pts) > 1 and pts[0] == pts[-1]:        # drop the closing vertex
        pts.pop()
    if len(pts) > MAX_VERTICES:
        raise GeometryError(f"The polygon has {len(pts):,} points; the limit is {MAX_VERTICES:,}.")
    if len(pts) < 3:
        raise GeometryError("At least 3 distinct corner points are needed.")
    if require_in_bangladesh:
        bad = [i for i, (lon, lat) in enumerate(pts, start=1) if not in_bangladesh(lon, lat)]
        if bad:
            swapped = all(in_bangladesh(lat, lon) for lon, lat in pts)
            hint = " The points look swapped: the order must be latitude, longitude when typing, and longitude, latitude in GeoJSON." if swapped else ""
            raise GeometryError(f"Point {bad[0]} is outside Bangladesh.{hint}")
    poly = Polygon(pts)
    if not poly.is_valid:
        raise GeometryError(f"The polygon is not valid ({explain_validity(poly)}). Check that its sides do not cross.")
    if poly.area == 0:
        raise GeometryError("The polygon has zero area (the points are in a line).")
    return pts


def _laea(lon0: float, lat0: float):
    crs = CRS.from_proj4(f"+proj=laea +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs")
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform


def transform(func, geom):
    """Project a Shapely geometry with a pyproj transform function (replaces the deprecated shapely.ops.transform)."""
    return shapely.transform(geom, lambda xy: np.column_stack(func(xy[:, 0], xy[:, 1])))


def polygon_metrics(coords, katha_sqft: float = 720.0, bigha_decimal: float = 33.0, require_in_bangladesh: bool = True) -> dict:
    """Validated measurements of a polygon. Raises GeometryError for invalid input (never returns metrics for bad geometry)."""
    pts = validate_polygon(coords, require_in_bangladesh)
    poly = Polygon(pts)
    c = poly.centroid
    area_sqm = transform(_laea(c.x, c.y), poly).area                      # equal-area projection (primary)
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    geo_area, perim = GEOD.polygon_area_perimeter(lons, lats)            # geodesic cross-check
    if area_sqm < MIN_AREA_SQM:
        raise GeometryError(f"The area is only {area_sqm:.2f} m², which is too small to be a plot.")
    sides = []
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        az, _, dist = GEOD.inv(lons[i], lats[i], lons[j], lats[j])
        sides.append({"from": i + 1, "to": j + 1, "length_m": round(dist, 2), "bearing_deg": round(az % 360, 1)})
    sqft = area_sqm * SQFT_PER_SQM
    decimal = area_sqm / SQM_PER_DECIMAL
    return {
        "area_sqm": round(area_sqm, 2), "area_sqft": round(sqft, 1), "area_decimal": round(decimal, 2),
        "area_katha": round(sqft / katha_sqft, 2), "area_bigha": round(decimal / bigha_decimal, 3),
        "area_geodesic_sqm": round(abs(geo_area), 2),
        "crs": "EPSG:4326 input; area measured in a Lambert Azimuthal Equal-Area projection centred on the polygon (metres)",
        "perimeter_m": round(abs(perim), 2),
        "centroid": (c.y, c.x),
        "valid": True,
        "corners": [{"n": i + 1, "lat": round(p[1], 7), "lon": round(p[0], 7),
                     "lat_dms": dms(p[1], "N", "S"), "lon_dms": dms(p[0], "E", "W")} for i, p in enumerate(pts)],
        "sides": sides, "bounds": poly.bounds, "points": pts,
    }


def overlap_sqm(a_points, b_points) -> float:
    """Area (m²) shared by two polygons, measured in the same equal-area projection used for parcel areas (centred on polygon A).
    Invalid input raises GeometryError; disjoint or merely touching polygons give 0."""
    a, b = Polygon(validate_polygon(a_points)), Polygon(validate_polygon(b_points))
    if not a.intersects(b):
        return 0.0
    inter = a.intersection(b)
    if inter.is_empty or inter.area == 0:
        return 0.0
    c = a.centroid
    return float(transform(_laea(c.x, c.y), inter).area)


def merge_polygons(rings, gap_m: float = 1.0) -> list:
    """Merge several polygons (each [(lon, lat), ...]) into ONE validated outline, e.g. a mapped outline plus extra land the user drew next to it.
    Parts that touch, overlap or are less than `gap_m` apart are joined. Separate parts cannot become one polygon: GeometryError says so."""
    if not rings:
        raise GeometryError("Nothing to merge.")
    polys = [Polygon(validate_polygon(r)) for r in rings]
    if len(polys) == 1:
        return validate_polygon(list(polys[0].exterior.coords))
    tol = gap_m / 111_320
    merged = unary_union([p.buffer(tol, join_style=2) for p in polys]).buffer(-tol, join_style=2)     # closes tiny gaps, keeps corners square
    if merged.geom_type != "Polygon":
        raise GeometryError("The parts are separate: they do not touch or overlap. Draw one connected outline, or analyse each part as its own parcel.")
    if list(merged.interiors):
        raise GeometryError("The merged outline encloses a hole, which is not supported in this prototype.")
    return validate_polygon(list(merged.exterior.coords))


def parse_corner_text(text: str) -> list:
    """Lines like '24.1900, 90.4780' (lat, lon). Returns validated [(lon, lat), ...]. Raises GeometryError."""
    if len(text) > 200_000:
        raise GeometryError("The text is too long.")
    pts = []
    for n, line in enumerate(text.strip().splitlines(), start=1):
        line = line.strip().replace(";", ",")
        if not line:
            continue
        parts = [p for p in line.replace("\t", " ").replace(",", " ").split() if p]
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            raise GeometryError(f"Line {n} is not 'latitude, longitude': {line[:60]!r}")
        pts.append((lon, lat))
    return validate_polygon(pts)


def parse_geojson(raw, max_bytes: int = MAX_GEOJSON_BYTES) -> list:
    """Validate a GeoJSON upload and return its single Polygon exterior ring as [(lon, lat), ...]."""
    if isinstance(raw, str):
        raw = raw.encode()
    if not isinstance(raw, (bytes, bytearray)):
        raise GeometryError("The upload is not a readable file.")
    if len(raw) > max_bytes:
        raise GeometryError(f"The file is {len(raw) / 1e6:.1f} MB; the limit is {max_bytes / 1e6:.0f} MB.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise GeometryError("The file is not valid GeoJSON (it could not be read as JSON).")
    if not isinstance(data, dict):
        raise GeometryError("The GeoJSON must be an object.")
    feats = data.get("features") if data.get("type") == "FeatureCollection" else [data]
    if not isinstance(feats, list) or not feats:
        raise GeometryError("The GeoJSON contains no features.")
    polys = []
    for f in feats:
        g = f.get("geometry", f) if isinstance(f, dict) else None
        if isinstance(g, dict) and g.get("type") in ("Polygon", "MultiPolygon"):
            polys.append(g)
    if len(polys) != 1:
        raise GeometryError("Upload a GeoJSON with exactly one Polygon." if not polys else "The file contains several polygons; upload one at a time.")
    g = polys[0]
    parts = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    if len(parts) != 1:
        raise GeometryError("MultiPolygons with several parts are not supported; upload a single Polygon.")
    rings = parts[0]
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise GeometryError("The Polygon coordinates are malformed.")
    if len(rings) > 1:
        raise GeometryError("Polygons with holes are not supported in this prototype.")
    return validate_polygon([tuple(p[:2]) if isinstance(p, (list, tuple)) else p for p in rings[0]])


# ----------------------------------------------------------------------------------------------- holdings (several parts)
def validate_holding(parts, require_in_bangladesh: bool = True) -> list:
    """A holding is one or more separate polygons (parts), for example the several dags of one khatian. Each part must be a valid polygon and
    parts must not overlap (so area is never counted twice). Returns the cleaned rings; raises GeometryError naming the part at fault."""
    if not isinstance(parts, (list, tuple)) or not parts:
        raise GeometryError("A holding needs at least one part.")
    if len(parts) > MAX_PARTS:
        raise GeometryError(f"A holding can have at most {MAX_PARTS} parts.")
    rings = []
    for i, part in enumerate(parts, start=1):
        try:
            rings.append(validate_polygon(part, require_in_bangladesh))
        except GeometryError as exc:
            raise GeometryError(f"Part {i}: {exc}")
    polys = [Polygon(r) for r in rings]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            inter = polys[i].intersection(polys[j])
            if not inter.is_empty and inter.area > 0:
                c = inter.centroid
                a = transform(_laea(c.x, c.y), inter).area
                if a >= MIN_AREA_SQM:
                    raise GeometryError(f"Parts {i + 1} and {j + 1} overlap by about {a:,.0f} m². Remove the overlap so the area is not counted twice.")
    return rings


def holding_metrics(parts, katha_sqft: float = 720.0, bigha_decimal: float = 33.0, require_in_bangladesh: bool = True) -> dict:
    """Measurements for a holding: every part is measured separately (equal-area projection) and the areas are added.
    Keys match polygon_metrics (so existing pages keep working) plus parts, part_metrics and parts_count."""
    rings = validate_holding(parts, require_in_bangladesh)
    pm = [polygon_metrics(r, katha_sqft, bigha_decimal, require_in_bangladesh) for r in rings]
    if len(pm) == 1:
        out = dict(pm[0])
        out.update(parts=rings, part_metrics=pm, parts_count=1)
        return out
    mp = MultiPolygon([Polygon(r) for r in rings])
    c = mp.centroid
    total = lambda k, nd: round(sum(m[k] for m in pm), nd)
    corners = [dict(c_, part=i) for i, m in enumerate(pm, start=1) for c_ in m["corners"]]
    sides = [dict(s_, part=i) for i, m in enumerate(pm, start=1) for s_ in m["sides"]]
    return {"area_sqm": total("area_sqm", 2), "area_sqft": total("area_sqft", 1), "area_decimal": total("area_decimal", 2), "area_katha": total("area_katha", 2),
            "area_bigha": total("area_bigha", 3), "area_geodesic_sqm": total("area_geodesic_sqm", 2),
            "crs": pm[0]["crs"] + "; each part is measured separately and the areas are added",
            "perimeter_m": total("perimeter_m", 2), "centroid": (c.y, c.x), "valid": True, "corners": corners, "sides": sides, "bounds": mp.bounds,
            "points": rings[0], "parts": rings, "part_metrics": pm, "parts_count": len(pm)}


def holding_geojson(parts) -> dict:
    """GeoJSON geometry for a holding: Polygon for one part, MultiPolygon for several."""
    def ring(r):
        return [list(p) for p in r] + [list(r[0])]
    if len(parts) == 1:
        return {"type": "Polygon", "coordinates": [ring(parts[0])]}
    return {"type": "MultiPolygon", "coordinates": [[ring(r)] for r in parts]}


def parts_from_geojson(geom: dict) -> list:
    """Rings (without the closing vertex) from a stored Polygon or MultiPolygon geometry."""
    if geom["type"] == "Polygon":
        return [[tuple(p) for p in geom["coordinates"][0]][:-1]]
    return [[tuple(p) for p in poly[0]][:-1] for poly in geom["coordinates"]]
