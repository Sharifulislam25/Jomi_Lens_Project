"""Build data/landmap/areas.sqlite (the pre-plotted map) and data/landmap/landmarks.json from the Joydebpur OpenStreetMap extract
data/landmap/joydebpur_osm.json.gz (fetched with the Overpass API; closed ways only, so multipolygon relations are missing).
Licence: ODbL 1.0, OpenStreetMap contributors. Usage:  python tools/build_landmap_from_extract.py"""
import gzip
import json
import sqlite3
import struct
from pathlib import Path

import numpy as np
from shapely import wkb as shp_wkb
from shapely.geometry import Polygon

D = Path(__file__).resolve().parent.parent / "data" / "landmap"
SRC, DB = D / "joydebpur_osm.json.gz", D / "areas.sqlite"
TILE, SMALL_EXTENT = 0.004, 0.003
KINDS = {"building": 0, "landuse": 1, "water": 2, "amenity": 3, "leisure": 4, "natural": 5}
# Extra landmarks looked up once with OpenStreetMap Nominatim on 2026-10-16 (ODbL). Kept short on purpose: the service is rate-limited.
EXTRA = [{"name": "Joydebpur Junction (railway station)", "name_bn": "জয়দেবপুর জংশন", "lat": 23.998039, "lon": 90.420312, "kind": "railway station"},
         {"name": "Sadar Hospital Road, Rathkhola", "lat": 23.993742, "lon": 90.42485, "kind": "road"}]


def encode(coords) -> bytes:
    pts = [(round(x * 1e6), round(y * 1e6)) for x, y in coords]
    d = [(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts))]
    if any(abs(a) > 32767 or abs(b) > 32767 for a, b in d):
        return b"\x01" + shp_wkb.dumps(Polygon(coords))
    return b"\x00" + struct.pack("<iiH", pts[0][0], pts[0][1], len(pts)) + np.array(d, dtype="<i2").tobytes()


def main():
    data = json.load(gzip.open(SRC))
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE small(id INTEGER PRIMARY KEY, tile INTEGER, kind INTEGER, sub TEXT, area INTEGER, osm INTEGER, g BLOB);
    CREATE TABLE big(id INTEGER PRIMARY KEY, minx REAL, miny REAL, maxx REAL, maxy REAL, kind INTEGER, sub TEXT, name TEXT, area INTEGER, osm INTEGER, g BLOB);
    CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);""")
    small, big, marks = [], [], []
    for f in data["features"]:
        ring = [tuple(p) for p in f["ring"]]
        if ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) < 3 or f["kind"] not in KINDS:
            continue
        poly = Polygon(ring)
        minx, miny, maxx, maxy = poly.bounds
        k, name, enc = KINDS[f["kind"]], (f.get("name") or "").strip(), encode(ring)
        if f["kind"] == "building" and not name and max(maxx - minx, maxy - miny) <= SMALL_EXTENT:
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            tile = int((cy - 20) / TILE) * 100000 + int((cx - 88) / TILE)
            small.append((tile, k, None if f.get("sub") == "yes" else f.get("sub"), int(f["area_m2"]), int(f["osm_id"]), enc))
        else:
            big.append((minx, miny, maxx, maxy, k, f.get("sub"), name, int(f["area_m2"]), int(f["osm_id"]), enc))
        if name and name.lower() not in ("quarter",):
            c = poly.representative_point()
            marks.append({"name": name, "lat": round(c.y, 6), "lon": round(c.x, 6), "kind": f"{f['kind']}: {f.get('sub')}", "osm_id": f["osm_id"], "area_m2": f["area_m2"]})
    con.executemany("INSERT INTO small(tile,kind,sub,area,osm,g) VALUES (?,?,?,?,?,?)", small)
    con.executemany("INSERT INTO big(minx,miny,maxx,maxy,kind,sub,name,area,osm,g) VALUES (?,?,?,?,?,?,?,?,?,?)", big)
    con.executescript("CREATE INDEX small_tile ON small(tile); CREATE INDEX big_bbox ON big(minx,maxx);")
    con.executemany("INSERT INTO meta VALUES (?,?)", [("source", data["source"]), ("fetched_at", data["fetched_at"]), ("done", "1")])
    con.commit(); con.execute("VACUUM"); con.close()
    seen, out = set(), []
    for m in sorted(marks, key=lambda m: -m["area_m2"]) + [dict(e, source="OpenStreetMap Nominatim") for e in EXTRA]:
        if m["name"] not in seen:
            seen.add(m["name"]); out.append({k: v for k, v in m.items() if k != "area_m2"})
    (D / "landmarks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(small):,} small + {len(big):,} other areas; {len(out)} landmarks; {DB.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
