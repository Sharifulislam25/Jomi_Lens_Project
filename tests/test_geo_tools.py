import json
import math

import pytest
from pyproj import Geod

from src.geo_tools import (GeometryError, from_sqm, in_bangladesh, parse_corner_text, parse_geojson, polygon_metrics, to_sqm, validate_polygon)

G = Geod(ellps="WGS84")


def square(lon=90.40, lat=23.80, side=100.0):
    n = G.fwd(lon, lat, 0, side / 2)[1]; s = G.fwd(lon, lat, 180, side / 2)[1]
    e = G.fwd(lon, lat, 90, side / 2)[0]; w = G.fwd(lon, lat, 270, side / 2)[0]
    return [(w, n), (e, n), (e, s), (w, s)]


def test_area_and_perimeter_of_a_100m_square():
    m = polygon_metrics(square())
    assert m["area_sqm"] == pytest.approx(10_000, rel=0.002)
    assert m["perimeter_m"] == pytest.approx(400, rel=0.002)
    assert m["area_decimal"] == pytest.approx(10_000 / 40.4686, rel=0.002)


def test_equal_area_projection_agrees_with_geodesic_cross_check():
    m = polygon_metrics(square(side=300))
    assert abs(m["area_sqm"] - m["area_geodesic_sqm"]) / m["area_sqm"] < 0.0005
    assert "Equal-Area" in m["crs"]


def test_unit_conversions():
    assert to_sqm(1, "decimal") == pytest.approx(40.4686)
    assert to_sqm(720, "sqft") == pytest.approx(to_sqm(1, "katha"), rel=1e-6)
    assert from_sqm(to_sqm(5, "bigha"), "bigha") == pytest.approx(5)
    assert to_sqm(1, "acre") == pytest.approx(100 * 40.4686)
    with pytest.raises(ValueError):
        to_sqm(1, "furlong")


def test_closing_vertex_and_duplicates_are_cleaned():
    sq = square()
    pts = validate_polygon(sq + [sq[0]])
    assert len(pts) == 4
    assert len(validate_polygon([sq[0], sq[0], sq[1], sq[2], sq[3]])) == 4


@pytest.mark.parametrize("bad", [
    [(90.4, 23.8), (90.41, 23.8)],                                   # too few points
    [(90.4, 23.8), (90.41, 23.8), (90.42, 23.8)],                    # zero area (a line)
    [(90.40, 23.80), (90.41, 23.81), (90.41, 23.80), (90.40, 23.81)],  # self-intersecting bow-tie
    [(float("nan"), 23.8), (90.41, 23.8), (90.41, 23.81)],
    [(float("inf"), 23.8), (90.41, 23.8), (90.41, 23.81)],
    [(90.4, 123.8), (90.41, 23.8), (90.41, 23.81)],                  # latitude out of range
    [(88.36, 22.57), (88.37, 22.57), (88.37, 22.58)],                # Kolkata: not in Bangladesh
    "not a list", [("a", "b"), (1, 2), (3, 4)],
])
def test_invalid_polygons_are_rejected(bad):
    with pytest.raises(GeometryError):
        polygon_metrics(bad)


def test_swapped_lat_lon_gets_a_helpful_message():
    swapped = [(lat, lon) for lon, lat in square()]
    with pytest.raises(GeometryError, match="swapped"):
        validate_polygon(swapped)


def test_bangladesh_test_is_a_polygon_not_a_rectangle():
    assert in_bangladesh(90.41, 23.81)                       # Dhaka
    assert not in_bangladesh(90.0, 21.5)                     # Bay of Bengal: inside the old lat/lon rectangle
    assert not in_bangladesh(91.5, 25.6)                     # Meghalaya, India: inside the old rectangle
    assert not in_bangladesh(float("nan"), 23.8) and not in_bangladesh("x", 1)


def test_too_many_vertices_rejected():
    ring = [(90.40 + 1e-6 * i, 23.80 + (1e-6 if i % 2 else 0)) for i in range(6000)]
    with pytest.raises(GeometryError, match="limit"):
        validate_polygon(ring)


def test_tiny_area_rejected():
    tiny = [(90.4, 23.8), (90.4000001, 23.8), (90.4000001, 23.8000001)]
    with pytest.raises(GeometryError):
        polygon_metrics(tiny)


GOOD = {"type": "Polygon", "coordinates": [[[90.478, 24.19], [90.4786, 24.19], [90.4786, 24.19045], [90.478, 24.19]]]}


def test_geojson_valid_feature_collection_and_bare_polygon():
    assert len(parse_geojson(json.dumps(GOOD))) == 3
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": GOOD}]}
    assert len(parse_geojson(json.dumps(fc).encode())) == 3


@pytest.mark.parametrize("raw,msg", [
    (b"not json at all", "not valid GeoJSON"),
    (b"[1,2,3]", "must be an object"),
    (b'{"type":"Point","coordinates":[90.4,23.8]}', "exactly one Polygon"),
    (b'{"type":"FeatureCollection","features":[]}', "no features"),
    (json.dumps({"type": "MultiPolygon", "coordinates": [GOOD["coordinates"], GOOD["coordinates"]]}).encode(), "several parts"),
    (json.dumps({"type": "Polygon", "coordinates": GOOD["coordinates"] * 2}).encode(), "holes"),
    (json.dumps({"type": "Polygon", "coordinates": [[["a", "b"], [1, 2], [3, 4]]]}).encode(), "number"),
    (b"x" * 3_000_000, "limit"),
    (b"\xff\xfe\x00bad", "not valid GeoJSON"),
])
def test_malformed_geojson_is_rejected_safely(raw, msg):
    with pytest.raises(GeometryError, match=msg):
        parse_geojson(raw)


def test_corner_text_parsing():
    pts = parse_corner_text("23.8000, 90.4000\n23.8000, 90.4010\n23.8010, 90.4010")
    assert pts[0] == (90.4, 23.8)
    with pytest.raises(GeometryError, match="Line 2"):
        parse_corner_text("23.8, 90.4\nhello world\n23.8, 90.5")


# ---------------------------------------------------------------- extending an outline (merge)
from src.geo_tools import merge_polygons


def rect(lon, lat, w=0.0006, h=0.0004):
    return [(lon, lat), (lon + w, lat), (lon + w, lat + h), (lon, lat + h)]


def test_merge_adjacent_parts_into_one_outline_with_the_summed_area():
    a, b = rect(90.4000, 23.8000), rect(90.4006, 23.8000)                       # share an edge
    merged = merge_polygons([a, b])
    assert polygon_metrics(merged)["area_sqm"] == pytest.approx(polygon_metrics(a)["area_sqm"] + polygon_metrics(b)["area_sqm"], rel=0.01)
    assert len(merge_polygons([rect(90.4, 23.8)])) == 4                          # a single part is returned as is


def test_merge_overlapping_parts_and_tiny_gap_but_not_separate_land():
    big = merge_polygons([rect(90.4000, 23.8000), rect(90.4003, 23.8000)])         # overlap
    assert polygon_metrics(big)["area_sqm"] < polygon_metrics(rect(90.4000, 23.8000))["area_sqm"] * 2
    assert merge_polygons([rect(90.4000, 23.8000), rect(90.40060005, 23.8000)])    # gap of well under a metre is closed
    with pytest.raises(GeometryError, match="separate"):
        merge_polygons([rect(90.4000, 23.8000), rect(90.4100, 23.8100)])           # far apart: cannot be one polygon


def test_merge_rejects_bad_input_and_holes():
    with pytest.raises(GeometryError):
        merge_polygons([])
    with pytest.raises(GeometryError):
        merge_polygons([rect(90.4, 23.8), [(88.36, 22.57), (88.37, 22.57), (88.37, 22.58)]])    # a part outside Bangladesh
    ring = [rect(90.4000, 23.8000, 0.0006, 0.0001), rect(90.4005, 23.8000, 0.0001, 0.0006), rect(90.4000, 23.8005, 0.0006, 0.0001), rect(90.4000, 23.8000, 0.0001, 0.0006)]
    with pytest.raises(GeometryError, match="hole"):
        merge_polygons(ring)
