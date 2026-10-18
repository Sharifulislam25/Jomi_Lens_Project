"""📄 Reports: PDF for the CURRENT parcel and CURRENT verification run."""
from contextlib import closing

import streamlit as st

from src import i18n, vdb, vstate
from src.log import logger
from src.report_generator import generate_verify_report
from src.ui_verify import current_settings
from src.vcommon import DISCLAIMER, SYNTH_NOTE, connect, metrics_for, parcel_picker


def render():
    st.header("📄 " + i18n.t("nav.report"))
    st.caption(SYNTH_NOTE)
    p = parcel_picker("rp_pick")
    if not p:
        return
    pid = p["parcel_id"]
    m, err = metrics_for(p)
    if err:
        st.error(f"The geometry is not valid, so no report can be created: {err}")
        return
    run = vstate.current_run(st.session_state)
    img = vstate.current_imagery(st.session_state)
    cls = st.session_state.get("vp_class")
    cls = cls if cls and cls.get("parcel_id") == pid else None
    cmp_ = st.session_state.get(f"vs_{pid}_cmp") if img else None

    st.markdown("#### What will be in the report")
    st.write(f"- Parcel **{pid}**, geometry and measurements: ready")
    st.write("- Verification run: " + (f"**{run['overall_status']}** from {run['created_at']}" if run else "**not run**"))
    st.write("- Satellite imagery: " + (f"{len(img['prepared'])} versions loaded" if img and img.get("prepared") else "not loaded (section will say so)"))
    st.write("- Before/after comparison: " + ("included" if cmp_ else "not run"))
    st.write("- Land-use result: " + (cls["class_label"] if cls else "not run"))

    if p["is_synthetic"] and not run:
        st.warning("Run the verification for this parcel first (Verification page). A report needs the current run.")
        return
    stale = bool(run) and vstate.run_is_stale(run, current_settings(), list(st.session_state.get("vp_uploads", {})))
    if stale:
        st.warning("The verification settings or uploaded files changed since the last run. Run verification again so the report matches the current settings.")
        return

    if st.button("📄 Generate report", type="primary", key="rp_go"):
        try:
            records = txs = docs = []
            ctx = {}
            if p["is_synthetic"]:
                with closing(connect()) as con:
                    records, txs, docs, ctx = vdb.get_records(con, pid), vdb.get_transactions(con, pid), vdb.get_documents(con, pid), vdb.verification_context(con, pid)
            case = {"parcel": p, "metrics": m, "records": records, "transactions": txs, "run": run, "run_id": st.session_state.get("vp_run_id"),
                    "documents": [{k: v for k, v in d.items() if k != "content"} for d in docs], "imagery": img, "comparison": cmp_, "classification": cls, "context": ctx}
            with st.spinner("Building the PDF..."):
                path, data = generate_verify_report(case)
            st.session_state["vp_report"] = {"parcel_id": pid, "name": path.name, "data": data}
            st.session_state["reports"] = st.session_state.get("reports", 0) + 1
            logger.info("report built parcel=%s file=%s", pid, path.name)
        except Exception as exc:
            logger.exception("report failed parcel=%s", pid)
            st.error(f"The report could not be created ({type(exc).__name__}: {exc}). The error was logged; nothing was generated.")
    rep = st.session_state.get("vp_report")
    if rep and rep["parcel_id"] == pid:
        st.success(f"Report ready: {rep['name']} ({len(rep['data']) // 1024} KB)")
        st.download_button("⬇️ Download PDF", rep["data"], file_name=rep["name"], mime="application/pdf", key="rp_dl")
    st.caption(DISCLAIMER)
