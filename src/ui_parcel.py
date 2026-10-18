"""📍 Parcel profile: geometry, boundary source, record coverage, land use, imagery availability and limits."""
from contextlib import closing

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import i18n, landmap, vdb, vstate
from src.geo_tools import dms, to_sqm
from src.landuse import classify_parcel
from src.map_utils import build_user_plot_map
from src.nav import PAGES
from src.places import locate
from src.vcommon import (reference_search, BOUNDARY_LABELS, DISCLAIMER, SYNTH_NOTE, badge, connect, legend_html, metrics_for, parcel_boundary_badge, parcel_picker)


def _classify(p, m):
    c = m["centroid"]
    feats = landmap.at_point(c[1], c[0]) if landmap.available() else []
    img = vstate.current_imagery(st.session_state)
    green = None
    if img and img.get("prepared"):
        green = img["prepared"][-1].get("greenness")
    return classify_parcel(p["points"], [f for f in feats if f.get("contains")], green)


def render():
    st.header("📍 " + i18n.t("nav.profile"))
    st.caption(SYNTH_NOTE)
    with st.expander("🔎 " + i18n.t("find_ref"), expanded=False):
        reference_search("pp")
    p = parcel_picker("pp_pick")
    if not p:
        st.info("Select a parcel.")
        return
    pid = p["parcel_id"]
    m, err = metrics_for(p)
    if err:
        st.error(f"This parcel's geometry is not valid, so it cannot be profiled: {err}")
        return
    label, color = BOUNDARY_LABELS.get(p["boundary_type"], BOUNDARY_LABELS["unknown"])
    st.subheader(p.get("scenario_title") or pid)
    st.markdown(f"<span style='color:{color};font-weight:700'>● {label}</span> &nbsp; " + (":red-badge[SYNTHETIC]" if p["is_synthetic"] else ":gray-badge[not from the synthetic database]"),
                unsafe_allow_html=True)
    if p.get("scenario_description"):
        st.info(p["scenario_description"])

    c = st.columns(4)
    c[0].metric("Internal parcel ID", pid)
    c[1].metric("Calculated area", f"{m['area_sqm']:,.1f} m²")
    c[2].metric("In decimal", f"{m['area_decimal']:,.2f}")
    c[3].metric("Perimeter", f"{m['perimeter_m']:,.1f} m")
    st.caption(f"Calculated from the drawn geometry. {m['crs']}. This is **not** the officially recorded area.")

    lat_c, lon_c = m["centroid"]
    gmaps = f"https://www.google.com/maps?q={lat_c:.6f},{lon_c:.6f}"
    k = st.columns([1, 1, 1, 1.2])
    k[0].metric("Mouza", p.get("mouza") or "not recorded")
    if p.get("asking_price_bdt"):
        k[1].metric("Asking price (fictional)", f"৳ {p['asking_price_bdt']:,.0f}")
        k[2].metric("Per decimal", f"৳ {p['asking_price_bdt'] / max(m['area_decimal'], 0.01):,.0f}")
    else:
        k[1].metric("Asking price", "not listed")
    with k[3]:
        st.link_button("🌍 Open in Google Maps", gmaps, use_container_width=True)
        if "inbox" in PAGES and p.get("is_synthetic"):
            if st.button("🚩 Report a problem with this land", key=f"pp_rep_{pid}", use_container_width=True):
                st.switch_page(PAGES["inbox"])
    if p.get("asking_price_bdt"):
        st.caption("Asking prices are invented for the demo. They are not a valuation or a market price.")

    loc = p.get("administrative_area") or ""
    if not loc:
        l = locate(m["centroid"][1], m["centroid"][0])
        loc = f"{l['upazila']}, {l['district']}, {l['division']} (BBS/OCHA, generalised)"
    prof = [("Boundary type", label), ("Boundary source", p.get("boundary_source") or "unknown"),
            ("Boundary source date", p.get("boundary_source_date") or "not known"), ("Administrative area", loc),
            ("Centre (lat, lon)", f"{m['centroid'][0]:.6f}, {m['centroid'][1]:.6f} ({dms(m['centroid'][0], 'N', 'S')}, {dms(m['centroid'][1], 'E', 'W')})")]
    st.table(pd.DataFrame(prof, columns=["Field", "Value"]).set_index("Field"))

    # ---- records
    st.markdown("#### Linked records")
    records, txs, docs, surveys, ctx = [], [], [], [], {}
    if p["is_synthetic"]:
        with closing(connect()) as con:
            records, txs, docs, ctx = vdb.get_records(con, pid), vdb.get_transactions(con, pid), vdb.get_documents(con, pid), vdb.verification_context(con, pid)
    surveys = [r for r in records if r.get("survey_gen")]
    records = [r for r in records if not r.get("survey_gen")]
    if records:
        st.success(f"Record coverage: {len(records)} FICTIONAL records, {len(txs)} simulated transaction(s), {len(docs)} synthetic document(s).")
        rows = []
        for r in records:
            sqm = None
            try:
                sqm = to_sqm(r["recorded_area"], r["area_unit"]) if r["recorded_area"] is not None else None
            except ValueError:
                pass
            rows.append({"Type": r["record_type"], "Reference (fictional)": r["record_reference"], "Dag": r["dag_ref"], "Khatian": r["khatian_ref"],
                         "Recorded area": f"{r['recorded_area']} {r['area_unit']}", "≈ m²": None if sqm is None else round(sqm, 1), "Date": r["record_date"],
                         "Party label (fictional)": r["recorded_party_label"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("The recorded area comes from the synthetic records; the calculated area comes from the synthetic geometry. They are different things and need not be equal.")
        if surveys:
            st.markdown("**Survey generations (CS → SA → RS → BS)**")
            st.dataframe(pd.DataFrame([{"Generation": r["survey_gen"], "Reference": r["record_reference"], "Dag": r["dag_ref"], "Declares previous dag": r["prev_dag_ref"],
                                        "Area": f"{r['recorded_area']} {r['area_unit']}", "Year": (r["record_date"] or "")[:4]} for r in surveys]), hide_index=True, width="stretch")
            st.caption("Dag numbers change between surveys; each later survey should declare the earlier dag it came from.")
        cov = ctx.get("coverage", {})
        st.markdown("**Registers (synthetic)**")
        st.write(f"Case register covers this parcel: **{'yes' if cov.get('case_register') else 'NO (absence of a case cannot be confirmed)'}** · "
                 f"Khas / acquisition register covers this parcel: **{'yes' if cov.get('khas_register') else 'NO (absence of a notice cannot be confirmed)'}**  \n"
                 f"Encumbrance (mortgage / lien) register covers this parcel: **{'yes' if cov.get('encumbrance_register') else 'NO (absence of a mortgage cannot be confirmed)'}**")
        if ctx.get("encumbrances"):
            st.dataframe(pd.DataFrame([{"Entry": e["entry_id"], "Kind": e["kind"], "Holder (synthetic)": e["holder_label"], "Status": e["status"],
                                        "Registered": e["registered_date"], "Released": e["released_date"] or "-", "Note": e["notes"]} for e in ctx["encumbrances"]]),
                         hide_index=True, width="stretch")
        if ctx.get("cases"):
            st.dataframe(pd.DataFrame([{"Case": c_["case_id"], "Type": c_["case_type"], "Court (synthetic)": c_["court_label"], "Status": c_["status"], "Filed": c_["filed_date"],
                                        "Restricts transfer": bool(c_["restricts_transfer"]), "Note": c_["notes"]} for c_ in ctx["cases"]]), hide_index=True, width="stretch")
        if ctx.get("khas"):
            st.dataframe(pd.DataFrame([{"Entry": k["entry_id"], "Type": k["status_type"], "Authority (synthetic)": k["authority_label"], "Notice": k["notice_ref"], "Date": k["notice_date"],
                                        "Status": k["status"], "Note": k["notes"]} for k in ctx["khas"]]), hide_index=True, width="stretch")
    elif p["is_synthetic"]:
        st.warning("Record coverage: none. This synthetic parcel has no records, so its ownership is unknown and every record check will be unavailable. "
                   "Only the boundary-overlap check can run.")
    else:
        st.warning("Record coverage: none. This is a " + label.lower() + "; this prototype does not access real land records. Use a demo parcel for the verification workflow.")

    # ---- land use
    st.markdown("#### Land use")
    cls = st.session_state.get("vp_class")
    if not cls or cls.get("parcel_id") != pid:
        cls = None
    stored = None
    if p["is_synthetic"]:
        with closing(connect()) as con:
            stored = vdb.get_classifications(con, pid)
    if stored:
        s0 = stored[-1]
        st.write(f"**Recorded label:** {s0['class_label']} · method: {s0['method']} · confidence: not calibrated · review: {s0['review_status']}  \n{s0['evidence_summary']}")
    if st.button("🏷️ Run rule-based land-use classification", key="pp_cls"):
        res = _classify(p, m)
        st.session_state["vp_class"] = {"parcel_id": pid, **res}
        if p["is_synthetic"]:
            with closing(connect()) as con:
                vdb.save_classification(con, pid, res)
        cls = st.session_state["vp_class"]
    if cls:
        st.write(f"**Predicted land-use class:** {cls['class_label']} · method: {cls['method']} ({cls['model_version']}) · confidence: **not calibrated, not reported** · review: {cls['review_status']}")
        st.caption(cls["evidence_summary"])
        with st.expander("Limitations of this label"):
            for c_ in cls["caveats"]:
                st.write("- " + c_)
    elif not stored:
        st.info("No land-use label yet. Run the rule-based classification above (it uses mapped features, not a trained model).")

    # ---- imagery + unresolved
    img = vstate.current_imagery(st.session_state)
    obs = 0
    if p["is_synthetic"]:
        with closing(connect()) as con:
            obs = len(vdb.get_imagery_observations(con, pid))
    st.markdown("#### Imagery timeline")
    st.write(f"{len(img['prepared'])} imagery versions loaded in this session." if img and img.get("prepared") else
             (f"{obs} imagery observation(s) saved earlier for this parcel. Open **Satellite & land use** to load them again." if obs else
              "Not loaded yet. Open **Satellite & land use** to fetch the real imagery versions (needs internet)."))
    run = vstate.current_run(st.session_state)
    st.markdown("#### Unresolved checks and limitations")
    items = []
    if p["boundary_type"] != "official_verified":
        items.append("The boundary is not an authenticated official boundary, so any area, overlap or location statement is approximate.")
    if run:
        for r in run["results"]:
            if r["status"] != "PASS":
                items.append(f"{r['title']}: {r['status']}. {r['summary']}")
    elif p["is_synthetic"]:
        items.append("Verification has not been run for this parcel yet.")
    items.append("Satellite imagery and mapped features do not establish ownership, legal boundary or legal land use.")
    for i in items:
        st.write("- " + i)

    st.markdown("#### Boundary overlap with registered (synthetic) parcels")
    from src.geo_tools import GeometryError as _GE, overlap_sqm
    with closing(connect()) as con:
        others = vdb.other_parcels(con, pid)
    hits = []
    for o in others:
        try:
            a = overlap_sqm(p["points"], o["points"])
        except _GE:
            continue
        if a >= 1.0:
            hits.append({"Overlaps parcel": o["parcel_id"], "Title": o["title"], "Shared area (m²)": round(a, 1), "Share of this parcel (%)": round(100 * a / m["area_sqm"], 1)})
    if hits:
        st.error(f"This boundary overlaps {len(hits)} registered parcel(s). The same land may be registered twice; a surveyor must resolve it.")
        st.dataframe(pd.DataFrame(hits), hide_index=True, width="stretch")
    else:
        st.success(f"No overlap with any of the {len(others)} registered (synthetic) parcels.")
    st.caption("Only the synthetic register is compared. Real neighbouring parcels are unknown to this prototype.")

    st.markdown("#### Map")
    st_folium(build_user_plot_map(p["points"], m["centroid"], markers=len(p["points"]) <= 40), height=420, use_container_width=True,
              returned_objects=[], key=f"pp_map_{pid}")
    st.markdown(legend_html(), unsafe_allow_html=True)
    st.caption(DISCLAIMER)
