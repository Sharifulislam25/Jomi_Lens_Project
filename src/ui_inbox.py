"""Citizen inbox: notifications from the land office, my problem reports, my conversation with support, and a form to report a problem."""
from contextlib import closing

import streamlit as st

from src import support, vstate
from src.nav import PAGES
from src.ui_auth import current_user
from src.vcommon import connect, demo_parcels

LEVEL_ICON = {"info": "ℹ️", "warning": "⚠️", "important": "❗"}
STATUS_ICON = {"open": "🟡 open", "in_review": "🔵 in review", "resolved": "🟢 resolved", "rejected": "⚪ rejected"}


def _chat(rows, me_role):
    for m in rows:
        who = "user" if m["sender_role"] == "user" else "assistant"
        with st.chat_message(who, avatar="🙂" if who == "user" else "🛡️"):
            label = "You" if m["sender_role"] == me_role else ("Support team" if m["sender_role"] == "admin" else m["sender_name"])
            st.caption(f"{label} · {m['created_at'].replace('T', ' ')[:16]} UTC" + (f" · {m['report_id']}" if m["report_id"] else ""))
            st.text(m["body"])


def report_form(user, default_parcel=None, key="rp"):
    parcels = demo_parcels()
    ids = ["(no specific parcel)"] + [p["parcel_id"] for p in parcels]
    labels = {p["parcel_id"]: f"{p['parcel_id']} · {p['scenario_title']} · {p.get('mouza') or ''}" for p in parcels}
    with st.form(f"{key}_form", clear_on_submit=True):
        pid = st.selectbox("Which land?", ids, index=ids.index(default_parcel) if default_parcel in ids else 0,
                           format_func=lambda k: labels.get(k, k), key=f"{key}_pid")
        cat = st.selectbox("What is wrong?", list(support.REPORT_CATEGORIES), format_func=support.REPORT_CATEGORIES.get, key=f"{key}_cat")
        desc = st.text_area("Describe the problem (10+ characters)", key=f"{key}_desc", max_chars=support.MAX_TEXT,
                            placeholder="Example: the map shows the north boundary about 5 m inside the neighbour's wall; my deed says 8.25 decimal, the map says 7.9.")
        st.caption("Do not write names, phone numbers, NID numbers or addresses. The support team answers in your Inbox.")
        if st.form_submit_button("📨 Send report", type="primary"):
            p = next((x for x in parcels if x["parcel_id"] == pid), None)
            lat = lon = None
            if p:
                lon = sum(q[0] for q in p["points"]) / len(p["points"])
                lat = sum(q[1] for q in p["points"]) / len(p["points"])
            with closing(connect()) as con:
                try:
                    rid = support.create_report(con, user, cat, desc, parcel_id=p["parcel_id"] if p else None, lat=lat, lon=lon)
                    st.success(f"Report {rid} sent. You will get an answer in your Inbox.")
                except support.SupportError as e:
                    st.error(str(e))


def render():
    user = current_user()
    st.header("📬 Inbox")
    with closing(connect()) as con:
        notes = support.notifications_for(con, user["user_id"])
        reports = support.list_reports(con, user_id=user["user_id"])
        n_unread = support.unread_messages(con, user)
    new_notes = sum(1 for n in notes if not n["is_read"])
    tabs = st.tabs([f"🔔 Notifications ({new_notes} new)", f"💬 Messages{f' ({n_unread} new)' if n_unread else ''}",
                    f"📋 My reports ({len(reports)})", "🚩 Report a problem"])
    with tabs[0]:
        if not notes:
            st.info("No notifications yet.")
        for n in notes:
            with st.container(border=True):
                st.markdown(f"{LEVEL_ICON[n['level']]} **{n['title']}**" + ("  🆕" if not n["is_read"] else "")
                            + f"  \n<small>{'Everyone' if n['recipient_id'] is None else 'Only you'} · from {n['sender']} · {n['created_at'][:16].replace('T', ' ')} UTC</small>",
                            unsafe_allow_html=True)
                st.text(n["body"])
        if new_notes and st.button("Mark all as read"):
            with closing(connect()) as con:
                support.mark_notifications_read(con, user["user_id"])
            st.rerun()
    with tabs[1]:
        st.caption("Your private conversation with the land-office support team (demo). Problem reports and status changes also appear here.")
        with closing(connect()) as con:
            rows = support.thread(con, user["user_id"], reader_role="user")
        if not rows:
            st.info("No messages yet. Write to the support team below.")
        _chat(rows, "user")
        msg = st.chat_input("Write to the support team")
        if msg:
            with closing(connect()) as con:
                try:
                    support.send_message(con, user, user["user_id"], msg)
                    st.rerun()
                except support.SupportError as e:
                    st.error(str(e))
    with tabs[2]:
        if not reports:
            st.info("You have not reported a problem yet.")
        for r in reports:
            with st.container(border=True):
                st.markdown(f"**{r['report_id']}** · {STATUS_ICON[r['status']]} · {support.REPORT_CATEGORIES[r['category']]}"
                            f"{' · parcel ' + r['parcel_id'] if r['parcel_id'] else ''}  \n<small>sent {r['created_at'][:16].replace('T', ' ')} UTC · "
                            f"updated {r['updated_at'][:16].replace('T', ' ')} UTC</small>", unsafe_allow_html=True)
                st.text(r["description"])
    with tabs[3]:
        report_form(user, default_parcel=vstate.current_key(st.session_state))
        if "v_explore" in PAGES:
            st.page_link(PAGES["v_explore"], label="Find the land on the map first", icon="🧭")
