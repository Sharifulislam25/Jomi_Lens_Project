"""Analysis of REAL satellite chips (Esri Wayback) inside a user-defined plot polygon.
Indicative only: imagery from different dates differs in sensor, season, sun angle and resolution, which can look
like 'change'. Results are potential observations that need verification."""
import cv2
import numpy as np
from src.geo_tools import GeometryError, polygon_metrics
from PIL import Image, ImageDraw
from src.wayback import lonlat_to_pixel

CANVAS_W = 640


def _canvas_size(img: Image.Image) -> tuple:
    return CANVAS_W, max(1, round(CANVAS_W * img.height / img.width))


def prepare_history(history: list, bbox: tuple, points: list, parts: list = None) -> list:
    """Resize every chip to a common canvas and compute plot-mask + greenness inside the plot."""
    out = []
    rings = parts if parts and len(parts) > 1 else [points]
    try:
        area_sqm = sum(polygon_metrics(r, require_in_bangladesh=False)["area_sqm"] for r in rings)
    except GeometryError:
        area_sqm = None
    for h in history:
        size = _canvas_size(history[0]["image"])
        img = h["image"].resize(size, Image.LANCZOS)
        polys = [lonlat_to_pixel(r, bbox, size) for r in rings]
        poly = polys if len(polys) > 1 else polys[0]          # one ring, or a list of rings for a holding
        mask = np.zeros((size[1], size[0]), np.uint8)
        cv2.fillPoly(mask, [np.array(pp, np.int32) for pp in polys], 1)
        rgb = np.asarray(img).astype(np.float32)
        exg = (2 * rgb[..., 1] - rgb[..., 0] - rgb[..., 2]) / (rgb.sum(axis=2) + 1e-6)  # excess-green index
        inside = mask == 1
        out.append({**{k: v for k, v in h.items() if k != "image"}, "raw": img, "poly_px": poly, "mask": mask,
                    "greenness": (round(float(exg[inside].mean()), 3) if inside.any() and np.isfinite(exg[inside].mean()) else None),
                    "brightness": round(float(rgb[inside].mean() / 255), 3) if inside.any() else None,
                    "native_pixels": round(area_sqm / h["resolution_m"] ** 2) if area_sqm and h.get("resolution_m") else None})
    return out


def _rings_px(poly_px):
    """poly_px is one ring [(x, y), ...] or a list of rings."""
    return [poly_px] if poly_px and not isinstance(poly_px[0][0], (tuple, list)) else list(poly_px)


def with_outline(img: Image.Image, poly_px: list, color=(255, 230, 0), width=3) -> Image.Image:
    """Copy of the image with the boundary (every part) and numbered corners drawn on it."""
    im = img.copy()
    d = ImageDraw.Draw(im)
    rings = _rings_px(poly_px)
    for k, ring in enumerate(rings, start=1):
        d.line(ring + [ring[0]], fill=color, width=width)
        if len(rings) > 1:
            cx, cy = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
            d.text((cx - 12, cy - 6), f"Part {k}", fill="white")
        else:
            for i, (x, y) in enumerate(ring, start=1):
                d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(214, 40, 40), outline="white")
                d.text((x + 8, y - 12), str(i), fill="white")
    return im


def _zscore(arr):
    return (arr - arr.mean(axis=(0, 1))) / (arr.std(axis=(0, 1)) + 1e-6)


def compare_real(before: dict, after: dict, threshold: float = 2.0) -> dict:
    """Difference between two prepared chips. Each image is colour-normalised (z-score per channel) first to reduce
    sensor/season differences, then blurred, differenced and thresholded."""
    a = cv2.GaussianBlur(_zscore(np.asarray(before["raw"]).astype(np.float32)), (9, 9), 0)
    b = cv2.GaussianBlur(_zscore(np.asarray(after["raw"]).astype(np.float32)), (9, 9), 0)
    diff = np.linalg.norm(a - b, axis=2)
    changed = (diff > threshold).astype(np.uint8)
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    inside = after["mask"] == 1
    pct_in = round(100 * float(changed[inside].mean()), 1) if inside.any() else None
    pct_all = round(100 * float(changed.mean()), 1)
    heat = cv2.applyColorMap(np.clip(diff / 6 * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    heat = Image.fromarray(cv2.cvtColor(heat, cv2.COLOR_BGR2RGB))
    ov = np.asarray(after["raw"]).copy()
    red = (changed == 1) & inside
    ov[red] = (0.5 * ov[red] + 0.5 * np.array([230, 40, 40])).astype(np.uint8)
    return {"changed_pct_plot": pct_in, "changed_pct_area": pct_all, "difference": with_outline(heat, after["poly_px"]),
            "overlay": with_outline(Image.fromarray(ov), after["poly_px"]),
            "greenness_change": None if (before.get("greenness") is None or after.get("greenness") is None)
                                else round(after["greenness"] - before["greenness"], 3),
            "warnings": comparison_warnings(before, after)}


def real_anomalies(cmp: dict, recorded_area_decimal=None, computed_decimal=None) -> list:
    """Cautious, rule-based 'potential' observations from real-imagery comparison."""
    found = []
    pct = cmp["changed_pct_plot"]
    if pct is not None and pct >= 15:
        found.append({"type": "POTENTIAL_SURFACE_CHANGE", "affected_pct": pct, "confidence": None,
                      "observation": f"About {pct}% of the marked plot looks different between the two images. This may be a real "
                                     "land-surface change or a difference in season, sensor or resolution.",
                      "status": "Requires verification"})
    g = cmp["greenness_change"]
    if g is not None and g <= -0.05:
        found.append({"type": "VEGETATION_DECREASE", "affected_pct": None, "confidence": None,
                      "observation": f"Greenness index inside the plot fell by {abs(g):.2f}. Possible clearing, construction or seasonal effect.",
                      "status": "Requires verification"})
    if recorded_area_decimal and computed_decimal:
        d = abs(computed_decimal - recorded_area_decimal) / recorded_area_decimal * 100
        if d >= 5:
            found.append({"type": "AREA_DISCREPANCY", "affected_pct": round(d, 1), "confidence": None,
                          "observation": f"Marked-boundary area ({computed_decimal} dec) differs from the recorded area ({recorded_area_decimal} dec). "
                                         "The marked corners may be imprecise.", "status": "Requires verification"})
    return found


GENERAL_MESSAGE = "Potential spatial anomaly detected. Further verification is recommended."


def comparison_warnings(before: dict, after: dict) -> list:
    """Plain-language reasons the comparison may be unreliable (resolution, empty mask, missing measurements)."""
    w = []
    rb, ra = before.get("resolution_m"), after.get("resolution_m")
    if rb and ra and max(rb, ra) / min(rb, ra) >= 2:
        w.append(f"The two images have very different resolutions (about {rb} m and {ra} m per pixel). Differences may come from sharpness, "
                 "not from the land.")
    px = [x for x in (before.get("native_pixels"), after.get("native_pixels")) if x is not None]
    if px and min(px) < 25:
        w.append(f"At this image resolution the parcel covers only about {min(px)} pixels, so plot-only percentages are rough. "
                 "Look at the whole view and the images themselves.")
    if before.get("mask") is None or after.get("mask") is None or not after["mask"].any():
        w.append("The plot outline does not cover any pixels of the image, so the plot-only measurement is unavailable.")
    if before.get("greenness") is None or after.get("greenness") is None:
        w.append("A vegetation measurement is missing for one of the images, so the greenness change is unavailable.")
    return w
