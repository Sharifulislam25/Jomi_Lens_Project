"""Shared analysis view used by 📐 My Plot and 🏙️ Demo Sites.
It is a fragment (changing a widget here does not re-run the whole page) and shows ONE section at a time, so hidden
sections do no work."""
import json
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

from src.geo_tools import GeometryError, dms, polygon_metrics
from src.map_utils import build_user_plot_map
from src.real_analysis import GENERAL_MESSAGE, compare_real, real_anomalies, with_outline
from src.wayback import ATTRIBUTION

MAX_CORNER_MARKERS = 40


def _b64(img) -> str:
    import base64, io
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def slider_html(a, b, label_a, label_b, max_w=760) -> tuple:
    """Self-contained before/after slider (pure HTML/JS, no extra package). Returns (html, height)."""
    max_w = min(max_w, int(620 * a.width / a.height))   # keep the slider at most ~620 px tall
    h = int(max_w * a.height / a.width) + 6
    html = f"""<style>
body{{margin:0;font-family:sans-serif}}
#c{{position:relative;max-width:{max_w}px;aspect-ratio:{a.width}/{a.height};overflow:hidden;border-radius:12px;cursor:ew-resize;
    touch-action:none;user-select:none;box-shadow:0 2px 10px rgba(0,0,0,.25)}}
#c img{{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none}}
#top{{clip-path:inset(0 50% 0 0)}}
#bar{{position:absolute;top:0;bottom:0;left:50%;width:3px;background:#fff;box-shadow:0 0 6px rgba(0,0,0,.6)}}
#knob{{position:absolute;top:50%;left:50%;width:38px;height:38px;margin:-19px 0 0 -19px;border-radius:50%;background:#fff;
      box-shadow:0 0 8px rgba(0,0,0,.5);text-align:center;line-height:38px;font-weight:bold;color:#0e7c86}}
.lb{{position:absolute;top:10px;padding:3px 10px;background:rgba(0,0,0,.55);color:#fff;border-radius:6px;font-size:13px}}
</style>
<div id="c"><img src="data:image/jpeg;base64,{_b64(b)}"><img id="top" src="data:image/jpeg;base64,{_b64(a)}">
<span class="lb" style="left:10px">{label_a}</span><span class="lb" style="right:10px">{label_b}</span>
<div id="bar"></div><div id="knob">&#8596;</div></div>
<script>
const c=document.getElementById('c'),t=document.getElementById('top'),bar=document.getElementById('bar'),k=document.getElementById('knob');
function set(x){{const r=c.getBoundingClientRect();let p=Math.min(1,Math.max(0,(x-r.left)/r.width))*100;
 t.style.clipPath='inset(0 '+(100-p)+'% 0 0)';bar.style.left=p+'%';k.style.left=p+'%';}}
let d=false;c.addEventListener('pointerdown',e=>{{d=true;c.setPointerCapture(e.pointerId);set(e.clientX)}});
c.addEventListener('pointermove',e=>{{if(d)set(e.clientX)}});c.addEventListener('pointerup',()=>d=false);
</script>"""
    return html, h


def compare_slider(a, b, label_a, label_b):
    """Draggable before/after slider for two same-size images."""
    html, h = slider_html(a, b, label_a, label_b)
    try:
        st.iframe(html, height=h)
    except AttributeError:  # older Streamlit
        import streamlit.components.v1 as components
        components.html(html, height=h)


def _default_before(dates):
    """Prefer a version from 2017 or later as the 'before' image (older ones come from different sensors)."""
    for i, d in enumerate(dates[:-1]):
        if d >= "2017-01-01":
            return i
    return 0


@st.fragment
def analysis_view(points, details, key, hist=None, extra=None, hist_hint="", hide=()):
    """points=[(lon,lat)], details=dict for the report, hist=prepared real imagery (or None), extra={label: callable}."""
    with st.popover("⚙️ Units"):
        katha = st.number_input("Katha size (sq ft)", 300.0, 1000.0, 720.0, 10.0, key=f"{key}_katha",
                                help="A katha differs between regions. 720 sq ft is common in the Dhaka region.")
    try:
        m = polygon_metrics(points, katha_sqft=katha)
    except GeometryError as exc:
        st.error(f"This outline cannot be analysed: {exc}")
        return
    c = st.columns(6)
    c[0].metric("Area (m²)", f"{m['area_sqm']:,.0f}")
    c[1].metric("Hectares", f"{m['area_sqm'] / 1e4:,.2f}")
    c[2].metric("Decimal", f"{m['area_decimal']:,.1f}")
    c[3].metric("Katha", f"{m['area_katha']:,.1f}")
    c[4].metric("Bigha", f"{m['area_bigha']:,.2f}")
    c[5].metric("Perimeter (m)", f"{m['perimeter_m']:,.0f}")
    if not m["valid"]:
        st.error("The sides of this shape cross each other, so the area is not reliable.")
    if details.get("recorded_area"):
        diff = m["area_decimal"] - details["recorded_area"]
        pct = abs(diff) / details["recorded_area"] * 100
        (st.warning if pct >= 5 else st.success)(
            f"Recorded area {details['recorded_area']} dec vs marked-boundary area {m['area_decimal']:.2f} dec: {diff:+.2f} dec ({pct:.1f}%). "
            "This does not prove an error in either; marked corners may be imprecise.")

    sections = [x for x in ["📍 Location", "🛰️ Satellite history", "🔍 Change check"] + list((extra or {}).keys()) + ["📄 Report"] if x not in hide]
    sec = st.segmented_control("Section", sections, default=sections[0], key=f"{key}_sec", label_visibility="collapsed") or sections[0]
    centre = m["centroid"]

    # ---------------- Location ----------------
    if sec == "📍 Location":
        many = len(points) > MAX_CORNER_MARKERS
        st_folium(build_user_plot_map(points, centre, markers=not many, dates=[h["date"] for h in hist] if hist else None), height=470, use_container_width=True,
                  returned_objects=[], key=f"{key}_map")
        st.markdown(f"**Plot centre:** {centre[0]:.6f}, {centre[1]:.6f}  \n{dms(centre[0], 'N', 'S')}, {dms(centre[1], 'E', 'W')}")
        corners = pd.DataFrame(m["corners"]).rename(columns={"n": "Corner", "lat": "Latitude", "lon": "Longitude",
                                                            "lat_dms": "Latitude (DMS)", "lon_dms": "Longitude (DMS)"})
        with st.expander(f"Corner coordinates ({len(corners)} vertices)", expanded=not many):
            st.dataframe(corners, hide_index=True, width="stretch", height=min(320, 38 + 35 * len(corners)))
        with st.expander("Side lengths and bearings"):
            st.dataframe(pd.DataFrame(m["sides"]).rename(columns={"from": "From", "to": "To", "length_m": "Length (m)", "bearing_deg": "Bearing (°)"}),
                         hide_index=True, width="stretch", height=min(320, 38 + 35 * len(m["sides"])))
        gj = {"type": "Feature", "properties": {"area_sqm": m["area_sqm"]},
              "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in points] + [list(points[0])]]}}
        a, b = st.columns(2)
        a.download_button("⬇️ Corner coordinates (CSV)", corners.to_csv(index=False), "plot_corners.csv", "text/csv", key=f"{key}_dl1")
        b.download_button("⬇️ Boundary (GeoJSON)", json.dumps(gj), "plot_boundary.geojson", "application/geo+json", key=f"{key}_dl2")
        st.caption("Coordinates are exactly what was marked. Real-world accuracy depends on how the corners were measured; for a legal "
                   "boundary use the Upazila Land Office and a licensed surveyor.")

    # ---------------- Satellite history ----------------
    elif sec == "🛰️ Satellite history":
        if not hist:
            st.info(hist_hint or "Real satellite history is not loaded yet.")
        else:
            dates = [h["date"] for h in hist]
            sel = st.select_slider("Imagery version (drag to move through time)", options=dates, value=dates[-1], key=f"{key}_ver")
            h = hist[dates.index(sel)]
            st.image(with_outline(h["raw"], h["poly_px"]), width="stretch",
                     caption=f"Version {h['date']} - about {h['resolution_m']} m per pixel - plot outline in yellow")
            st.plotly_chart(px.line(pd.DataFrame({"Version": dates, "Greenness": [x["greenness"] for x in hist]}), x="Version", y="Greenness",
                                    markers=True, title="Greenness inside the plot over time").update_layout(margin=dict(t=40, b=10), height=300),
                            width="stretch")
            with st.expander("Imagery version details"):
                cap = hist[0].get("date_kind") == "capture"
                if cap:
                    st.dataframe([{"Capture date": x["date"], "Season": x.get("season"), "Cloud cover (scene, %)": x.get("cloud_cover"),
                                   "Resolution (m/pixel)": x["resolution_m"], "Scene": x.get("item_id")} for x in hist], hide_index=True, width="stretch")
                    st.caption("Capture dates come from the Sentinel-2 scene metadata. One scene per dry season (Dec-Feb) is used so images are comparable. "
                               "10 m pixels: small parcels cover only a few pixels.")
                else:
                    st.dataframe([{"Version (release) date": x["date"], "Capture date": "not provided by this source", "Resolution (m/pixel)": x["resolution_m"],
                                   "Tile zoom": x["zoom"]} for x in hist], hide_index=True, width="stretch")
                    st.caption("The date shown is the Esri Wayback release (version) date of the basemap. It is NOT the date the image was captured; "
                               "resolution and seasonal conditions differ between versions.")
            st.caption("Version dates are Esri Wayback release dates, not necessarily capture dates; resolution, sensor and season differ. "
                       "Greenness = excess-green index inside the plot. " + ATTRIBUTION)

    # ---------------- Change check ----------------
    elif sec == "🔍 Change check":
        if not hist or len(hist) < 2:
            st.info(hist_hint or "Real satellite history is needed first.")
        else:
            dates = [h["date"] for h in hist]
            c1, c2, c3 = st.columns(3)
            b = c1.selectbox("Before", dates, index=_default_before(dates), key=f"{key}_b")
            a = c2.selectbox("After", dates, index=len(dates) - 1, key=f"{key}_a")
            is_s2 = hist[0].get("date_kind") == "capture"
            thr = c3.slider("Sensitivity threshold", 0.5, 4.0, 3.0 if is_s2 else 2.0, 0.25, key=f"{key}_thr_{'s2' if is_s2 else 'esri'}",
                            help="Higher = only stronger differences count. 10 m imagery needs a higher default because of atmosphere and sensor noise.")
            if dates.index(b) >= dates.index(a):
                st.warning("Choose a Before version earlier than the After version.")
            else:
                hb, ha = hist[dates.index(b)], hist[dates.index(a)]
                memo = st.session_state.setdefault("cmp_memo", {})
                mk = (key, b, a, thr)
                if mk not in memo:
                    memo[mk] = compare_real(hb, ha, thr)
                cmp = memo[mk]
                st.markdown("**Drag the slider to compare** (plot outline in yellow)")
                compare_slider(with_outline(hb["raw"], hb["poly_px"]), with_outline(ha["raw"], ha["poly_px"]), f"Before {b}", f"After {a}")
                i3, i4 = st.columns(2)
                i3.image(cmp["difference"], caption="Difference (brighter = larger)", width="stretch")
                i4.image(cmp["overlay"], caption="Changed pixels inside the plot (red)", width="stretch")
                m1, m2, m3 = st.columns(3)
                m3.metric("Changed share of the whole view", f"{cmp['changed_pct_area']}%", help="Context: the same measure over the whole image, including surroundings. If it is similar to the parcel's share, the difference may be noise rather than a change specific to the parcel.")
                m1.metric("Changed share of the plot", "unavailable" if cmp["changed_pct_plot"] is None else f"{cmp['changed_pct_plot']}%")
                m2.metric("Greenness change", "unavailable" if cmp["greenness_change"] is None else f"{cmp['greenness_change']:+}")
                for w in cmp.get("warnings", []):
                    st.warning(w)
                an = real_anomalies(cmp, details.get("recorded_area") or None, m["area_decimal"] if details.get("recorded_area") else None)
                if an:
                    st.warning(GENERAL_MESSAGE)
                    for x in an:
                        with st.expander(f"{x['type']} - {x['status']}", expanded=True):
                            st.write(x["observation"])
                else:
                    st.success("No anomaly detected in the available imagery for these two versions.")
                st.caption("Real images from different dates differ in season, sensor, sun angle and resolution, which can look like change. "
                           "Treat results as potential observations only.")
                st.session_state[f"{key}_cmp"] = {"before": b, "after": a, "cmp": cmp, "anomalies": an, "threshold": thr,
                                                  "before_resolution_m": hb.get("resolution_m"), "after_resolution_m": ha.get("resolution_m")}

    # ---------------- extra sections ----------------
    elif sec in (extra or {}):
        extra[sec]()

    # ---------------- Report ----------------
    else:
        st.write("A PDF with plot details, precise corner coordinates, a satellite view, the real imagery history, the change check, "
                 "potential anomalies, a verification checklist and a disclaimer.")
        if st.button("📄 Generate report", type="primary", key=f"{key}_gen"):
            from src.report_generator import generate_custom_report
            with st.spinner("Building report..."):
                try:
                    case = {"details": details, "metrics": m, "history": hist or [], "compare": st.session_state.get(f"{key}_cmp")}
                    path, data = generate_custom_report(case)
                    st.session_state[f"{key}_report"] = {"name": path.name, "data": data}
                    st.session_state["reports"] = st.session_state.get("reports", 0) + 1
                except Exception as exc:
                    st.error(f"Report could not be generated: {exc}")
        last = st.session_state.get(f"{key}_report")
        if last:
            st.success(f"Report ready: {last['name']} ({len(last['data']) // 1024} KB)")
            st.download_button("⬇️ Download PDF", last["data"], file_name=last["name"], mime="application/pdf", key=f"{key}_dlr")
