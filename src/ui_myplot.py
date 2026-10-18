"""📐 My Plot: mark any plot in Bangladesh, measure it precisely, see REAL satellite history, enter holder details."""
import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from src.geo_tools import GeometryError, merge_polygons, parse_corner_text, parse_geojson, polygon_metrics, validate_polygon
from src.privacy import personal_data_reason
from src.places import search_places as search_place
from src.map_utils import add_map_tools, add_satellite_layers
from src.nav import PAGES
from src.ui_analysis import analysis_view

SAMPLE = "24.19000, 90.47800\n24.19000, 90.47860\n24.19045, 90.47860\n24.19045, 90.47800"


def _commit(points):
    """Validate and store the plot corners (list of (lon, lat)). Raises GeometryError with a plain message."""
    pts = validate_polygon([tuple(p[:2]) for p in points])
    polygon_metrics(pts)
    st.session_state["mp_points"] = pts
    st.session_state.pop("mp_hist", None)


def _draw_tab():
    q = st.text_input("Find the area first (optional)", placeholder="e.g. Kazipur Sirajganj, a village or union name", key="mp_q")
    if q:
        results, err = search_place(q)
        if err:
            st.warning(err)
        elif results:
            i = st.selectbox("Matches", range(len(results)), format_func=lambda k: results[k]["name"][:110], key="mp_match")
            if st.button("Go to this place"):
                st.session_state["mp_center"] = (results[i]["lat"], results[i]["lon"])
        else:
            st.info("No match found. Try adding the district name.")
    centre = st.session_state.get("mp_center")
    existing = st.session_state.get("mp_points")
    fmap = folium.Map(location=list(centre) if centre else [23.78, 90.40], zoom_start=18 if centre else 12, tiles=None, max_zoom=21, control_scale=True)
    add_satellite_layers(fmap, lon=centre[1] if centre else None, lat=centre[0] if centre else None, show=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False, overlay=False).add_to(fmap)
    fg = folium.FeatureGroup(name="Outline (editable)")
    if existing:                                    # the current outline becomes an editable layer: drag its corners, or draw more land next to it
        folium.Polygon([[la, lo] for lo, la in existing], color="#ffe600", weight=3, fill=True, fill_color="#f77f00", fill_opacity=0.15).add_to(fg)
        lons, lats = [p_[0] for p_ in existing], [p_[1] for p_ in existing]
        fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(30, 30), max_zoom=19)
    fg.add_to(fmap)
    Draw(feature_group=fg, export=False, draw_options={"polygon": {"allowIntersection": False}, "rectangle": True, "polyline": False,
                                                       "circle": False, "marker": False, "circlemarker": False}, edit_options={"edit": True, "remove": True}).add_to(fmap)
    add_map_tools(fmap)
    folium.LayerControl().add_to(fmap)
    if existing:
        st.info("**Editing the current outline.** Use the edit tool (pencil on the left of the map) to drag its corners, or the polygon / rectangle tool to draw more land "
                "next to it. Everything on the map is merged into one outline when you press the button. Land that does not touch it cannot join the same outline: "
                "analyse that land as its own parcel.")
    else:
        st.caption("Zoom in close, then use the polygon tool (left of the map) to click each corner of the plot. Drawing on a map is typically accurate to a few metres, "
                   "so check the result against your documents.")
    res = st_folium(fmap, height=520, use_container_width=True, returned_objects=["all_drawings"], key=f"mp_map_{centre}_{hash(tuple(existing)) if existing else 0}")
    polys = [d["geometry"]["coordinates"][0][:-1] for d in ((res or {}).get("all_drawings") or []) if d.get("geometry", {}).get("type") == "Polygon"]
    if polys:
        st.write(f"**{len(polys)} shape(s)** on the map.")
        if st.button("✅ Use this outline" + (" (all shapes merged)" if len(polys) > 1 else ""), type="primary"):
            try:
                _commit(merge_polygons([[tuple(c) for c in r] for r in polys]))
                st.success("Outline saved. Scroll down for the measurements.")
            except GeometryError as e:
                st.error(str(e))


def _type_tab():
    st.write("Enter one corner per line as **latitude, longitude** (decimal degrees), in order around the plot. "
             "Good sources: a GPS app on site, a survey sheet, or readings from a licensed surveyor.")
    txt = st.text_area("Corner coordinates", value="", height=150, placeholder=SAMPLE, key="mp_text")
    if st.button("Use these corners", key="mp_text_btn"):
        try:
            _commit(parse_corner_text(txt))
            st.success("Plot saved. Scroll down for the results.")
        except GeometryError as e:
            st.error(str(e))


def _upload_tab():
    f = st.file_uploader("GeoJSON file with one Polygon", type=["geojson", "json"], key="mp_file")
    if f is not None and st.button("Use this file", key="mp_file_btn"):
        try:
            _commit(parse_geojson(f.read()))
            st.success("Plot saved. Scroll down for the results.")
        except Exception as e:
            st.error(f"Could not read the file: {e}")


def _details_form():
    with st.expander("📝 Plot and holder details (optional, entered by you)"):
        st.warning("**Do not enter real names, NID numbers, phone numbers or addresses** (prototype rule). Use placeholder labels such as "
                   "'Party A'. JomiLens does not look up or verify ownership. Entries stay in this session and in reports you generate, "
                   "labelled 'user-entered, unverified'.")
        c = st.columns(4)
        c[0].text_input("Division", key="mp_div"); c[1].text_input("District", key="mp_dist")
        c[2].text_input("Upazila", key="mp_upz"); c[3].text_input("Mouza", key="mp_mouza")
        c = st.columns(5)
        c[0].text_input("Sheet", key="mp_sheet"); c[1].selectbox("Survey", ["", "CS", "SA", "RS", "BRS", "BDS", "Other"], key="mp_survey")
        c[2].text_input("Dag no.", key="mp_dag"); c[3].text_input("Khatian no.", key="mp_khatian")
        c[4].number_input("Recorded area (decimals)", min_value=0.0, step=0.5, key="mp_rec_area",
                          help="From your khatian/deed, if you have it. 0 = unknown.")
        st.markdown("**Party labels (placeholders only, e.g. Party A)**")
        base = pd.DataFrame({"Party label": [""], "Share": [""], "Basis (reference)": [""], "Note": [""]})
        st.session_state["mp_holders"] = st.data_editor(st.session_state.get("mp_holders", base), num_rows="dynamic",
                                                        key="mp_holders_editor", width="stretch")


def collect_details() -> dict:
    keys = {"division": "mp_div", "district": "mp_dist", "upazila": "mp_upz", "mouza": "mp_mouza", "sheet": "mp_sheet",
            "survey": "mp_survey", "dag_no": "mp_dag", "khatian": "mp_khatian"}
    d = {k: st.session_state.get(v, "") or "" for k, v in keys.items()}
    d["recorded_area"] = float(st.session_state.get("mp_rec_area", 0) or 0)
    h = st.session_state.get("mp_holders")
    rows = [] if h is None else [r for r in h.fillna("").to_dict("records") if str(r.get("Party label", "")).strip()]
    safe = []
    for r in rows:
        why = next((personal_data_reason(v) for v in r.values() if personal_data_reason(v)), "")
        if why:
            st.error(f"A party entry was removed because it {why}. Real personal data is not allowed in this prototype.")
        else:
            safe.append(r)
    d["holders"] = safe
    return d


def render():
    st.header("📐 Draw a plot")
    st.caption("Mark any plot in Bangladesh, get its precise area and corner coordinates, and see how the land looked in real "
               "satellite imagery over the years.")
    t1, t2, t3 = st.tabs(["✏️ Draw on map", "⌨️ Type coordinates", "📁 Upload GeoJSON"])
    with t1: _draw_tab()
    with t2: _type_tab()
    with t3: _upload_tab()
    _details_form()

    pts = st.session_state.get("mp_points")
    if not pts:
        st.info("Mark a plot above to see its measurements and satellite history.")
        return
    st.divider()
    d = collect_details()

    def holders():
        if not d["holders"]:
            st.info("No party labels entered. Add placeholder labels (never real names) in the details form above if you want them in your notes.")
        else:
            st.warning("User-entered and **unverified**. JomiLens does not confirm ownership.")
            st.dataframe(pd.DataFrame(d["holders"]), hide_index=True, width="stretch")

    analysis_view(pts, d, key="mp", hist=None, extra={"👤 Party labels": holders}, hide=("🛰️ Satellite history", "🔍 Change check", "📄 Report"))
    st.success("Your drawn polygon is selectable as **USER-DRAWN** on the Parcel profile and Satellite pages (kept only in this browser session, never saved to the database).")
    if "v_profile" in PAGES:
        a_, b_ = st.columns(2)
        a_.page_link(PAGES["v_profile"], label="Open the parcel profile", icon="📍")
        b_.page_link(PAGES["v_satellite"], label="Open satellite history (open imagery)", icon="🛰️")
