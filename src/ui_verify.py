"""✅ Verification workspace: ten checks on a synthetic case, under a traffic-light summary, grouped, each read on its own; QR / signature verification; ledger view."""
from contextlib import closing

import pandas as pd
import streamlit as st

from src import i18n, registry_crypto as rc, vdb, vstate
from src.log import logger
from src.ui_safety import safety_card
from src.verification_engine import DEFAULT_SETTINGS, run_verification
from src.ui_auth import current_user
from src.vcommon import badge, connect, parcel_picker, results_table

MAX_UPLOAD = 5 * 1024 * 1024
ALLOWED = (".txt", ".pdf", ".png", ".jpg", ".jpeg")
GROUPS = [("g.records", ["record_consistency", "registration_mutation", "survey_chain", "boundary_overlap"]), ("g.transfers", ["conflicting_sales"]),
          ("g.integrity", ["document_integrity", "document_authenticity"]), ("g.flags", ["pending_cases", "khas_acquisition", "encumbrance"])]


def current_settings() -> dict:
    """The settings currently chosen in this page (defaults if it has not been opened). Used to detect outdated runs."""
    ss = st.session_state
    return {**DEFAULT_SETTINGS, "area_tolerance_pct": float(ss.get("vw_tol", DEFAULT_SETTINGS["area_tolerance_pct"])),
            "overlap_days": int(ss.get("vw_days", DEFAULT_SETTINGS["overlap_days"])), "rapid_days": int(ss.get("vw_rapid", DEFAULT_SETTINGS["rapid_days"])),
            "mutation_deadline_days": int(ss.get("vw_mut", DEFAULT_SETTINGS["mutation_deadline_days"])),
            "survey_area_drift_pct": float(ss.get("vw_drift", DEFAULT_SETTINGS["survey_area_drift_pct"])),
            "overlap_tolerance_pct": float(ss.get("vw_ovl", DEFAULT_SETTINGS["overlap_tolerance_pct"])),
            "required_record_types": list(ss.get("vw_req", DEFAULT_SETTINGS["required_record_types"]))}


def _card(r):
    with st.container(border=True):
        st.markdown(f"**{i18n.check_title(r['check_id'], r['title'])}** &nbsp; {badge(r['status'])}")
        st.write(r["summary"])
        st.info(f"**{i18n.t('means')}:** " + r["meaning"])
        if r["evidence"]:
            st.dataframe(results_table(r["evidence"]), hide_index=True, width="stretch")
        with st.expander(i18n.t("limits")):
            for l in r["limitations"]:
                st.write("- " + l)
        st.caption(f"check_id: {r['check_id']} · {r['timestamp']}")


def _show_run(run, stale):
    if stale:
        st.warning("The settings or uploaded files changed since this run. The results below are **outdated**: press **Run verification** again.")
    safety_card(run)
    st.markdown(f"### {i18n.t('overall')}: {badge(run['overall_status'])}")
    st.write(i18n.overall_text(run["overall_status"]))
    by_id = {r["check_id"]: r for r in run["results"]}
    st.caption(f"Run at {run['created_at']} · engine {run['engine_version']} · parcel {run['parcel_id']} · synthetic data · {len(run['results'])} checks")
    counts = {}
    for r in run["results"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    st.write(" · ".join(f"{badge(k)} × {v}" for k, v in counts.items()))
    for gkey, ids in GROUPS:
        shown = [by_id[i] for i in ids if i in by_id]
        if shown:
            st.markdown(f"#### {i18n.t(gkey)}")
            for r in shown:
                _card(r)


def _qr_section(pid, docs, ctx):
    keys = ctx["issuer_keys"]
    signed = [d for d in docs if d.get("signature") and d.get("expected_sha256")]
    with st.expander("🔐 QR codes and offline verification (tamper-proof documents)"):
        st.caption("Each registered document carries a QR code holding its SHA-256 and an Ed25519 signature from the SIMULATED issuer. Anyone can scan the code and "
                   "compare it with the paper or file they were given, without access to the registry.")
        if not signed:
            st.info("This parcel has no signed documents.")
        for d in signed:
            payload = rc.build_payload(d["document_id"], pid, d["expected_sha256"], d["signer_kid"], d["signature"])
            c1, c2 = st.columns([1, 3])
            png = rc.make_qr_png(payload)
            c1.image(png, width=130)
            c2.markdown(f"**{d['document_id']}** · signer `{d['signer_kid']}`")
            c2.code(payload, language=None)
            c2.download_button("⬇️ QR code (PNG)", png, file_name=f"{d['document_id']}-qr.png", key=f"qrdl_{d['document_id']}")
        st.markdown("**Verify a QR code against a file**")
        a, b = st.columns(2)
        qrf = a.file_uploader("QR code image", type=["png", "jpg", "jpeg"], key=f"qr_img_{pid}")
        docf = b.file_uploader("Document file", type=[e.strip(".") for e in ALLOWED], key=f"qr_doc_{pid}")
        if qrf is not None and docf is not None and st.button("Verify QR + file", key="qr_go"):
            if len(docf.getvalue()) > MAX_UPLOAD:
                st.error("The document is larger than 5 MB.")
            else:
                text = rc.decode_qr(qrf.getvalue())
                if not text:
                    st.error("No QR code could be read from that image.")
                else:
                    res = rc.verify_qr_against_file(text, docf.getvalue(), keys)
                    (st.success if res["ok"] else st.error)(res["reason"])
                    if res.get("parcel_id") and res["parcel_id"] != pid:
                        st.warning(f"This QR code belongs to parcel {res['parcel_id']}, not the selected parcel {pid}.")
                    if "computed_sha256" in res:
                        st.caption(f"File SHA-256 {res['computed_sha256'][:16]}... · QR SHA-256 {res['qr_sha256'][:16]}... · signature valid: {res['signature_valid']}")


def _ledger_section(ctx):
    entries = ctx["ledger"]
    with st.expander("⛓️ Registry ledger for this parcel (hash chain)"):
        if not entries:
            st.info("No ledger entries for this parcel.")
            return
        chain = rc.verify_chain(entries)
        (st.success if chain["ok"] else st.error)(("Chain intact: " if chain["ok"] else "CHAIN BROKEN: ") + chain["reason"] + f" ({chain['checked']} entries checked)")
        st.dataframe(pd.DataFrame([{"Entry": e["entry_index"], "Document": e["doc_id"], "SHA-256": e["sha256"][:14] + "...", "Signer": e["signer_kid"],
                                    "Previous hash": e["prev_hash"][:10] + "...", "Entry hash": e["entry_hash"][:10] + "..."} for e in entries]), hide_index=True, width="stretch")
        st.caption("Each entry's hash covers the previous entry's hash, so editing, removing, inserting or reordering any entry breaks every later link. "
                   "A real registry would also anchor the latest hash outside its own system.")


def render():
    st.header("✅ " + i18n.t("nav.verify"))
    st.caption(i18n.t("synthetic"))
    p = parcel_picker("vw_pick")
    if not p:
        return
    pid = p["parcel_id"]
    if not p["is_synthetic"]:
        st.info("Verification needs records and registers. Only the synthetic demo parcels have them in this prototype; this parcel is a "
                f"{p['boundary_type'].replace('_', ' ')}. Choose a demo parcel above.")
        return
    st.subheader(p["scenario_title"])
    st.write(p["scenario_description"])
    with closing(connect()) as con:
        records, txs, docs, ctx = vdb.get_records(con, pid), vdb.get_transactions(con, pid), vdb.get_documents(con, pid), vdb.verification_context(con, pid)
    a, b, c, d = st.columns(4)
    a.metric("Records", len([r for r in records if not r.get("survey_gen")])); b.metric("Survey generations", len([r for r in records if r.get("survey_gen")]))
    c.metric("Transactions", len(txs)); d.metric("Documents", len(docs))

    with st.expander(i18n.t("settings"), expanded=False):
        s1, s2, s3 = st.columns(3)
        s1.slider("Area tolerance (%)", 0.0, 10.0, DEFAULT_SETTINGS["area_tolerance_pct"], 0.5, key="vw_tol", help="Recorded areas differing by more than this (or 1 m²) are a conflict.")
        s2.number_input("Overlapping-claim window (days)", 1, 365, DEFAULT_SETTINGS["overlap_days"], key="vw_days")
        s3.number_input("Rapid-transfer window (days)", 1, 365, DEFAULT_SETTINGS["rapid_days"], key="vw_rapid")
        s4, s5, s6 = st.columns(3)
        s4.number_input("Mutation deadline (days, illustrative)", 1, 730, DEFAULT_SETTINGS["mutation_deadline_days"], key="vw_mut")
        s5.slider("Survey area drift to review (%)", 1.0, 50.0, DEFAULT_SETTINGS["survey_area_drift_pct"], 1.0, key="vw_drift")
        s6.slider("Boundary overlap ignored below (% of smaller parcel)", 0.0, 10.0, DEFAULT_SETTINGS["overlap_tolerance_pct"], 0.5, key="vw_ovl",
                  help="Tiny overlaps are usually drawing noise. Above this, the overlap is reported as a conflict.")
        st.multiselect("Record types that must be present", ["deed", "khatian", "mutation", "survey reference"], default=DEFAULT_SETTINGS["required_record_types"], key="vw_req")
    settings = current_settings()

    uploads = st.session_state.setdefault("vp_uploads", {})
    if docs:
        with st.expander("Document integrity: test a file against the stored hash and signature (optional)"):
            st.caption("Download a fixture, edit it, and upload it to see the hash and signature checks fail. Uploaded files are hashed in memory and are not saved.")
            for dd in docs:
                if dd["content"] is not None:
                    st.download_button(f"⬇️ {dd['filename']}", dd["content"], file_name=dd["filename"], key=f"dl_{dd['document_id']}")
            target = st.selectbox("Replace which document?", [dd["document_id"] for dd in docs], key="vw_updoc")
            f = st.file_uploader("File", type=[e.strip(".") for e in ALLOWED], key=f"vw_file_{pid}")
            if f is not None:
                data = f.getvalue()
                if len(data) > MAX_UPLOAD:
                    st.error(f"The file is {len(data) / 1e6:.1f} MB; the limit is 5 MB.")
                elif not f.name.lower().endswith(ALLOWED):
                    st.error("Only .txt, .pdf, .png, .jpg files are accepted.")
                elif st.button("Use this file for the check", key="vw_useup"):
                    uploads[target] = data
                    st.success(f"Using the uploaded file for {target} (not stored).")
            if uploads:
                st.write("Uploaded for: " + ", ".join(sorted(uploads)))
                if st.button("Remove uploaded files", key="vw_clearup"):
                    uploads.clear()
    _qr_section(pid, docs, ctx)
    _ledger_section(ctx)

    if st.button(i18n.t("run"), type="primary", key="vw_run"):
        try:
            with st.spinner("Running checks..."):
                run = run_verification(pid, records, txs, docs, settings, uploaded=dict(uploads), context=ctx)
                with closing(connect()) as con:
                    run_id = vdb.save_run(con, pid, run, user=current_user())
                vstate.store_run(st.session_state, run, run_id)
            logger.info("verification run %s parcel=%s overall=%s", run_id, pid, run["overall_status"])
        except Exception as exc:
            logger.exception("verification failed parcel=%s", pid)
            st.error(f"The verification could not be completed ({type(exc).__name__}). Please try again; the error was logged.")
    run = vstate.current_run(st.session_state)
    if run:
        _show_run(run, vstate.run_is_stale(run, settings, list(uploads)))
        st.caption(f"Saved as {st.session_state.get('vp_run_id')} in the local synthetic database.")
    else:
        st.info(i18n.t("no_run"))
    with st.expander("Run history for this parcel (saved, never overwritten; citizens see only their own runs)"):
        with closing(connect()) as con:
            me = current_user() or {}
            hist = vdb.list_runs(con, pid, user_id=None if me.get("role") == "admin" else me.get("user_id", -1))
        st.dataframe(hist, hide_index=True, width="stretch") if hist else st.write("No saved runs.")
    st.caption(i18n.t("disclaimer"))
