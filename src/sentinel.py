"""Open satellite imagery: Copernicus Sentinel-2 L2A (ESA; free, full and open licence), searched through the Element84 Earth Search STAC API and
read as Cloud-Optimised GeoTIFF windows from AWS Open Data. Unlike the Esri basemap, every image has a REAL CAPTURE DATE, and we compare the SAME
season (December-February, the dry season) in each year so differences are more likely to be real change than monsoon or crop effects.
Limits: 10 m per pixel, so small parcels cover only a few pixels (the app says so); clouds and haze can still affect single scenes."""
import math
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import streamlit as st
from PIL import Image
from shapely.geometry import box, shape

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
PROVIDER = "Copernicus Sentinel-2 L2A (ESA) via Element84 Earth Search / AWS Open Data"
ATTRIBUTION = "Contains modified Copernicus Sentinel data (ESA). Free, full and open licence. Access via Element84 Earth Search and AWS Open Data."
YEARS = list(range(2019, 2027))
MIN_WINDOW_M = 500       # chips are at least this wide so a parcel has visible surroundings (about 50 pixels at 10 m)


class SentinelError(Exception):
    """A readable reason why Sentinel-2 imagery could not be produced."""


def _env():
    import rasterio
    # TLS certificates are always verified. If the machine uses a custom certificate bundle (a company or campus proxy),
    # GDAL is told where it is through the standard environment variables; verification is never switched off.
    opts = {"GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_TIMEOUT": "30", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
    for var in ("CURL_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        if os.environ.get(var) and os.path.exists(os.environ[var]):
            opts["GDAL_HTTP_CAINFO"] = os.environ[var]
            break
    return rasterio.Env(**opts)


def window_bbox(bounds, min_m=MIN_WINDOW_M):
    """Expand (minlon, minlat, maxlon, maxlat) to at least min_m wide/high, centred on the parcel."""
    minlon, minlat, maxlon, maxlat = bounds
    lat0 = (minlat + maxlat) / 2
    mx = min_m / (111_320 * math.cos(math.radians(lat0)))
    my = min_m / 110_574
    cx, cy = (minlon + maxlon) / 2, lat0
    hx, hy = max((maxlon - minlon) / 2 + 0.0004, mx / 2), max((maxlat - minlat) / 2 + 0.0004, my / 2)
    return (cx - hx, cy - hy, cx + hx, cy + hy)


def _search(bbox, year, max_cloud):
    from pystac_client import Client
    cat = Client.open(STAC_URL)
    items = list(cat.search(collections=[COLLECTION], bbox=bbox, datetime=f"{year - 1}-12-01/{year}-02-28", query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=40).items())
    target = box(*bbox)
    items = [i for i in items if shape(i.geometry).contains(target)]      # the window must lie inside the scene
    return sorted(items, key=lambda i: i.properties.get("eo:cloud_cover", 100))


def _read(item, bbox):
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds
    href = item.assets["visual"].href
    with _env(), rasterio.open(href) as ds:
        b = transform_bounds("EPSG:4326", ds.crs, *bbox)
        arr = ds.read(window=from_bounds(*b, transform=ds.transform), boundless=False)
    if arr.size == 0 or arr.shape[0] < 3 or not arr.any():
        raise SentinelError("empty window")
    return np.transpose(arr[:3], (1, 2, 0)).astype(np.uint8)


def _one_year(bbox, year, max_cloud):
    try:
        for item in _search(bbox, year, max_cloud)[:3]:                       # least cloudy first; try a couple if one fails
            try:
                rgb = _read(item, bbox)
            except Exception:
                continue
            return {"date": item.datetime.date().isoformat(), "date_kind": "capture", "image": Image.fromarray(rgb), "zoom": None, "resolution_m": 10.0,
                    "provider": PROVIDER, "cloud_cover": round(float(item.properties.get("eo:cloud_cover", -1)), 1), "item_id": item.id, "season": f"Dec {year - 1} - Feb {year}"}
    except Exception:
        return None
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch(bbox: tuple, years: tuple, max_cloud: float) -> list:
    with ThreadPoolExecutor(4) as ex:
        out = [r for r in ex.map(lambda y: _one_year(bbox, y, max_cloud), years) if r]
    if not out:
        raise SentinelError("No cloud-free Sentinel-2 scene could be read for this place in the dry seasons. Check your internet connection and try again, "
                            "or switch to the Esri viewer.")
    return out


def try_fetch_history(bounds: tuple, years=None, max_cloud: float = 15.0) -> tuple:
    """Returns (history, message). history items match the Esri history format (+ date_kind='capture', cloud_cover, item_id)."""
    try:
        bbox = tuple(round(v, 6) for v in window_bbox(bounds))
        return _fetch(bbox, tuple(years or YEARS), max_cloud), "", bbox
    except SentinelError as e:
        return [], str(e), None
    except Exception as e:
        return [], f"Unexpected problem while reading Sentinel-2 ({type(e).__name__}). Please try again.", None
