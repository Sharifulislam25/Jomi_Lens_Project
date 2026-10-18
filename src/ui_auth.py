"""Sign-in pages (Citizen Login and Admin Portal are separate), account page and the session helpers used by app.py."""
from contextlib import closing

import streamlit as st

from src import accounts, support
from src.accounts import AuthError
from src.vcommon import connect

KEY = "auth"


def current_user():
    """The signed-in user (dict) or None. Expired sessions and accounts disabled since sign-in are signed out here."""
    a = st.session_state.get(KEY)
    if not a:
        return None
    if accounts.session_expired(a):
        st.session_state.pop(KEY, None)
        st.session_state["auth_msg"] = "Your session expired. Please sign in again."
        return None
    with closing(connect()) as con:
        u = accounts.get_user_by_id(con, a["user_id"])
    if not u or not u["active"] or u["role"] != a["role"]:
        st.session_state.pop(KEY, None)
        st.session_state["auth_msg"] = "Your account is not active any more. Contact the administrator."
        return None
    a["must_change_password"] = bool(u["must_change_password"])
    return a


def sign_out():
    keep = {k: st.session_state[k] for k in ("lang",) if k in st.session_state}
    st.session_state.clear()
    st.session_state.update(keep)


def _do_login(username, password, door):
    with closing(connect()) as con:
        try:
            u = accounts.authenticate(con, username, password, door)
        except AuthError as e:
            st.error(str(e))
            return
    keep = {k: st.session_state[k] for k in ("lang",) if k in st.session_state}
    st.session_state.clear()                       # a new sign-in never inherits the previous person's selections
    st.session_state.update(keep)
    st.session_state[KEY] = accounts.new_session(u)
    st.rerun()


def _demo_box(text):
    st.markdown(f'<div class="note">{text}</div>', unsafe_allow_html=True)


def citizen_login():
    if msg := st.session_state.pop("auth_msg", None):
        st.warning(msg)
    st.markdown('<div class="hero door-citizen"><h1>Citizen Login</h1><div class="tag">নাগরিক লগইন · check a land in Joydebpur before you buy</div>'
                '<span class="pill">For buyers and land owners</span><span class="pill">No phone, NID or e-mail needed</span></div>', unsafe_allow_html=True)
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("Sign in")
        with st.form("cit_login"):
            u = st.text_input("Username", key="cl_user", autocomplete="username")
            p = st.text_input("Password", type="password", key="cl_pw", autocomplete="current-password")
            if st.form_submit_button("Sign in as citizen", type="primary", use_container_width=True):
                _do_login(u, p, "citizen")
        _demo_box("Demo citizen: <b>citizen</b> / <b>JomiCitizen#2026</b>. Administrators use the separate <b>Admin Portal</b> page.")
    with right:
        st.subheader("Create an account")
        st.caption("Choose a nickname as username. Do not use your real name, phone number, NID or e-mail: this prototype must not hold personal data.")
        with st.form("cit_register"):
            u = st.text_input("Username (nickname)", key="cr_user", help="3-30 characters: letters, digits, dot, dash, underscore; start with a letter.")
            p1 = st.text_input("Password (8+ characters)", type="password", key="cr_pw1", autocomplete="new-password")
            p2 = st.text_input("Repeat password", type="password", key="cr_pw2", autocomplete="new-password")
            ok = st.checkbox("I understand this is a prototype with synthetic data. It does not prove ownership or title.", key="cr_ok")
            if st.form_submit_button("Create account", use_container_width=True):
                if p1 != p2:
                    st.error("The two passwords are different.")
                elif not ok:
                    st.error("Please tick the box first.")
                else:
                    with closing(connect()) as con:
                        try:
                            accounts.create_user(con, u, p1)
                        except AuthError as e:
                            st.error(str(e))
                            return
                    _do_login(u, p1, "citizen")


def admin_login():
    if msg := st.session_state.pop("auth_msg", None):
        st.warning(msg)
    st.markdown('<div class="hero door-admin"><h1>Admin Portal</h1><div class="tag">প্রশাসক পোর্টাল · land-office demo staff only</div>'
                '<span class="pill">Separate sign-in</span><span class="pill">Sessions end after 2 hours</span><span class="pill">Every action is audit-logged</span></div>',
                unsafe_allow_html=True)
    c = st.columns([1, 1.4, 1])[1]
    with c:
        with st.form("adm_login"):
            u = st.text_input("Admin username", key="al_user", autocomplete="username")
            p = st.text_input("Password", type="password", key="al_pw", autocomplete="current-password")
            if st.form_submit_button("Sign in to Admin Portal", type="primary", use_container_width=True):
                _do_login(u, p, "admin")
        st.caption("Admin accounts cannot be self-registered. They are created by another administrator. "
                   "After 5 wrong passwords the username is locked for 15 minutes.")
        _demo_box("Demo admin: <b>admin</b> / <b>JomiAdmin#2026</b> (set JOMILENS_ADMIN_PASSWORD before the first run to choose your own).")


def account_page():
    user = current_user()
    st.header("👤 My account")
    st.write(f"Signed in as **{user['username']}** ({'Administrator' if user['role'] == 'admin' else 'Citizen'}) since {user['login_at']} UTC. "
             f"Sessions last {accounts.SESSION_HOURS[user['role']]} hours.")
    if user.get("must_change_password"):
        st.warning("An administrator reset your password. Please choose a new one now.")
    with st.form("chpw"):
        st.subheader("Change password")
        cur = st.text_input("Current password", type="password")
        n1 = st.text_input("New password", type="password")
        n2 = st.text_input("Repeat new password", type="password")
        if st.form_submit_button("Change password"):
            if n1 != n2:
                st.error("The two new passwords are different.")
            else:
                with closing(connect()) as con:
                    try:
                        accounts.change_password(con, user["user_id"], cur, n1)
                        st.success("Password changed.")
                    except AuthError as e:
                        st.error(str(e))
    if st.button("🚪 Sign out", type="primary"):
        sign_out()
        st.rerun()


def sidebar_badge(user):
    with closing(connect()) as con:
        n_msg = support.unread_messages(con, user)
        n_note = support.unread_notifications(con, user["user_id"]) if user["role"] == "user" else 0
    role = "🛡️ Admin" if user["role"] == "admin" else "🙂 Citizen"
    st.sidebar.markdown(f"**{role}: {user['username']}**")
    bits = []
    if n_note:
        bits.append(f"🔔 {n_note} new notification{'s' if n_note != 1 else ''}")
    if n_msg:
        bits.append(f"✉️ {n_msg} unread message{'s' if n_msg != 1 else ''}")
    if bits:
        st.sidebar.info(" · ".join(bits))
    if st.sidebar.button("Sign out", key="sb_signout", use_container_width=True):
        sign_out()
        st.rerun()
