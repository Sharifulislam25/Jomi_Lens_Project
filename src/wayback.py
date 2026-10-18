"""Real historical satellite imagery for any place in Bangladesh using Esri World Imagery Wayback.
Each Wayback 'release' is a dated snapshot of the Esri basemap. IMPORTANT: the release date is NOT the date the
image was captured, and image sources/resolution differ between releases. Treat results as indicative."""
import hashlib
import io
import json
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
CFG_URL = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
UA = "JomiLensPrototype/0.1 (student prototype)"
ATTRIBUTION = "Imagery: Esri World Imagery Wayback (Esri, Maxar, Earthstar Geographics and the GIS User Community)"


class ImageryError(Exception):
    """A clear, user-readable reason why imagery could not be produced."""


def _get(url: str, timeout: int = 30, tries: int = 2) -> bytes:
    """Download with one retry for temporary network errors (a 404 is raised immediately: it means 'no tile')."""
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code == 404 or attempt == tries - 1:
                raise
        except Exception:
            if attempt == tries - 1:
                raise


_RELEASES = []   # remembered for this server session ONLY when it loaded successfully (a failure is never remembered)


def load_releases() -> list:
    """List of {date, url} sorted by date. Uses a copy on disk if the internet is unavailable; [] only if neither works."""
    global _RELEASES
    if _RELEASES:
        return _RELEASES
    CACHE.mkdir(exist_ok=True)
    f = CACHE / "waybackconfig.json"
    try:
        raw = _get(CFG_URL)
        f.write_bytes(raw)
    except Exception:
        if not f.exists():
            return []
        raw = f.read_bytes()
    cfg = json.loads(raw)
    items = [{"date": v["itemTitle"].split("Wayback ")[1].rstrip(")"), "url": v["itemURL"]} for v in cfg.values()]
    _RELEASES = sorted(items, key=lambda r: r["date"])
    return _RELEASES


def tile_xy(lon: float, lat: float, z: int) -> tuple:
    """Fractional tile coordinates (Web Mercator) of a lon/lat."""
    n = 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def fetch_tile(url_tpl: str, z: int, x: int, y: int):
    """One 256px tile (PIL) or None. Cached on disk."""
    key = hashlib.md5(f"{url_tpl}{z}{x}{y}".encode()).hexdigest()
    f = CACHE / "tiles" / f"{key}.bin"
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        if f.exists():
            raw = f.read_bytes()
            return Image.open(io.BytesIO(raw)).convert("RGB") if raw else None
        try:
            raw = _get(url_tpl.replace("{level}", str(z)).replace("{row}", str(y)).replace("{col}", str(x)))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                f.write_bytes(b"")  # remember: no imagery at this zoom/release
                return None
            raise
        f.write_bytes(raw)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None


def get_chip(url_tpl: str, bbox, z: int):
    """Stitch tiles covering bbox=(minlon,minlat,maxlon,maxlat) at zoom z and crop. Returns PIL or None."""
    minlon, minlat, maxlon, maxlat = bbox
    x0, y0 = tile_xy(minlon, maxlat, z)   # top-left
    x1, y1 = tile_xy(maxlon, minlat, z)   # bottom-right
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 25:
        return None  # area too large for one chip
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            t = fetch_tile(url_tpl, z, tx, ty)
            if t is None:
                return None
            mosaic.paste(t, ((tx - tx0) * 256, (ty - ty0) * 256))
    box = (round((x0 - tx0) * 256), round((y0 - ty0) * 256), round((x1 - tx0) * 256), round((y1 - ty0) * 256))
    return mosaic.crop(box)


def best_chip(url_tpl: str, bbox, zooms=(19, 18, 17, 16, 15, 14, 13)):
    """Highest-resolution chip available for this release. Returns (image, zoom) or (None, None)."""
    for z in zooms:
        img = get_chip(url_tpl, bbox, z)
        if img is not None and img.width >= 8 and img.height >= 8:
            return img, z
    return None, None


def metres_per_pixel(lat: float, z: int) -> float:
    return 156543.03 * math.cos(math.radians(lat)) / (2 ** z)


def _signature(rel, lon, lat):
    """Hash of the z17 tile at the place: identical hash = same imagery in different releases."""
    x, y = tile_xy(lon, lat, 17)
    t = fetch_tile(rel["url"], 17, int(x), int(y))
    return None if t is None else hashlib.md5(t.tobytes()).hexdigest()


@st.cache_data(ttl=86400, show_spinner=False)
def _distinct_versions(lon: float, lat: float) -> list:
    """Releases (earliest date of each) whose imagery at this place actually differs. Raises ImageryError instead of
    returning an empty list, so a failed lookup is never cached."""
    rels = load_releases()
    if not rels:
        raise ImageryError("The imagery catalogue could not be loaded. Check your internet connection and try again.")
    with ThreadPoolExecutor(12) as ex:
        sigs = list(ex.map(lambda r: _signature(r, lon, lat), rels))
    seen, out = set(), []
    for r, s in zip(rels, sigs):
        if s and s not in seen:
            seen.add(s)
            out.append(r)
    if not out:
        raise ImageryError("No satellite imagery came back for this location. If you are online, this spot may simply have no archived "
                           "imagery (for example open water), or the imagery server is busy: try again in a minute.")
    return out


def distinct_versions(lon: float, lat: float) -> list:
    return _distinct_versions(lon, lat)


def padded_bbox(bounds, pad_ratio: float = 0.6, min_pad_m: float = 25.0):
    """Expand the plot bounds so the chip shows some surroundings."""
    minlon, minlat, maxlon, maxlat = bounds
    lat0 = (minlat + maxlat) / 2
    max_pad_deg = 0.006   # about 650 m: big plots do not need a huge margin
    dlat = max(min((maxlat - minlat) * pad_ratio, max_pad_deg), min_pad_m / 111_320)
    dlon = max(min((maxlon - minlon) * pad_ratio, max_pad_deg), min_pad_m / (111_320 * math.cos(math.radians(lat0))))
    return (minlon - dlon, minlat - dlat, maxlon + dlon, maxlat + dlat)


def lonlat_to_pixel(points, bbox, size):
    """Map lon/lat points into pixel positions of a chip covering bbox (Web Mercator aware)."""
    minlon, minlat, maxlon, maxlat = bbox
    w, h = size
    def my(lat): return math.asinh(math.tan(math.radians(lat)))
    top, bot = my(maxlat), my(minlat)
    return [((lon - minlon) / (maxlon - minlon) * w, (top - my(lat)) / (top - bot) * h) for lon, lat in points]


def area_km(bbox, lat):
    """Width and height (km) of a lon/lat box."""
    minlon, minlat, maxlon, maxlat = bbox
    return (maxlon - minlon) * 111.32 * math.cos(math.radians(lat)), (maxlat - minlat) * 110.57


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_history(bbox: tuple, centre: tuple, max_versions: int = 10) -> list:
    """Real image chips for each distinct imagery version: [{date, image, zoom, resolution_m}].
    Raises ImageryError (never returns an empty list) so failures are not cached."""
    versions = _distinct_versions(*centre)
    if len(versions) > max_versions:  # keep first, last and evenly spaced ones
        idx = sorted({round(i * (len(versions) - 1) / (max_versions - 1)) for i in range(max_versions)})
        versions = [versions[i] for i in idx]
    def work(rel):
        img, z = best_chip(rel["url"], bbox)
        return None if img is None else {"date": rel["date"], "image": img, "zoom": z,
                                         "resolution_m": round(metres_per_pixel(centre[1], z), 2)}
    with ThreadPoolExecutor(6) as ex:
        out = [r for r in ex.map(work, versions) if r]
    if out and len(out) < max(1, len(versions) // 2):   # mostly failed: do not cache a degraded result
        raise ImageryError("Only part of the imagery could be downloaded (the imagery server may be busy). Please try again.")
    if not out:
        w, h = area_km(bbox, centre[1])
        if max(w, h) > 12:
            raise ImageryError(f"The marked area (with its margin) is about {w:.1f} x {h:.1f} km, which is too large for one image "
                               "(the limit is about 15-20 km). Mark a smaller plot.")
        raise ImageryError("Satellite tiles for this area could not be downloaded. Check your internet connection and try again; "
                           "if it keeps failing the imagery server may be busy.")
    return out


def fetch_history(bbox: tuple, centre: tuple, max_versions: int = 10) -> list:
    """Like _fetch_history but raises ImageryError with a readable reason."""
    return _fetch_history(tuple(bbox), tuple(centre), max_versions)


def try_fetch_history(bbox: tuple, centre: tuple, max_versions: int = 10) -> tuple:
    """Returns (history, message). message is '' on success, otherwise the specific reason it failed."""
    try:
        return fetch_history(bbox, centre, max_versions), ""
    except ImageryError as e:
        return [], str(e)
    except Exception as e:  # unexpected: still show something useful
        return [], f"Unexpected problem while downloading imagery ({type(e).__name__}: {e}). Please try again."


@st.cache_data(ttl=86400, show_spinner=False)
def native_zoom(lon: float, lat: float) -> int:
    """Highest zoom (17-19) at which the latest imagery really exists around this place. Beyond it the basemap would show
    'Map data not yet available', so maps must stop requesting tiles there and just enlarge the last real zoom level."""
    rels = load_releases()
    if not rels:
        return 17
    url = rels[-1]["url"]
    for z in (19, 18):
        cx, cy = tile_xy(lon, lat, z)
        cells = [(int(cx) + dx, int(cy) + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        with ThreadPoolExecutor(9) as ex:
            ok = sum(1 for t in ex.map(lambda c: fetch_tile(url, z, c[0], c[1]), cells) if t is not None)
        if ok >= 8:
            return z
    return 17
