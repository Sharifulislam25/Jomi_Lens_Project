"""🛰️ Satellite history and land-use analysis for the selected parcel (real Esri Wayback imagery, cautious language)."""
from contextlib import closing

import streamlit as st

from src import vdb, vstate
from src.log import logger
from src.real_analysis import prepare_history
from src.ui_analysis import analysis_view
from src.ui_parcel import _classify
from src.vcommon import DISCLAIMER, connect, metrics_for, parcel_picker
from src import sentinel
from src.wayback import ATTRIBUTION as ESRI_ATTRIBUTION, padded_bbox, try_fetch_history


def render():
    st.header("🛰️ Satellite history and land use")
    st.caption("Default source: open Copernicus Sentinel-2 imagery (10 m, real capture dates, same season each year). Optional: Esri high-resolution viewer "
               "(not open data; release dates only). Results are possible surface changes and predicted classes, never ownership, legal boundary or legal land use.")
    p = parcel_picker("sv_pick")
    if not p:
        return
    pid = p["parcel_id"]
    m, err = metrics_for(p)
    if err:
        st.error(f"This geometry is not valid, so imagery cannot be analysed: {err}")
        return
    if p["is_synthetic"]:
        st.warning("The parcel is synthetic, but the imagery at its location is real. A synthetic outline on real land says nothing about the real land's ownership.")
    source = st.segmented_control("Imagery source", ["Sentinel-2 (open data)", "Esri high-resolution (viewing only)"], default="Sentinel-2 (open data)",
                                  key="sv_source", label_visibility="collapsed") or "Sentinel-2 (open data)"
    use_s2 = source.startswith("Sentinel")
    if not use_s2:
        st.warning("Esri World Imagery is not open data: use it for viewing only, check Esri's terms for any wider use, and note that its dates are release dates.")
    img = vstate.current_imagery(st.session_state)
    ebbox = padded_bbox(m["bounds"])
    key = (("s2" if use_s2 else "esri"),) + tuple(round(v, 6) for v in (sentinel.window_bbox(m["bounds"]) if use_s2 else ebbox))
    centre = (round(m["centroid"][1], 6), round(m["centroid"][0], 6))
    if img is None or img.get("key") != key:
        st.info("Imagery is downloaded on request (about 10-30 seconds; needs internet). The rest of the workflow works without it.")
        if st.button("🛰️ Fetch satellite history", type="primary", key="sv_fetch"):
            with st.spinner("Downloading imagery..."):
                if use_s2:
                    hist, msg, bbox = sentinel.try_fetch_history(m["bounds"])
                else:
                    hist, msg = try_fetch_history(key[1:], centre)
                    bbox = ebbox
            prepared = prepare_history(hist, bbox, m["points"]) if hist else []
            vstate.store_imagery(st.session_state, pid, {"key": key, "prepared": prepared, "message": msg, "source": "sentinel2" if use_s2 else "esri"})
            if prepared and p["is_synthetic"]:
                with closing(connect()) as con:
                    vdb.save_imagery_observations(con, pid, [{"provider": h.get("provider") or "Esri World Imagery Wayback", "imagery_item_id": h.get("item_id") or f"wayback:{h['date']}",
                                                              "release_date": None if use_s2 else h["date"], "capture_date": h["date"] if use_s2 else None,
                                                              "resolution_m": h["resolution_m"],
                                                              "quality_notes": (f"Scene cloud cover {h.get('cloud_cover')}%; season {h.get('season')}" if use_s2 else
                                                                                f"Release (version) date; capture date not provided. Tile zoom {h['zoom']}."),
                                                              "attribution": sentinel.ATTRIBUTION if use_s2 else ESRI_ATTRIBUTION} for h in prepared])
            logger.info("imagery fetched parcel=%s source=%s versions=%d ok=%s", pid, "s2" if use_s2 else "esri", len(prepared), bool(prepared))
            st.rerun()
        return
    if not img["prepared"]:
        st.warning(img.get("message") or "Satellite imagery is unavailable for this location.")
        if st.button("🔄 Try again", key="sv_retry"):
            st.session_state.pop("vp_img", None)
            st.rerun()
        st.caption("The rest of the parcel workflow (profile, verification, report) still works without imagery.")
        return

    def land_use():
        cls = st.session_state.get("vp_class")
        if st.button("🏷️ Run rule-based land-use classification", key="sv_cls"):
            res = _classify(p, m)
            st.session_state["vp_class"] = {"parcel_id": pid, **res}
            cls = st.session_state["vp_class"]
        if cls and cls.get("parcel_id") == pid:
            st.write(f"**Predicted class:** {cls['class_label']} · method: {cls['method']} ({cls['model_version']}) · confidence: **not calibrated** · review: {cls['review_status']}")
            st.caption(cls["evidence_summary"])
            for c_ in cls["caveats"]:
                st.write("- " + c_)
        else:
            st.info("Not run yet. The label comes from mapped OpenStreetMap features at the parcel centre, with imagery greenness only as a preliminary hint.")

    details = {"recorded_area": 0.0}
    analysis_view(p["points"], details, key=f"vs_{pid}", hist=img["prepared"], extra={"🏷️ Land use": land_use},
                  hide=("📄 Report",), hist_hint="No imagery loaded.")
    st.caption(DISCLAIMER)
