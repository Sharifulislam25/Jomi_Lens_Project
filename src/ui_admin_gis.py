"""Admin GIS coordinate editor: correct a parcel outline by dragging corners, clicking the map, typing lat/lng or moving it by metres;
digitise a new parcel; retire or restore a parcel. Every save is validated (inside Gazipur Sadar, no new overlap) and audit-logged."""
import json
from contextlib import closing

import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from streamlit_folium import st_folium

from src import parcel_admin, places, vdb
from src.map_utils import add_corner_markers, add_map_tools, add_satellite_layers
from src.parcel_admin import EditError
from src.ui_admin import _admin
from src.vcommon import connect, demo_parcels


def _changed():
    demo_parcels.clear()                  # every page reads parcels through this cache


def _base_map(center, zoom=19):
    m = folium.Map(location=list(center), zoom_start=zoom, tiles=None, max_zoom=21, control_scale=True)
    add_satellite_layers(m, lon=center[1], lat=center[0], show=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False, overlay=False).add_to(m)
    return m


def _others(m, skip=None):
    for p in demo_parcels():
        if p["parcel_id"] != skip:
            folium.Polygon([[la, lo] for lo, la in p["points"]], color="#00b4d8", weight=1.5, fill=True, fill_opacity=0.08,
                           tooltip=f"{p['parcel_id']} · {p['scenario_title']}").add_to(m)


def _draft_key(pid):
    return f"gis_draft_{pid}"


def editor():
    admin = _admin()
    st.header("🗺️ GIS coordinate editor")
    st.caption("Correct where a parcel sits on the map. Changes are checked (inside Gazipur Sadar, no new overlap with other parcels), "
               "then saved with your reason to the audit log. Records and signed documents are not changed: re-run verification afterwards.")
    tabs = st.tabs(["✏️ Edit an outline", "➕ Digitise a new parcel", "🗃️ Retire / restore"])
    with tabs[0]:
        _edit_tab(admin)
    with tabs[1]:
        _new_tab(admin)
    with tabs[2]:
        _retire_tab(admin)


def _edit_tab(admin):
    parcels = demo_parcels()
    ids = [p["parcel_id"] for p in parcels]
    by_id = {p["parcel_id"]: p for p in parcels}
    pre = st.session_state.get("gis_pid")
    pid = st.selectbox("Parcel", ids, index=ids.index(pre) if pre in ids else 0,
                       format_func=lambda k: f"{k} · {by_id[k]['scenario_title']} · {by_id[k].get('mouza') or ''}", key="gis_pick")
    st.session_state["gis_pid"] = pid
    saved = [tuple(x) for x in by_id[pid]["points"]]
    dk = _draft_key(pid)
    draft = st.session_state.setdefault(dk, saved)
    dirty = [tuple(round(c, 7) for c in x) for x in draft] != [tuple(round(c, 7) for c in x) for x in saved]

    mode = st.radio("How to adjust", ["drag", "click", "type", "move"], horizontal=True, key="gis_mode",
                    format_func={"drag": "🖐️ Drag corners on map", "click": "👆 Click map to place a corner", "type": "⌨️ Type lat / lng",
                                 "move": "↔️ Move whole parcel"}.get)
    corner = None
    if mode == "click":
        corner = st.selectbox("Corner to move (then click its new position on the map)", range(len(draft)), format_func=lambda i: f"Corner {i + 1}", key="gis_corner")
    lat0 = sum(p[1] for p in draft) / len(draft)
    lon0 = sum(p[0] for p in draft) / len(draft)
    m = _base_map((lat0, lon0))
    _others(m, skip=pid)
    folium.Polygon([[la, lo] for lo, la in saved], color="#ffffff", weight=2, dash_array="6 6", fill=False, tooltip="Saved outline").add_to(m)
    fg = folium.FeatureGroup(name="Draft outline (editable)")
    folium.Polygon([[la, lo] for lo, la in draft], color="#ffe600", weight=3, fill=True, fill_color="#f77f00", fill_opacity=0.2, tooltip="Draft").add_to(fg)
    fg.add_to(m)
    if mode == "drag":
        Draw(feature_group=fg, export=False, draw_options={k: False for k in ("polyline", "polygon", "rectangle", "circle", "marker", "circlemarker")},
             edit_options={"edit": True, "remove": False}).add_to(m)
    add_corner_markers(m, draft)
    add_map_tools(m)
    folium.LayerControl().add_to(m)
    lons, lats = [p[0] for p in draft + saved], [p[1] for p in draft + saved]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(40, 40), max_zoom=20)
    if mode == "drag":
        st.info("Click the **pencil** (left of the map), drag the white corner handles, then press **Save** in the map toolbar and the button below the map.")
    res = st_folium(m, height=540, use_container_width=True, returned_objects=["all_drawings", "last_clicked"],
                    key=f"gis_map_{pid}_{mode}_{hash(tuple(draft))}")
    res = res or {}
    if mode == "drag":
        polys = [d["geometry"]["coordinates"][0][:-1] for d in (res.get("all_drawings") or []) if d.get("geometry", {}).get("type") == "Polygon"]
        if polys and st.button("Use the dragged corners", type="primary", key="gis_use_drag"):
            st.session_state[dk] = [(round(x, 7), round(y, 7)) for x, y in polys[-1]]
            st.rerun()
    elif mode == "click":
        c = res.get("last_clicked")
        if c and st.session_state.get("gis_last_click") != (c["lat"], c["lng"]):
            st.session_state["gis_last_click"] = (c["lat"], c["lng"])
            new = list(draft)
            new[corner] = (round(c["lng"], 7), round(c["lat"], 7))
            st.session_state[dk] = new
            st.rerun()
    elif mode == "type":
        df = pd.DataFrame([{"corner": i + 1, "lat": y, "lng": x} for i, (x, y) in enumerate(draft)])
        ed = st.data_editor(df, num_rows="dynamic", hide_index=True, key=f"gis_tbl_{pid}_{hash(tuple(draft))}",
                            column_config={"corner": st.column_config.NumberColumn(disabled=True),
                                           "lat": st.column_config.NumberColumn(format="%.7f", min_value=23.5, max_value=24.5),
                                           "lng": st.column_config.NumberColumn(format="%.7f", min_value=90.0, max_value=91.0)})
        if st.button("Apply typed coordinates", key="gis_apply_tbl"):
            rows = ed.dropna(subset=["lat", "lng"])
            st.session_state[dk] = [(round(float(r.lng), 7), round(float(r.lat), 7)) for r in rows.itertuples()]
            st.rerun()
    else:
        a, b, c = st.columns([1, 1, 1])
        east = a.number_input("East (+) / West (−) metres", -parcel_admin.MAX_SHIFT_M, parcel_admin.MAX_SHIFT_M, 0.0, 0.5, key="gis_e")
        north = b.number_input("North (+) / South (−) metres", -parcel_admin.MAX_SHIFT_M, parcel_admin.MAX_SHIFT_M, 0.0, 0.5, key="gis_n")
        c.write("")
        if c.button("Move draft", key="gis_move", use_container_width=True):
            try:
                st.session_state[dk] = parcel_admin.shift_points(draft, east, north)
                st.rerun()
            except EditError as e:
                st.error(str(e))

    if flash := st.session_state.pop("gis_flash", None):
        st.success(flash)
    st.subheader("Draft check")
    with closing(connect()) as con:
        try:
            chk = parcel_admin.check_outline(con, draft, pid)
            mm = chk["metrics"]
            k = st.columns(4)
            k[0].metric("Area", f"{mm['area_sqm']:.1f} m²", f"{mm['area_sqm'] - (by_id[pid]['area_calculated'] or 0):+.1f} m²")
            k[1].metric("Area (decimal)", f"{mm['area_decimal']:.2f}")
            k[2].metric("Perimeter", f"{mm['perimeter_m']:.1f} m")
            k[3].metric("Corners", len(draft))
            if chk["overlaps"]:
                st.warning("Shares area with: " + ", ".join(f"{o['parcel_id']} ({o['after_m2']} m², was {o['before_m2']} m²)" for o in chk["overlaps"])
                           + ". Existing overlaps may stay, but cannot grow.")
            ok = True
        except EditError as e:
            st.error(f"Cannot save this draft: {e}")
            ok = False
    reason = st.text_input("Reason for the change (goes to the audit log)", key="gis_reason", placeholder="e.g. Corner 2 moved to the wall seen in 2024 imagery after citizen report")
    a, b = st.columns(2)
    if a.button("💾 Save outline", type="primary", disabled=not (ok and dirty), use_container_width=True, key="gis_save"):
        with closing(connect()) as con:
            try:
                parcel_admin.update_outline(con, admin, pid, draft, reason)
                _changed()
                st.session_state.pop(dk, None)
                st.session_state["gis_flash"] = f"{pid}: outline saved and logged in the audit log. Re-run verification to see the effect."
                st.rerun()
            except EditError as e:
                st.error(str(e))
    if b.button("↩️ Discard draft", disabled=not dirty, use_container_width=True, key="gis_discard"):
        st.session_state.pop(dk, None)
        st.rerun()
    if not dirty:
        st.caption("The draft is the same as the saved outline. Adjust it above to enable Save.")

    with closing(connect()) as con:
        hist = parcel_admin.outline_history(con, pid)
    with st.expander(f"Change history of {pid} ({len(hist)})"):
        for h in hist:
            d = json.loads(h["detail_json"] or "{}")
            st.markdown(f"- `{h['ts']}` **{h['actor']}** · {h['action']} · {d.get('reason', '')}"
                        + (f" · area {d['old_area_sqm']} → {d['new_area_sqm']} m²" if "new_area_sqm" in d else ""))
        last = next((json.loads(h["detail_json"]) for h in hist if h["action"] == "parcel_outline_edit"), None)
        if last and st.button("Load the outline from before the last edit into the draft (undo)", key="gis_undo"):
            st.session_state[dk] = [tuple(x) for x in last["old"]]
            st.rerun()


def _new_tab(admin):
    st.caption("Draw the outline with the polygon or rectangle tool. The parcel gets an id JL-0001, JL-0002… and starts without land records.")
    lm = places.landmarks()
    options = [("Joydebpur centre", places.FOCUS_CENTER)] + [(x["name"], (x["lat"], x["lon"])) for x in lm[:40]]
    at = st.selectbox("Start the map at", range(len(options)), format_func=lambda i: options[i][0], key="gis_new_at")
    m = _base_map(options[at][1], zoom=18)
    _others(m)
    fg = folium.FeatureGroup(name="New parcel")
    fg.add_to(m)
    Draw(feature_group=fg, export=False, draw_options={"polygon": {"allowIntersection": False}, "rectangle": True, "polyline": False, "circle": False,
                                                       "marker": False, "circlemarker": False}, edit_options={"edit": True, "remove": True}).add_to(m)
    add_map_tools(m)
    folium.LayerControl().add_to(m)
    res = st_folium(m, height=500, use_container_width=True, returned_objects=["all_drawings"], key=f"gis_new_map_{at}") or {}
    polys = [d["geometry"]["coordinates"][0][:-1] for d in (res.get("all_drawings") or []) if d.get("geometry", {}).get("type") == "Polygon"]
    if not polys:
        st.info("Draw one outline on the map.")
        return
    pts = [(round(x, 7), round(y, 7)) for x, y in polys[-1]]
    with closing(connect()) as con:
        try:
            chk = parcel_admin.check_outline(con, pts)
            st.success(f"Outline OK: {chk['metrics']['area_sqm']:.1f} m² ({chk['metrics']['area_decimal']:.2f} decimal), {len(pts)} corners.")
        except EditError as e:
            st.error(str(e))
            return
    with st.form("gis_new_form"):
        title = st.text_input("Title", placeholder="e.g. Corner plot near the rail line")
        mouza = st.selectbox("Mouza", [f"Demo Mouza {i}" for i in range(1, 6)] + ["Other demo mouza"])
        price = st.number_input("Asking price (BDT, fictional, optional)", 0, 10_000_000_000, 0, 100_000)
        if st.form_submit_button("Create parcel", type="primary"):
            with closing(connect()) as con:
                try:
                    pid = parcel_admin.create_parcel(con, admin, pts, title, mouza, price or None)
                    _changed()
                    st.success(f"Created {pid}. Open it in the outline editor or the parcel profile.")
                except EditError as e:
                    st.error(str(e))


def _retire_tab(admin):
    with closing(connect()) as con:
        rows = vdb.list_parcels(con, include_retired=True)
    pick = st.selectbox("Parcel", [r["parcel_id"] for r in rows], key="gis_ret_pick",
                        format_func=lambda k: next(f"{r['parcel_id']} · {r['scenario_title']} · {r['status']}" for r in rows if r["parcel_id"] == k))
    row = next(r for r in rows if r["parcel_id"] == pick)
    reason = st.text_input("Reason", key="gis_ret_reason")
    new = "retired" if row["status"] == "active" else "active"
    if st.button("Retire (hide from citizens)" if new == "retired" else "Restore", key="gis_ret_go"):
        with closing(connect()) as con:
            try:
                parcel_admin.set_parcel_status(con, admin, pick, new, reason)
                _changed()
                st.session_state["gis_flash"] = f"{pick} is now {new}."
                st.rerun()
            except EditError as e:
                st.error(str(e))
    st.caption("Retired parcels keep their records and history; they are only hidden from maps, search and verification.")
