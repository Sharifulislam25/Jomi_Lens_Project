"""Modest, honest land-use classification (rules only; NO trained model, so confidence is None = not calibrated).
Parcel-level label comes from mapped OpenStreetMap features at/around the parcel; imagery is only supporting evidence."""

LABELS = ("residential", "industrial/factory", "commercial/shop", "institutional/education", "playground/park", "agricultural/field",
          "garden/vegetation", "construction/disturbed land", "water", "road/paved area", "mixed use", "unknown")
MODEL_VERSION = "rules-v1"
LANDUSE = {"residential": "residential", "industrial": "industrial/factory", "depot": "industrial/factory", "port": "industrial/factory",
           "commercial": "commercial/shop", "retail": "commercial/shop", "education": "institutional/education", "institutional": "institutional/education",
           "farmland": "agricultural/field", "farmyard": "agricultural/field", "meadow": "agricultural/field", "greenfield": "agricultural/field",
           "orchard": "garden/vegetation", "grass": "garden/vegetation", "forest": "garden/vegetation", "recreation_ground": "playground/park",
           "construction": "construction/disturbed land", "brownfield": "construction/disturbed land", "basin": "water", "reservoir": "water"}
AMENITY = {"school": "institutional/education", "university": "institutional/education", "college": "institutional/education",
           "marketplace": "commercial/shop", "kindergarten": "institutional/education"}
BUILDING = {"residential": "residential", "house": "residential", "apartments": "residential", "commercial": "commercial/shop", "retail": "commercial/shop",
            "industrial": "industrial/factory", "warehouse": "industrial/factory", "school": "institutional/education", "university": "institutional/education"}


def _label_for(kind_text: str):
    kind, _, sub = kind_text.partition(": ")
    kind = kind.strip()
    sub = sub.strip()
    if kind == "water":
        return "water"
    if kind == "landuse":
        return LANDUSE.get(sub)
    if kind == "amenity":
        return AMENITY.get(sub)
    if kind == "leisure":
        return "playground/park"
    if kind.startswith("building"):
        return BUILDING.get(sub or kind.split(":")[-1].strip())
    if kind == "natural":
        return "garden/vegetation" if sub in ("wood", "scrub", "grassland", "heath") else ("water" if sub in ("water", "wetland") else None)
    return None


def classify_parcel(points, mapped_features=None, greenness=None) -> dict:
    """points: [(lon, lat)]. mapped_features: list of dicts with 'kind' text (e.g. 'landuse: residential') that contain the parcel centre
    (from src.landmap.at_point). greenness: optional mean excess-green index inside the parcel (preliminary evidence only)."""
    evidence, labels = [], []
    for f in mapped_features or []:
        lab = _label_for(f.get("kind", ""))
        if lab:
            labels.append(lab)
            evidence.append(f"Mapped feature '{f.get('label', '')}' ({f.get('kind')}) -> {lab}")
    distinct = sorted(set(labels))
    if len(distinct) == 1:
        label, note = distinct[0], "One mapped class found."
    elif len(distinct) > 1:
        label, note = "mixed use", "Several different mapped classes overlap the parcel: " + ", ".join(distinct) + "."
    else:
        label, note = "unknown", "No mapped land-use feature covers the parcel."
        if greenness is not None and greenness >= 0.12:
            label, note = "garden/vegetation", "No mapped feature, but imagery greenness is high (preliminary imagery rule)."
            evidence.append(f"Greenness index {greenness} >= 0.12 (preliminary, not a validated classifier)")
    return {"class_label": label, "method": "rules", "confidence": None, "model_version": MODEL_VERSION,
            "evidence_summary": note + (" " + " | ".join(evidence) if evidence else ""), "review_status": "unreviewed",
            "caveats": ["Rule-based and preliminary; confidence is not calibrated and is therefore not reported.",
                        "A mapped feature is a volunteer-drawn object, not an official land-use designation.",
                        "Parcel-level label is separate from object-level features (a campus can contain buildings, fields and paths)."]}
