"""JomiLens Verify: citizen pre-purchase land verification for Joydebpur, Gazipur (prototype).
Signed out: overview + two separate doors (Citizen Login, Admin Portal). Citizens and administrators see different menus."""
import streamlit as st

st.set_page_config(page_title="JomiLens Verify", page_icon="🛰️", layout="wide")

from src import i18n
from src.nav import PAGES
from src.style import inject_css
from src.ui_auth import current_user, sidebar_badge

inject_css()
st.sidebar.radio("Language / ভাষা", list(i18n.LANGS), format_func=lambda k: i18n.LANGS[k], key="lang", horizontal=True)
t = i18n.t


def lazy(module, fn="render"):
    """Pages import lazily, so only the page you open is loaded (faster start)."""
    def run():
        import importlib
        getattr(importlib.import_module(f"src.{module}"), fn)()
    run.__name__ = f"{module}_{fn}"
    return run


def page(key, module, title, icon, url, fn="render", default=False):
    PAGES[key] = st.Page(lazy(module, fn), title=title, icon=icon, url_path=url, default=default)
    return PAGES[key]


def _nav(pages):
    return st.navigation(pages, expanded=True)


PAGES.clear()             # rebuilt every run: a signed-out visitor must never get links to signed-in pages
user = current_user()
if user is None:
    nav = _nav({"JomiLens Verify": [page("v_overview", "ui_verify_overview", t("nav.overview"), "🏠", "overview", default=True)],
                         t("nav.signin"): [page("login_citizen", "ui_auth", t("nav.citizen_login"), "🙂", "citizen-login", "citizen_login"),
                                           page("login_admin", "ui_auth", t("nav.admin_login"), "🛡️", "admin-portal", "admin_login")]})
elif user.get("must_change_password"):
    sidebar_badge(user)
    nav = _nav([page("account", "ui_auth", t("nav.account"), "👤", "account", "account_page", default=True)])
else:
    sidebar_badge(user)
    verify = [page("v_explore", "ui_landmap", t("nav.explore"), "🧭", "explore-joydebpur"),
              page("v_search", "ui_search", t("nav.search"), "🔎", "search"),
              page("v_profile", "ui_parcel", t("nav.profile"), "📍", "parcel-profile"),
              page("v_verify", "ui_verify", t("nav.verify"), "✅", "verification"),
              page("v_satellite", "ui_satellite_verify", t("nav.satellite"), "🛰️", "satellite"),
              page("v_report", "ui_verify_report", t("nav.report"), "📄", "report")]
    if user["role"] == "admin":
        admin = [page("a_dash", "ui_admin", t("nav.a_dash"), "🛡️", "admin", "dashboard", default=True),
                 page("a_support", "ui_admin", t("nav.a_support"), "📨", "admin-reports", "support_page"),
                 page("a_gis", "ui_admin_gis", t("nav.a_gis"), "🗺️", "admin-gis", "editor"),
                 page("a_users", "ui_admin", t("nav.a_users"), "👥", "admin-users", "users_page"),
                 page("a_notify", "ui_admin", t("nav.a_notify"), "📢", "admin-notify", "notify_page"),
                 page("a_audit", "ui_admin", t("nav.a_audit"), "📜", "admin-audit", "audit_page")]
        nav = _nav({t("nav.admin"): admin, t("nav.group"): [page("v_overview", "ui_verify_overview", t("nav.overview"), "🏠", "overview")] + verify,
                             t("nav.me"): [page("myplot", "ui_myplot", t("nav.myplot"), "📐", "draw-a-plot"),
                                           page("account", "ui_auth", t("nav.account"), "👤", "account", "account_page")]})
    else:
        mine = [page("inbox", "ui_inbox", t("nav.inbox"), "📬", "inbox"),
                page("myplot", "ui_myplot", t("nav.myplot"), "📐", "draw-a-plot"),
                page("account", "ui_auth", t("nav.account"), "👤", "account", "account_page")]
        nav = _nav({t("nav.group"): [page("v_overview", "ui_verify_overview", t("nav.overview"), "🏠", "overview", default=True)] + verify,
                             t("nav.me"): mine})
st.sidebar.caption(t("disclaimer"))
nav.run()
