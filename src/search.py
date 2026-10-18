"""Smart search: find a land by part of its id, title, mouza, dag or khatian number, or a nearby landmark name.

Each searchable text is broken into words; the query matches a word if
- the word contains the query (substring: "dv-01" finds DV-010...DV-019, "hosp" finds "Sadar Hospital Road"),
- or, for dag/khatian numbers, the numbers are equal after removing leading zeros and labels ("Dag 0125" == "125"),
- or the spelling is close (difflib ratio >= 0.75, so "joydebpr" still finds "Joydebpur").
Results are ranked: exact > number match > starts-with > contains > close spelling. Landmarks also list demo parcels within 1.2 km."""
import difflib
import math
import re

from src import vdb
from src.verification_engine import normalize_ref

WEIGHTS = {"exact": 100, "number": 90, "prefix": 70, "contains": 50, "fuzzy": 30}
FIELD_BONUS = {"parcel_id": 8, "dag": 6, "khatian": 6, "mouza": 4, "title": 2, "landmark": 0, "area": 0}
NEAR_KM = 1.2


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()


def _words(s) -> list:
    return [w for w in re.split(r"[\s,;:/()·]+", _norm(s)) if w]


def match_score(query: str, text: str, numeric=False):
    """(score, kind) for how well `query` matches `text`, or (0, None)."""
    q, t = _norm(query), _norm(text)
    if not q or not t:
        return 0, None
    if q == t:
        return WEIGHTS["exact"], "exact"
    if numeric:
        nq, nt = normalize_ref(q), normalize_ref(t)
        if nq and nq == nt:
            return WEIGHTS["number"], "number"
    if t.startswith(q):
        return WEIGHTS["prefix"], "prefix"
    if q in t:
        return WEIGHTS["contains"], "contains"
    if numeric and any(ch.isdigit() for ch in q):
        return 0, None                                   # never "close spelling" for numbers: 125 must not find 126
    if not set(re.findall(r"\d+", q)) <= set(re.findall(r"\d+", t)):
        return 0, None                                   # "mouza 3" must not find "mouza 1" by close spelling
    best = max([difflib.SequenceMatcher(None, q, w).ratio() for w in _words(t)] + [difflib.SequenceMatcher(None, q, t).ratio()])
    if len(q) >= 4 and best >= 0.75:
        return int(WEIGHTS["fuzzy"] * best), "fuzzy"
    return 0, None


def _km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _centroid(row):
    pts = vdb.parcel_points(row)
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def search(con, query: str, landmarks=None, limit: int = 30) -> list:
    """[{type: parcel|landmark, parcel_id?, name, field, value, kind, score, lat, lon, near?}] best first."""
    q = _norm(query)[:80]
    if len(q) < 2:
        return []
    parcels = vdb.list_parcels(con)
    recs = {}
    for r in con.execute("SELECT parcel_id, dag_ref, khatian_ref FROM land_records"):
        recs.setdefault(r["parcel_id"], []).append(r)
    hits = {}

    def add(pid, field, value, score, kind, row):
        s = score + FIELD_BONUS.get(field, 0)
        if pid not in hits or hits[pid]["score"] < s:
            lat, lon = _centroid(row)
            hits[pid] = {"type": "parcel", "parcel_id": pid, "name": row["scenario_title"] or pid, "field": field, "value": value,
                         "kind": kind, "score": s, "lat": lat, "lon": lon, "mouza": row.get("mouza")}

    for p in parcels:
        for field, value, numeric in (("parcel_id", p["parcel_id"], False), ("title", p["scenario_title"], False),
                                      ("mouza", p.get("mouza"), False), ("area", p.get("administrative_area"), False)):
            sc, kind = match_score(q, value, numeric)
            if sc:
                add(p["parcel_id"], field, value, sc, kind, p)
        for r in recs.get(p["parcel_id"], []):
            for field, value in (("dag", r["dag_ref"]), ("khatian", r["khatian_ref"])):
                sc, kind = match_score(q, value, numeric=True)
                if sc:
                    add(p["parcel_id"], field, value, sc, kind, p)
    out = list(hits.values())
    by_id = {p["parcel_id"]: p for p in parcels}
    for lm in landmarks or []:
        sc, kind = match_score(q, lm["name"])
        if not sc:
            continue
        near = sorted(((round(_km(lm["lat"], lm["lon"], *_centroid(p)), 2), pid) for pid, p in by_id.items()))
        near = [{"parcel_id": pid, "km": d} for d, pid in near if d <= NEAR_KM][:5]
        out.append({"type": "landmark", "name": lm["name"], "field": "landmark", "value": lm.get("kind", ""), "kind": kind,
                    "score": sc - 5, "lat": lm["lat"], "lon": lm["lon"], "near": near})
    out.sort(key=lambda h: (-h["score"], h["type"] != "parcel", h["name"]))
    return out[:limit]
