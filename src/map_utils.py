"""Folium (Leaflet) map helpers."""
import folium
from folium.plugins import Fullscreen, MousePosition

from src.wayback import ATTRIBUTION, load_releases, native_zoom

ESRI_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def _wb(url: str) -> str:
    return url.replace("{level}", "{z}").replace("{row}", "{y}").replace("{col}", "{x}")


def add_satellite_layers(fmap, lon=None, lat=None, dates=None, show=True):
    """Satellite base layers from the SAME Esri Wayback imagery used for the analysis.
    - 'latest' layer stops requesting tiles at the zoom where imagery really exists (no 'Map data not yet available').
    - optional older versions (dates) can be switched on in the layer control to travel back in time."""
    rels = load_releases()
    if not rels:   # offline fallback: live Esri layer, capped at the safe zoom
        folium.TileLayer(ESRI_TILES, attr="Esri World Imagery", name="Satellite (Esri)", max_zoom=21, max_native_zoom=17,
                         overlay=False, show=show).add_to(fmap)
        return
    nz = native_zoom(round(lon, 4), round(lat, 4)) if lon is not None else 17
    folium.TileLayer(_wb(rels[-1]["url"]), attr=ATTRIBUTION, name=f"Satellite (latest, {rels[-1]['date']})", max_zoom=21,
                     max_native_zoom=nz, overlay=False, show=show).add_to(fmap)
    by_date = {r["date"]: r for r in rels}
    for d in list(dates or [])[:-1][::-1]:      # older versions, newest first
        if d in by_date:
            folium.TileLayer(_wb(by_date[d]["url"]), attr=ATTRIBUTION, name=f"Satellite {d}", max_zoom=21, max_native_zoom=17,
                             overlay=False, show=False).add_to(fmap)


def add_corner_markers(fmap, points):
    """Numbered red markers at each corner of a plot. points = [(lon, lat), ...]."""
    for i, (lon, lat) in enumerate(points, start=1):
        html = ("<div style='background:#d62828;color:white;border-radius:50%;width:22px;height:22px;"
                "text-align:center;line-height:20px;font-size:12px;border:2px solid white;font-weight:bold'>"
                f"{i}</div>")
        folium.Marker([lat, lon], icon=folium.DivIcon(html=html, icon_size=(22, 22), icon_anchor=(11, 11)),
                      tooltip=f"Corner {i}: {lat:.6f}, {lon:.6f}").add_to(fmap)


def add_map_tools(fmap):
    Fullscreen().add_to(fmap)
    MousePosition(position="bottomleft", num_digits=6, prefix="Lat/Lon:", lat_formatter="function(n){return n}",
                  lng_formatter="function(n){return n}").add_to(fmap)


def build_user_plot_map(points, centroid, markers=True, dates=None, parts=None):
    """Satellite map (default) with the plot outline and numbered corners. parts = several polygons (a holding) drawn together. dates = imagery layers."""
    parts = parts if parts and len(parts) > 1 else None
    fmap = folium.Map(location=list(centroid), zoom_start=18, tiles=None, max_zoom=21, control_scale=True)
    add_satellite_layers(fmap, lon=centroid[1], lat=centroid[0], dates=dates, show=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False, overlay=False).add_to(fmap)
    for k, ring in enumerate(parts or [points], start=1):
        folium.Polygon([[lat, lon] for lon, lat in ring], color="#ffe600", weight=3, fill=True, fill_color="#f77f00", fill_opacity=0.15,
                       tooltip=f"Part {k}" if parts else None).add_to(fmap)
        if parts:
            cx, cy = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
            folium.Marker([cy, cx], icon=folium.DivIcon(html=f"<div style='background:#0b3c5d;color:#fff;border-radius:6px;padding:1px 6px;font-size:12px;"
                                                            f"border:2px solid #fff;white-space:nowrap'>Part {k}</div>", icon_size=(52, 22), icon_anchor=(26, 11))).add_to(fmap)
    if markers and not parts:
        add_corner_markers(fmap, points)
    folium.Marker(list(centroid), tooltip="Centre", icon=folium.Icon(color="blue", icon="home")).add_to(fmap)
    allp = [p for ring in (parts or [points]) for p in ring]
    lons, lats = [p[0] for p in allp], [p[1] for p in allp]
    fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(40, 40), max_zoom=20)
    add_map_tools(fmap)
    folium.LayerControl().add_to(fmap)
    return fmap
