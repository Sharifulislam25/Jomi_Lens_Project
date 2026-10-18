"""Smart search page: type part of a parcel id, title, mouza, dag or khatian number, or a landmark name."""
from contextlib import closing

import folium
import streamlit as st
from streamlit_folium import st_folium

from src import places, search, vstate
from src.nav import PAGES
from src.vcommon import connect, demo_parcels

KIND_TEXT = {"exact": "exact", "number": "same number", "prefix": "starts with", "contains": "contains", "fuzzy": "similar spelling"}
FIELD_TEXT = {"parcel_id": "Parcel id", "title": "Title", "mouza": "Mouza", "area": "Area", "dag": "Dag", "khatian": "Khatian", "landmark": "Landmark"}


def _open(pid, page="v_profile"):
    vstate.select_parcel(st.session_state, pid)
    st.switch_page(PAGES[page])


def render():
    st.header("🔎 Find a land")
    st.caption("Type any part of: parcel id (DV-011), dag or khatian number (Dag 0125 = 125), mouza (Demo Mouza 3), a title word, or a landmark "
               "(junction, hospital, DUET). Small spelling mistakes are allowed for words, never for numbers.")
    q = st.text_input("Search", key="srch_q", placeholder="e.g. 125 · dv-01 · mouza 3 · hospitl · joydebpur junction")
    examples = st.columns(5)
    for col, ex in zip(examples, ["DV-011", "Demo Mouza 2", "hospital", "junction", "rapid"]):
        if col.button(ex, key=f"srch_ex_{ex}", use_container_width=True):
            st.session_state["srch_q"] = ex
            st.rerun()
    if not q or len(q.strip()) < 2:
        st.info("Type at least 2 characters.")
        return
    with closing(connect()) as con:
        hits = search.search(con, q, landmarks=places.landmarks())
    if not hits:
        st.warning("Nothing found. Try fewer letters (for example 'joyd' instead of 'joydebpur sadar').")
        return
    by_id = {p["parcel_id"]: p for p in demo_parcels()}
    left, right = st.columns([1.1, 1])
    with left:
        st.write(f"**{len(hits)} result(s)**")
        for i, h in enumerate(hits):
            with st.container(border=True):
                if h["type"] == "parcel":
                    p = by_id.get(h["parcel_id"], {})
                    st.markdown(f"📍 **{h['parcel_id']}** · {h['name']}  \n<small>{p.get('mouza') or ''} · matched {FIELD_TEXT[h['field']]} "
                                f"“{h['value']}” ({KIND_TEXT[h['kind']]})</small>", unsafe_allow_html=True)
                    a, b = st.columns(2)
                    if a.button("Open profile", key=f"srch_p_{i}", use_container_width=True):
                        _open(h["parcel_id"])
                    if b.button("Verify", key=f"srch_v_{i}", use_container_width=True):
                        _open(h["parcel_id"], "v_verify")
                else:
                    st.markdown(f"🏷️ **{h['name']}** (landmark, {KIND_TEXT[h['kind']]})", unsafe_allow_html=True)
                    if h["near"]:
                        st.caption("Demo parcels within 1.2 km: " + ", ".join(f"{n['parcel_id']} ({n['km']:.2f} km)" for n in h["near"]))
                        pick = st.selectbox("Open a nearby parcel", [n["parcel_id"] for n in h["near"]], key=f"srch_n_{i}")
                        if st.button("Open", key=f"srch_no_{i}"):
                            _open(pick)
                    else:
                        st.caption("No demo parcel within 1.2 km.")
    with right:
        lat0 = sum(h["lat"] for h in hits[:10]) / min(len(hits), 10)
        lon0 = sum(h["lon"] for h in hits[:10]) / min(len(hits), 10)
        m = folium.Map(location=[lat0, lon0], zoom_start=14, control_scale=True)
        folium.GeoJson(places.coverage_upazilas().__geo_interface__, style_function=lambda _: {"color": "#0e7c86", "weight": 2, "fill": False}).add_to(m)
        for h in hits[:30]:
            if h["type"] == "parcel" and h["parcel_id"] in by_id:
                pts = by_id[h["parcel_id"]]["points"]
                folium.Polygon([[la, lo] for lo, la in pts], color="#f77f00", weight=3, fill=True, fill_opacity=0.3, tooltip=f"{h['parcel_id']} · {h['name']}").add_to(m)
            else:
                folium.Marker([h["lat"], h["lon"]], tooltip=h["name"], icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)
        st_folium(m, height=520, use_container_width=True, returned_objects=[], key=f"srch_map_{q}")
        st.caption("Map data © OpenStreetMap contributors (ODbL). Orange = synthetic demo parcels.")
