"""🧭 Explore Joydebpur: every mapped area in the Joydebpur focus area (Gazipur Sadar, Gazipur) is pre-plotted. Pan and zoom, click any area or a synthetic demo parcel."""
import folium
import streamlit as st
from streamlit_folium import st_folium

from src import i18n, landmap, vstate
from src import vcommon
from shapely.geometry import Polygon
from src.geo_tools import GeometryError, dms, polygon_metrics
from src.map_utils import add_map_tools, add_satellite_layers
from src.nav import PAGES
from src.places import FOCUS_NAME, coverage_upazilas, in_coverage, landmarks, locate, search_places

DEFAULT_CENTER = (23.9945, 90.4231)   # near Joydebpur junction and demo parcel DV-011, so synthetic parcels are visible on first load
LABELS = {"building": "🏠 Buildings", "landuse": "🟩 Land use", "water": "💧 Water", "amenity": "🏫 Campuses & amenities",
          "leisure": "🌳 Parks & sports", "natural": "🌿 Natural"}
MAX_W_BUILDINGS = 0.012     # degrees wide (about 1.3 km): buildings appear from here
MAX_W_AREAS = 0.25          # degrees wide (about 28 km): other areas appear from here


def _size_text(m2):
    return f"{m2 / 1e4:.2f} ha" if m2 >= 1e4 else f"{m2:,.0f} m²"


def _geojson(feats):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"label": f["label"], "kind": f["kind"], "size": _size_text(f["area_m2"])},
         "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in f["points"]] + [list(f["points"][0])]]}} for f in feats]}


def _jump(lat, lon, zoom=17):
    s = st.session_state
    s["lm_center"], s["lm_zoom"] = (lat, lon), zoom
    s["lm_jump"] = s.get("lm_jump", 0) + 1
    s["lm_sel"] = None


@st.cache_data(show_spinner=False)
def _candidates(lon, lat):
    return landmap.at_point(lon, lat)


def render():
    if not landmap.available():
        st.error("The pre-plotted land data is missing. Build it with tools/build_landmap_from_extract.py (see README).")
        return
    s = st.session_state
    s.setdefault("lm_center", DEFAULT_CENTER); s.setdefault("lm_zoom", 17); s.setdefault("lm_jump", 0); s.setdefault("lm_sel", None)
    st.header("🧭 " + i18n.t("nav.explore"))
    st.caption(f"{FOCUS_NAME}. Mapped features come from OpenStreetMap (about 28,000 areas, mostly buildings). They are **approximate features, not legal parcels**: "
               "a building footprint is not a plot boundary, and open land is often unmapped. **Pink dashed outlines are SYNTHETIC demo parcels.** "
               "Official cadastral boundaries are not available in this prototype.")
    with st.expander("Coverage: what this map does and does not contain"):
        st.markdown("- **Geographic exploration:** real administrative boundaries (BBS/OCHA, generalised), place search and real satellite imagery.\n"
                    "- **Land-use features:** mapped buildings, land use, water, parks and campuses (OpenStreetMap volunteers; completeness varies).\n"
                    "- **Verification-ready demo parcels:** 25 synthetic parcels in five fictional mouzas with fictional records, surveys, cases and signed documents.\n"
                    "- **Not claimed:** cadastral completeness. No official parcel data is loaded.")
    cnt = landmap.stats()
    c = st.columns(6)
    for col, k in zip(c, landmap.KIND_NAMES):
        col.metric(LABELS[k].split(" ", 1)[1], f"{cnt[k]:,}")

    def _show_parcel(dp):
        c0 = Polygon(dp["points"]).centroid
        _jump(c0.y, c0.x, 19)
        st.rerun()

    vcommon.reference_search("lm", on_show=_show_parcel)
    with st.expander("Go to a place", expanded=False):
        a, b = st.columns(2)
        q = a.text_input("Search a place", key="lm_q", placeholder="e.g. Joydebpur, Rajbari, Shimultoli, Chandna")
        if q:
            res, err = search_places(q)
            if err: a.warning(err)
            elif not res: a.info("No match inside the Joydebpur focus area.")
            else:
                i = a.selectbox("Matches", range(len(res)), format_func=lambda k: f"{res[k]['name']} · {res[k]['kind']}", key="lm_match")
                if a.button("Go there", key="lm_go"):
                    _jump(res[i]["lat"], res[i]["lon"]); st.rerun()
        dps = vcommon.demo_parcels()
        sel_dp = a.selectbox("Or jump to a synthetic demo parcel", ["-"] + [d["parcel_id"] for d in dps], key="lm_dp",
                             format_func=lambda k: k if k == "-" else vcommon.parcel_label(next(d for d in dps if d["parcel_id"] == k)))
        if sel_dp != "-" and a.button("Go to demo parcel", key="lm_godp"):
            c0 = Polygon(next(d for d in dps if d["parcel_id"] == sel_dp)["points"]).centroid
            _jump(c0.y, c0.x, 18); st.rerun()
        lms = sorted(landmarks(), key=lambda x: x["name"])
        name = b.selectbox("Or jump to a landmark", ["-"] + [x["name"] for x in lms], key="lm_lmk")
        if name != "-" and b.button("Go to landmark", key="lm_golmk"):
            x = next(x for x in lms if x["name"] == name)
            _jump(x["lat"], x["lon"], 17); st.rerun()
        mz = b.selectbox("Or jump to a demo mouza", ["-"] + [f"Demo Mouza {i}" for i in range(1, 6)], key="lm_mz")
        if mz != "-" and b.button("Go to mouza", key="lm_gomz"):
            pts = [q for d in dps if d.get("mouza") == mz for q in d["points"]]
            if pts:
                _jump(sum(q[1] for q in pts) / len(pts), sum(q[0] for q in pts) / len(pts), 17); st.rerun()

    kinds = st.segmented_control("Show", list(LABELS), selection_mode="multi", default=list(LABELS), format_func=lambda k: LABELS[k],
                                 key="lm_kinds") or []
    mapkey = f"lm_map_{s['lm_jump']}"
    prev = s.get(mapkey) or {}
    b = prev.get("bounds")
    lat0, lon0 = s["lm_center"]
    bounds = (b["_southWest"]["lng"], b["_southWest"]["lat"], b["_northEast"]["lng"], b["_northEast"]["lat"]) if b else \
             (lon0 - 0.003, lat0 - 0.002, lon0 + 0.003, lat0 + 0.002)
    width = bounds[2] - bounds[0]

    feats, note = [], ""
    if width > MAX_W_AREAS:
        note = "Zoom in to see the pre-plotted areas (land-use zones and water appear at about 25 km wide, buildings at about 1 km)."
    else:
        want = set(kinds) if width <= MAX_W_BUILDINGS else set(kinds) - {"building"}
        r = landmap.query_view(*bounds, kinds=want)
        feats = r["features"]
        if width > MAX_W_BUILDINGS and "building" in kinds:
            note = "Buildings appear when you zoom in closer (about 1 km wide)."
        elif r["truncated"]:
            note = f"Showing the first {len(feats):,} areas in this view. Zoom in to see all of them."
    if note:
        st.info(note)

    m = folium.Map(location=[lat0, lon0], zoom_start=s["lm_zoom"], tiles=None, max_zoom=21, control_scale=True)
    add_satellite_layers(m, lon=lon0, lat=lat0, show=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False, overlay=False).add_to(m)
    add_map_tools(m)
    # The layer control is passed to st_folium (not added to the map): a control added to the map cannot see the dynamically
    # added feature group, and Leaflet then fails with "Cannot read properties of undefined (reading 'setZIndex')" and a blank map.
    fg = folium.FeatureGroup(name="Pre-plotted areas")
    folium.GeoJson(coverage_upazilas().__geo_interface__, style_function=lambda _: {"color": "#d81b60", "weight": 2, "fill": False, "dashArray": "8 6"},
                   tooltip="Joydebpur focus area").add_to(fg)
    colors = landmap.KIND_COLORS
    if feats:
        folium.GeoJson(_geojson(feats), style_function=lambda f: {"color": colors.get(f["properties"]["kind"].split(":")[0], "#e07a5f"), "weight": 1,
                                                                   "fillOpacity": 0.28},
                       tooltip=folium.GeoJsonTooltip(["label", "kind", "size"], aliases=["", "Type", "Size"])).add_to(fg)
    for dp in vcommon.demo_parcels():
        folium.Polygon([[la, lo] for lo, la in dp["points"]], color="#d81b60", weight=3, dash_array="6 4", fill=True, fill_color="#d81b60", fill_opacity=0.25,
                       tooltip=f"SYNTHETIC DEMO PARCEL {dp['parcel_id']}: {dp['scenario_title']}").add_to(fg)
        c0 = Polygon(dp["points"]).centroid
        folium.CircleMarker([c0.y, c0.x], radius=7, color="#ffffff", weight=2, fill=True, fill_color="#d81b60", fill_opacity=1,
                            tooltip=f"SYNTHETIC {dp['parcel_id']}").add_to(fg)
    sel = s.get("lm_sel")
    if sel:
        folium.Polygon([[la, lo] for lo, la in sel["points"]], color="#ffe600", weight=4, fill=True, fill_color="#f77f00", fill_opacity=0.35).add_to(fg)
    out = st_folium(m, feature_group_to_add=fg, layer_control=folium.LayerControl(collapsed=True), height=620, use_container_width=True, returned_objects=["bounds", "zoom", "last_clicked"], key=mapkey)

    st.markdown(vcommon.legend_html(), unsafe_allow_html=True)
    click = (out or {}).get("last_clicked")
    st.caption(f"{len(feats):,} areas drawn in this view. Colours: " + " · ".join(f"{LABELS[k]}" for k in landmap.KIND_NAMES) + ". Click the map to select an area.")
    if not click:
        return
    lat, lon = click["lat"], click["lng"]
    if not in_coverage(lon, lat):
        st.warning("That point is outside the Joydebpur focus area (the pink outline). Pan back inside it.")
        return
    cands = _candidates(round(lon, 6), round(lat, 6))
    loc = locate(lon, lat)
    dp, hit_dist = vcommon.parcel_at(lon, lat)
    inside = vcommon.parcels_containing(lon, lat)
    if len(inside) > 1:
        st.error("This spot is inside **" + " and ".join(x["parcel_id"] for x in inside) + "**: their registered boundaries overlap here. "
                 "The same land appears in more than one registration.")
    if dp:
        st.success(f"**Synthetic demo parcel {dp['parcel_id']}** · {dp['scenario_title']} (fictional; not a real parcel)" +
                   ("" if hit_dist == 0 else f" · your click was {hit_dist:.0f} m outside its boundary"))
        if st.button("📍 Open this parcel's profile", type="primary", key=f"lm_click_open_{dp['parcel_id']}"):
            vstate.select_parcel(st.session_state, dp["parcel_id"])
            st.switch_page(PAGES["v_profile"])
        if "inbox" in PAGES and st.button("🚩 Report a problem with this land", key=f"lm_click_rep_{dp['parcel_id']}"):
            vstate.select_parcel(st.session_state, dp["parcel_id"])
            st.switch_page(PAGES["inbox"])
    st.markdown(f"**Clicked:** {lat:.6f}, {lon:.6f} · {dms(lat, 'N', 'S')}, {dms(lon, 'E', 'W')} · {loc['upazila']}, {loc['district']}")
    if not cands:
        st.info("No pre-plotted area at this exact spot (nothing mapped here in OpenStreetMap). Click closer to a building or zone, or draw your own plot.")
        if st.button("✏️ Draw a plot here in My Plot", key="lm_draw0"):
            s["mp_center"] = (lat, lon); st.switch_page(PAGES["myplot"])
        return
    i = st.selectbox("Areas at this spot", range(len(cands)), key=f"lm_cand_{round(lon, 5)}_{round(lat, 5)}",
                     format_func=lambda k: f"{cands[k]['label']} · {cands[k]['kind']} · {_size_text(cands[k]['area_m2'])}" +
                                           ("" if cands[k]["contains"] else f" · {cands[k]['dist_m']} m away"))
    o = cands[i]
    try:
        met = polygon_metrics(o["points"])
    except GeometryError as exc:
        st.warning(f"This mapped outline is not a valid polygon ({exc}), so it cannot be measured or analysed.")
        return
    s["lm_sel"] = {"points": o["points"]}
    d = st.columns(5)
    d[0].metric("Area (m²)", f"{met['area_sqm']:,.0f}"); d[1].metric("Decimal", f"{met['area_decimal']:,.1f}")
    d[2].metric("Katha", f"{met['area_katha']:,.1f}"); d[3].metric("Perimeter (m)", f"{met['perimeter_m']:,.0f}")
    d[4].metric("Corners", len(met["points"]))
    st.markdown(f"Centre: {met['centroid'][0]:.6f}, {met['centroid'][1]:.6f} · [OpenStreetMap feature](https://www.openstreetmap.org/way/{o['osm_id']})")
    a, b2, c2, d2 = st.columns(4)
    if d2.button("📍 Profile as approximate feature", key="lm_prof", help="Opens a profile that is clearly labelled as an approximate mapped feature."):
        vcommon.set_custom_parcel(f"OSM-{o['osm_id']}", o["points"], "approximate_feature", f"OpenStreetMap contributors (way {o['osm_id']}); not a cadastral boundary",
                                  f"{o['label']} ({o['kind']})", f"{loc['upazila']}, {loc['district']}, {loc['division']} (BBS/OCHA, generalised)")
        st.switch_page(PAGES["v_profile"])
    if a.button("🛰️ Satellite history (open imagery)", type="primary", key="lm_an"):
        kind_txt = o["kind"].split(": ")[-1]
        nice = o["label"] if o["label"].lower() == kind_txt.lower() else f"{o['label']} ({kind_txt})"
        vcommon.set_custom_parcel(f"OSM-{o['osm_id']}", o["points"], "approximate_feature", f"OpenStreetMap contributors (way {o['osm_id']}); not a cadastral boundary",
                                  nice, f"{loc['upazila']}, {loc['district']} (BBS/OCHA, generalised)")
        st.switch_page(PAGES["v_satellite"])
    if b2.button("📐 Edit / extend outline", key="lm_edit", help="Opens this outline in Draw a plot as an editable layer: drag its corners or draw more land next to it."):
        s["mp_points"] = [tuple(p) for p in o["points"]]; s.pop("mp_hist", None); st.switch_page(PAGES["myplot"])
    if c2.button("🔄 Show on map", key="lm_show"):
        st.rerun()
