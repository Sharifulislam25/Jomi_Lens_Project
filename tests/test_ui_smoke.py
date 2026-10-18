import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src import vdb

HDR = "import sys; sys.path.insert(0,'.')\nimport streamlit as st\nfrom src.nav import PAGES\n"
PAGE = HDR + """
mode = st.session_state.get('mode', 'verify')
if mode == 'verify':
    from src.ui_verify import render
elif mode == 'report':
    from src.ui_verify_report import render
elif mode == 'profile':
    from src.ui_parcel import render
else:
    from src.ui_verify_overview import render
render()
"""


@pytest.fixture()
def app(seeded, monkeypatch):
    monkeypatch.setattr(vdb, "DB_PATH", seeded)
    st.cache_resource.clear()
    st.cache_data.clear()
    return lambda **state: _make(state)


def _make(state):
    at = AppTest.from_string(PAGE, default_timeout=60)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def run_button(at):
    return [b for b in at.button if b.key == "vw_run"][0]


def test_overview_and_profile_render_without_errors(app):
    assert not app(mode="overview").exception
    at = app(mode="profile")
    assert not at.exception and at.metric[0].value == "DV-001"


def test_verification_runs_and_changing_parcel_discards_the_old_result(app):
    at = app(mode="verify")
    at.selectbox(key="vw_pick").set_value("DV-008").run()
    run_button(at).click().run()
    assert not at.exception and at.session_state["vp_run"]["overall_status"] == "CONFLICT_FOUND"
    assert any("Overall" in m.value for m in at.markdown)
    at.selectbox(key="vw_pick").set_value("DV-001").run()
    assert at.session_state["vp_run"] is None if "vp_run" in at.session_state else True
    assert any("No run yet" in i.value for i in at.info)                           # no stale DV-008 result shown for DV-001


def test_report_page_requires_the_current_run_and_then_builds(app, tmp_path, monkeypatch):
    from src import report_generator as rg
    monkeypatch.setattr(rg, "REPORT_DIR", tmp_path)
    at = app(mode="verify")
    at.selectbox(key="vw_pick").set_value("DV-003").run()
    at.session_state["mode"] = "report"; at.run()
    assert any("Run the verification" in w.value for w in at.warning)               # blocked: no run yet
    at.session_state["mode"] = "verify"; at.run(); run_button(at).click().run()
    at.session_state["mode"] = "report"; at.run()
    [b for b in at.button if b.key == "rp_go"][0].click().run()
    rep = at.session_state["vp_report"]
    assert not at.exception and rep["parcel_id"] == "DV-003" and rep["data"][:4] == b"%PDF"


def test_changed_settings_block_the_report_until_rerun(app):
    at = app(mode="verify")
    at.selectbox(key="vw_pick").set_value("DV-003").run(); run_button(at).click().run()
    at.session_state["vw_tol"] = 9.0
    at.session_state["mode"] = "report"; at.run()
    assert any("settings" in w.value.lower() for w in at.warning)


def test_safety_card_and_voice_button_render(app):
    at = app(mode="verify")
    at.selectbox(key="vw_pick").set_value("DV-023").run()
    run_button(at).click().run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "SAFETY SUMMARY" in html and "boundary overlap" in html
    assert len(at.session_state["vp_run"]["results"]) == 10


def test_reference_search_lists_matches(app):
    at = app(mode="profile")
    at.text_input(key="pp_ref").set_value("Dag No. 0540").run()
    assert not at.exception
    assert any("DV-023" in m.value for m in at.markdown)


def test_speech_text_is_built_from_the_summary_only():
    from src.ui_safety import speech_html, speech_text
    from src.verification_engine import safety_summary
    run = {"parcel_id": "DV-025", "results": [{"check_id": "encumbrance", "title": "Mortgage", "status": "REVIEW_REQUIRED", "summary": "x"}]}
    s = safety_summary(run)
    bn, en = speech_text(s, "bn"), speech_text(s, "en")
    assert "DV-025" in bn and "বন্ধক" in bn and "প্রোটোটাইপ" in bn
    assert "Needs checking" in en and "not legal proof" in en
    h = speech_html('a "quoted" </script> text', "bn")
    assert "</script> text" not in h and 'startsWith(WANT)' in h        # text is JSON-encoded, cannot close the script tag
