"""Overview of JomiLens Verify (Joydebpur, Gazipur). Also the landing page for signed-out visitors."""
from contextlib import closing

import streamlit as st

from src import i18n, landmap, vdb
from src.nav import PAGES
from src.vcommon import connect


def render():
    t = i18n.t
    st.markdown(f"""<div class="hero"><h1>JomiLens Verify</h1><div class="tag">{t('tagline')}</div>
<p>{'Find a plot on the Joydebpur map, review its (fictional) records, run ten transparent checks, see how the land looked in open satellite imagery, and get a PDF that says exactly what was checked and what could not be.' if i18n.lang() == 'en' else 'জয়দেবপুরের মানচিত্রে একটি জমি খুঁজুন, এর (কাল্পনিক) রেকর্ড পর্যালোচনা করুন, দশটি স্বচ্ছ যাচাই চালান, উন্মুক্ত স্যাটেলাইট চিত্রে জমির ইতিহাস দেখুন, এবং কী যাচাই হয়েছে ও কী হয়নি তা স্পষ্ট করে বলা একটি PDF পান।'}</p>
<span class="pill">LandTech 2026 · P5 Citizen Pre-Purchase Verification</span><span class="pill">Joydebpur · Gazipur Sadar · Gazipur</span><span class="pill">{'Synthetic demo data' if i18n.lang() == 'en' else 'কৃত্রিম ডেমো তথ্য'}</span></div>""", unsafe_allow_html=True)
    if "login_citizen" in PAGES:
        a, b = st.columns(2)
        a.page_link(PAGES["login_citizen"], label="**Citizen Login** · create a free account with a nickname", icon="🙂")
        b.page_link(PAGES["login_admin"], label="**Admin Portal** · separate sign-in for staff", icon="🛡️")
    st.error(t("disclaimer"))
    st.caption(t("synthetic"))
    with closing(connect()) as con:
        c = vdb.counts(con)
    m = st.columns(4)
    m[0].metric(t("parcels"), c["parcels"]); m[1].metric(t("records_n"), c["records"]); m[2].metric(t("checks_n"), 10); m[3].metric(t("runs_n"), c["runs"])

    st.subheader("What P5 asks for, and where it is checked" if i18n.lang() == "en" else "P5 যা চায় এবং কোথায় যাচাই হয়")
    st.table({"P5 requirement": ["Ownership", "Mutation history", "Pending cases", "Khas or acquisition status", "(Track) double-selling and forged documents", "(Track) cryptographic validation",
                                 "(Buyer risk) mortgage or lien on the title"],
              "Checks in JomiLens Verify": ["Record consistency · Conflicting / duplicate sales (incl. rapid transfers) · holder match · Boundary overlap with other registered parcels",
                                            "Registration vs mutation · Survey chain CS → SA → RS → BS", "Pending cases (synthetic case register)", "Khas / vested / acquisition (synthetic register)",
                                            "Conflicting sales · Boundary overlap · Document integrity (SHA-256)", "Document authenticity: Ed25519 signature + hash-chained ledger + QR code",
                                            "Mortgage / lien / attachment (synthetic encumbrance register)"],
              "Result type": ["PASS / REVIEW / CONFLICT / UNAVAILABLE"] * 7})
    st.subheader(t("ov.workflow"))
    st.markdown("""
1. **Explore Joydebpur** or **Find a land** (smart search by dag, khatian, mouza, id or landmark): a real map; synthetic demo parcels are drawn differently from real mapped features, with a legend.
2. **Parcel profile**: geometry, calculated vs recorded area, boundary source, surveys, registers and data limits.
3. **Verification**: a traffic-light safety summary (with a Bangla voice button) above ten checks, each with status, evidence, limitations and a plain explanation; QR and signature verification.
4. **Satellite & land use**: open Sentinel-2 imagery (real capture dates, same season each year) with cautious change analysis.
5. **Report**: a PDF for the current parcel and current run, with mouza, the (fictional) asking price and a Google Maps link.
6. **Inbox**: report a problem with a land, message the support team, and read notifications from the land office.

Administrators sign in through the separate **Admin Portal**: they answer reports and messages, correct parcel coordinates in the GIS editor,
manage accounts and send notifications. Every admin action is written to an audit log.""")
    a, b = st.columns(2)
    a.markdown(f"**{t('ov.can')}**\n- compare synthetic records and flag disagreements\n- link registration and mutation, and walk the CS→SA→RS→BS survey chain\n- flag overlapping, repeated and rapid simulated sales\n- check hashes, issuer signatures and a tamper-evident ledger\n- show case, khas/acquisition and mortgage flags from synthetic registers\n- detect a boundary that overlaps another registered parcel\n- show open satellite imagery and possible surface change")
    b.markdown(f"**{t('ov.cannot')}**\n- establish ownership, title or a legal boundary\n- prove a document is authentic (a signature here comes from a simulated issuer)\n- read real court, land-office or government records (none are used)\n- infer legal land use or illegal possession from images")
    st.subheader("Joydebpur coverage: three levels" if i18n.lang() == "en" else "জয়দেবপুরের কভারেজ: তিন স্তর")
    cnt = landmap.stats() if landmap.available() else {"building": 0}
    st.table({"Level": ["1. Geographic exploration", "2. Mapped land-use features", "3. Verification-ready demo parcels"],
              "What exists": ["Gazipur Sadar upazila outline (BBS/OCHA), the Joydebpur focus area, landmarks, place search, open and optional high-resolution imagery",
                              f"OpenStreetMap buildings ({cnt['building']:,}), land use, water, parks and campuses in the Joydebpur focus area",
                              "25 synthetic parcels in five fictional mouzas, with fictional records, asking prices, surveys, cases, notices, mortgages, signed documents and a ledger"],
              "What it is NOT": ["Not a cadastral map", "Not parcels: a building footprint is not a plot boundary; open land is often unmapped", "Not real land records"]})
    if "v_explore" in PAGES:
        st.page_link(PAGES["v_explore"], label=t("ov.start"), icon="🧭")
    elif "login_citizen" in PAGES:
        a, b = st.columns(2)
        a.page_link(PAGES["login_citizen"], label="Citizen Login: check a land before you buy", icon="🙂")
        b.page_link(PAGES["login_admin"], label="Admin Portal: land-office staff (demo)", icon="🛡️")
