"""Admin Portal pages: dashboard, users, problem reports & messages, notifications, audit log."""
import json
from contextlib import closing

import pandas as pd
import streamlit as st

from src import accounts, support, vdb
from src.accounts import AuthError
from src.exporting import to_csv
from src.nav import PAGES
from src.ui_auth import current_user
from src.ui_inbox import STATUS_ICON, _chat
from src.vcommon import connect


def _admin():
    u = current_user()
    if not u or u["role"] != "admin":
        st.error("Administrators only.")
        st.stop()
    return u


# ---------------------------------------------------------------- dashboard
def dashboard():
    _admin()
    st.header("🛡️ Admin dashboard")
    with closing(connect()) as con:
        c = vdb.counts(con)
        users = accounts.list_users(con)
        reports = support.list_reports(con)
        runs = vdb.all_runs(con)
        audit = [dict(r) for r in con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 5000")]
        n_unread = con.execute("SELECT COUNT(*) FROM messages WHERE read_by_admin = 0").fetchone()[0]
    open_r = sum(1 for r in reports if r["status"] in ("open", "in_review"))
    m = st.columns(5)
    m[0].metric("Active parcels", c["parcels"])
    m[1].metric("Citizen accounts", sum(1 for u in users if u["role"] == "user"))
    m[2].metric("Open reports", open_r)
    m[3].metric("Unread messages", n_unread)
    m[4].metric("Verification runs", c["runs"])
    a, b = st.columns(2)
    with a:
        st.subheader("Verification results")
        if runs:
            st.bar_chart(pd.Series([r["overall_status"] for r in runs]).value_counts())
        else:
            st.caption("No runs yet.")
    with b:
        st.subheader("Problem reports by status")
        if reports:
            st.bar_chart(pd.Series([r["status"] for r in reports]).value_counts())
        else:
            st.caption("No reports yet.")
    st.subheader("Quick links")
    q = st.columns(5)
    for col, key, label, icon in zip(q, ["a_support", "a_gis", "a_users", "a_notify", "a_audit"],
                                     ["Reports & messages", "GIS coordinate editor", "Users", "Send notification", "Audit log"], ["📨", "🗺️", "👥", "📢", "📜"]):
        if key in PAGES:
            col.page_link(PAGES[key], label=label, icon=icon)
    st.subheader("Exports (CSV, safe to open in Excel)")
    e = st.columns(3)
    e[0].download_button("Audit log", to_csv(audit), "jomilens_audit_log.csv", "text/csv", use_container_width=True)
    e[1].download_button("Verification runs", to_csv(runs), "jomilens_runs.csv", "text/csv", use_container_width=True)
    e[2].download_button("Problem reports", to_csv(reports), "jomilens_reports.csv", "text/csv", use_container_width=True)


# ---------------------------------------------------------------- users
def users_page():
    admin = _admin()
    st.header("👥 User management")
    with closing(connect()) as con:
        users = accounts.list_users(con)
    df = pd.DataFrame(users)
    df["active"] = df["active"].map({1: "✅ active", 0: "⛔ disabled"})
    st.dataframe(df[["user_id", "username", "role", "display_name", "active", "created_at", "created_by", "last_login_at"]], hide_index=True, use_container_width=True)
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Change an account")
        by_name = {u["username"]: u for u in users}
        name = st.selectbox("Account", list(by_name), key="um_pick")
        u = by_name[name]
        c1, c2 = st.columns(2)
        if u["active"]:
            if c1.button("⛔ Disable", key="um_dis", use_container_width=True, disabled=u["user_id"] == admin["user_id"]):
                _apply(lambda con: accounts.set_active(con, admin, u["user_id"], False), f"{name} disabled. They are signed out on their next click.")
        elif c1.button("✅ Enable", key="um_en", use_container_width=True):
            _apply(lambda con: accounts.set_active(con, admin, u["user_id"], True), f"{name} enabled.")
        if c2.button("🔑 Reset password", key="um_reset", use_container_width=True, disabled=u["user_id"] == admin["user_id"]):
            with closing(connect()) as con:
                temp = accounts.reset_password(con, admin, u["user_id"])
            st.success(f"Temporary password for **{name}** (shown once, give it to them in person): `{temp}`. They must change it after signing in.")
        if u["user_id"] == admin["user_id"]:
            st.caption("You cannot disable or reset your own account here; use My account to change your password.")
    with right:
        st.subheader("Create an account")
        with st.form("um_new", clear_on_submit=True):
            n = st.text_input("Username (nickname, no personal data)")
            r = st.selectbox("Role", ["user", "admin"], format_func=lambda k: "Citizen" if k == "user" else "Administrator")
            p = st.text_input("Initial password (10+ characters)", type="password")
            if st.form_submit_button("Create", type="primary"):
                with closing(connect()) as con:
                    try:
                        accounts.create_user(con, n, p, role=r, created_by=admin["username"])
                        con.execute("UPDATE users SET must_change_password = 1 WHERE username = ?", (accounts.clean_username(n),))
                        con.commit()
                        st.success("Account created. The person must change the password at first sign-in.")
                    except AuthError as e:
                        st.error(str(e))


def _apply(fn, ok):
    with closing(connect()) as con:
        try:
            fn(con)
            st.success(ok)
            st.rerun()
        except AuthError as e:
            st.error(str(e))


# ---------------------------------------------------------------- reports & messages
def support_page():
    admin = _admin()
    st.header("📨 Problem reports & messages")
    t1, t2 = st.tabs(["📋 Problem reports", "💬 Conversations"])
    with t1:
        status = st.segmented_control("Status", ["all", *support.REPORT_STATUSES], default="open", key="sp_status") or "all"
        with closing(connect()) as con:
            reports = support.list_reports(con, status=None if status == "all" else status)
        if not reports:
            st.info("No reports with this status.")
        for r in reports:
            with st.expander(f"{r['report_id']} · {STATUS_ICON[r['status']]} · {support.REPORT_CATEGORIES[r['category']]} · by {r['username']}"
                             + (f" · {r['parcel_id']}" if r["parcel_id"] else "")):
                st.text(r["description"])
                st.caption(f"Sent {r['created_at']} · updated {r['updated_at']}" + (f" · location {r['lat']:.5f}, {r['lon']:.5f}" if r["lat"] is not None else ""))
                with st.form(f"sp_f_{r['report_id']}"):
                    ns = st.selectbox("New status", support.REPORT_STATUSES, index=support.REPORT_STATUSES.index(r["status"]))
                    note = st.text_input("Note to the citizen (optional)")
                    if st.form_submit_button("Update and notify"):
                        with closing(connect()) as con:
                            try:
                                support.set_report_status(con, admin, r["report_id"], ns, note)
                                st.rerun()
                            except support.SupportError as e:
                                st.error(str(e))
                if r["parcel_id"] and "a_gis" in PAGES and st.button("Open this parcel in the GIS editor", key=f"sp_gis_{r['report_id']}"):
                    st.session_state["gis_pid"] = r["parcel_id"]
                    st.switch_page(PAGES["a_gis"])
    with t2:
        with closing(connect()) as con:
            threads = support.threads_for_admin(con)
        if not threads:
            st.info("No conversations yet.")
            return
        lab = {t["thread_user_id"]: f"{t['username']} · {t['n']} messages" + (f" · 🆕 {t['unread']} unread" if t["unread"] else "") for t in threads}
        who = st.selectbox("Citizen", list(lab), format_func=lab.get, key="sp_thread")
        with closing(connect()) as con:
            rows = support.thread(con, who, reader_role="admin")
        _chat(rows, "admin")
        msg = st.chat_input("Reply as the support team")
        if msg:
            with closing(connect()) as con:
                try:
                    support.send_message(con, admin, who, msg)
                    st.rerun()
                except support.SupportError as e:
                    st.error(str(e))


# ---------------------------------------------------------------- notifications
def notify_page():
    admin = _admin()
    st.header("📢 Send a notification")
    with closing(connect()) as con:
        citizens = [u for u in accounts.list_users(con) if u["role"] == "user" and u["active"]]
    with st.form("nt_form", clear_on_submit=True):
        to = st.radio("To", ["everyone", "one"], horizontal=True, format_func=lambda k: "Every user (system-wide)" if k == "everyone" else "One citizen")
        who = st.selectbox("Citizen (if 'One citizen')", [u["user_id"] for u in citizens], format_func=lambda i: next(u["username"] for u in citizens if u["user_id"] == i))
        level = st.selectbox("Level", support.LEVELS, format_func=lambda k: {"info": "ℹ️ Info", "warning": "⚠️ Warning", "important": "❗ Important"}[k])
        title = st.text_input("Title", max_chars=120)
        body = st.text_area("Message", max_chars=support.MAX_TEXT)
        if st.form_submit_button("Send", type="primary"):
            with closing(connect()) as con:
                try:
                    support.notify(con, admin, title, body, recipient_id=None if to == "everyone" else who, level=level)
                    st.success("Sent.")
                except support.SupportError as e:
                    st.error(str(e))
    st.subheader("Sent")
    with closing(connect()) as con:
        sent = support.sent_notifications(con)
    if sent:
        df = pd.DataFrame(sent)
        df["to"] = df["recipient"].fillna("everyone")
        st.dataframe(df[["created_at", "to", "level", "title", "body", "sender"]], hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- audit log
def audit_page():
    _admin()
    st.header("📜 Audit log")
    st.caption("Append-only record of sign-ins (successful, failed, locked), account changes, report and message actions, notifications and every parcel edit "
               "with the old and new outline. Passwords are never logged.")
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 5000")]
    if not rows:
        st.info("Empty.")
        return
    df = pd.DataFrame(rows)
    c = st.columns(3)
    actors = c[0].multiselect("Who", sorted(df["actor"].dropna().unique()))
    actions = c[1].multiselect("Action", sorted(df["action"].unique()))
    text = c[2].text_input("Target contains")
    if actors:
        df = df[df["actor"].isin(actors)]
    if actions:
        df = df[df["action"].isin(actions)]
    if text:
        df = df[df["target"].fillna("").str.contains(text, case=False, regex=False)]
    st.dataframe(df[["id", "ts", "actor", "role", "action", "target", "detail_json"]], hide_index=True, use_container_width=True, height=460)
    st.download_button("Download these rows (CSV)", to_csv(df.to_dict("records")), "jomilens_audit_filtered.csv", "text/csv")
    pick = st.selectbox("Show details of entry", df["id"].tolist()[:300])
    if pick is not None:
        st.json(json.loads(df[df["id"] == pick].iloc[0]["detail_json"] or "{}"))
