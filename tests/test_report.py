import io
import re

import pytest
from pypdf import PdfReader

from src import report_generator as rg
from src import vdb
from src.geo_tools import polygon_metrics
from src.verification_engine import run_verification
from src.verify_seed import rect_points

NOW = "2026-10-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _tmp_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "REPORT_DIR", tmp_path)


def text_of(data: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages))


def case_for(con, pid, **over):
    p = vdb.get_parcel(con, pid)
    import json
    p["points"] = [tuple(x) for x in json.loads(p["geometry_geojson"])["coordinates"][0]][:-1]
    recs, txs, docs = vdb.get_records(con, pid), vdb.get_transactions(con, pid), vdb.get_documents(con, pid)
    ctx = vdb.verification_context(con, pid)
    run = run_verification(pid, recs, txs, docs, now=NOW, context=ctx)
    c = {"parcel": p, "metrics": polygon_metrics(p["points"]), "records": recs, "transactions": txs, "run": run, "run_id": "RUN-TEST", "context": ctx,
         "documents": [{k: v for k, v in d.items() if k != "content"} for d in docs], "imagery": None, "comparison": None, "classification": None}
    c.update(over)
    return c


def test_report_contains_the_current_parcel_run_and_required_sections(con):
    path, data = rg.generate_verify_report(case_for(con, "DV-003"))
    t = text_of(data)
    assert path.exists() and data[:4] == b"%PDF"
    for needle in ("JomiLens Verify", "DV-003", "SYNTHETIC", "CONFLICT_FOUND", "Recorded areas differ", "RUN-TEST", "JLV-", "Report ID",
                   "Not an official land record", "not an official government document", "Limitations", "What this result means",
                   "Unresolved questions", "calculated area", "Equal-Area"):
        assert needle.lower() in t.lower(), needle
    assert "DV-001" not in t                                                       # nothing from another parcel


def test_report_for_another_parcel_shows_that_parcels_result(con):
    t1 = text_of(rg.generate_verify_report(case_for(con, "DV-001"))[1])
    t8 = text_of(rg.generate_verify_report(case_for(con, "DV-008"))[1])
    assert "DV-001" in t1 and "DV-008" not in t1 and "do not match their stored hash" not in t1
    assert "DV-008" in t8 and "do not match their stored hash" in t8


def test_stale_or_mixed_inputs_are_refused(con):
    other_run = run_verification("DV-001", vdb.get_records(con, "DV-001"), vdb.get_transactions(con, "DV-001"), vdb.get_documents(con, "DV-001"), now=NOW,
                                 context=vdb.verification_context(con, "DV-001"))
    with pytest.raises(ValueError, match="different parcel"):
        rg.generate_verify_report(case_for(con, "DV-003", run=other_run))
    with pytest.raises(ValueError, match="imagery"):
        rg.generate_verify_report(case_for(con, "DV-003", imagery={"parcel_id": "DV-001", "prepared": []}))
    with pytest.raises(ValueError, match="land-use"):
        rg.generate_verify_report(case_for(con, "DV-003", classification={"parcel_id": "DV-001"}))


def test_special_characters_are_escaped_not_interpreted(con):
    c = case_for(con, "DV-003")
    nasty = "A & B <script>alert(1)</script> </b> <font color=red>"
    c["parcel"]["scenario_title"] = nasty
    c["parcel"]["boundary_source"] = nasty
    c["records"][0]["record_reference"] = nasty
    c["run"]["results"][0]["summary"] = nasty
    _, data = rg.generate_verify_report(c)                                         # must not raise or produce a broken PDF
    t = text_of(data)
    assert "<script>" in t and "A & B" in t


def test_P_escapes_but_PM_keeps_trusted_markup():
    para = rg.P("5 < 6 & 7 > 3 <b>x</b>")
    assert "&lt;" in para.text and "&amp;" in para.text and "<b>" not in para.text.replace("&lt;b&gt;", "")
    assert "<b>" in rg.PM("<b>ok</b>").text


def test_report_without_records_run_or_imagery_still_builds_and_says_so(tmp_path):
    pts = rect_points(90.40, 23.80, 300)
    p = {"parcel_id": "USER-DRAWN", "points": pts, "boundary_type": "user_drawn", "boundary_source": "Drawn by the user", "boundary_source_date": None,
         "administrative_area": "", "is_synthetic": 0, "scenario_title": "My plot", "scenario_description": "", "expected_overall": None}
    _, data = rg.generate_verify_report({"parcel": p, "metrics": polygon_metrics(pts), "records": [], "transactions": [], "documents": [], "run": None,
                                         "imagery": None, "comparison": None, "classification": None})
    t = text_of(data)
    for needle in ("No records are available", "Verification was not run", "not loaded in this session", "No land-use classification", "NOT from the synthetic database"):
        assert needle.lower() in t.lower(), needle


def _details(**over):
    d = {"division": "A & B", "district": "<x>", "upazila": "", "mouza": "", "sheet": "", "survey": "", "dag_no": "", "khatian": "", "recorded_area": 0.0,
         "holders": [{"Party label": "Tom & <Jerry>", "Share": "1/1", "Basis (reference)": "a<b", "Note": "&"}]}
    d.update(over)
    return d


def test_my_plot_report_escapes_party_labels_and_place_fields():
    pts = rect_points(90.40, 23.80, 300)
    _, data = rg.generate_custom_report({"details": _details(), "metrics": polygon_metrics(pts), "history": [], "compare": None})
    t = text_of(data)
    assert "Tom & <Jerry>" in t and "A & B" in t


def test_my_plot_report_escapes_site_name_and_source_note():
    pts = rect_points(90.40, 23.80, 300)
    d = _details(site_name="Site <b>1</b> & co", source_note="x < y & z")
    _, data = rg.generate_custom_report({"details": d, "metrics": polygon_metrics(pts), "history": [], "compare": None})
    t = text_of(data)
    assert "Site <b>1</b> & co" in t and "x < y & z" in t


def test_report_includes_registers_surveys_signers_and_all_eight_checks(con):
    t = text_of(rg.generate_verify_report(case_for(con, "DV-015"))[1])
    for needle in ("Pending cases", "Khas / acquisition", "Survey", "CS", "BS", "Registers (synthetic)", "Restricts transfer", "Signer (simulated)", "DEMO-ISSUER-SUBREGISTRY-01",
                   "hash-chained", "Registration (sub-registry) vs mutation", "Document authenticity"):
        assert needle.lower() in t.lower(), needle
    assert "CONFLICT_FOUND" in t


def test_report_shows_capture_dates_for_open_sentinel_imagery(con):
    from PIL import Image
    c = case_for(con, "DV-011")
    prep = [{"date": "2018-12-13", "date_kind": "capture", "provider": "Copernicus Sentinel-2 L2A (ESA) via Element84 Earth Search / AWS Open Data", "season": "Dec 2018 - Feb 2019",
             "cloud_cover": 0.0, "resolution_m": 10.0, "raw": Image.new("RGB", (60, 40)), "poly_px": [(5, 5), (30, 5), (30, 30)], "greenness": 0.1}]
    c["imagery"] = {"parcel_id": "DV-011", "prepared": prep}
    t = text_of(rg.generate_verify_report(c)[1])
    for needle in ("Capture date", "Copernicus Sentinel", "2018-12-13", "Dec 2018 - Feb 2019", "one low-cloud scene per dry season"):
        assert needle.lower() in t.lower(), needle


def test_report_has_traffic_light_mortgage_register_and_ten_checks(con):
    t = text_of(rg.generate_verify_report(case_for(con, "DV-025"))[1])
    for needle in ("Safety summary: AMBER", "mortgaged", "Demo Bank B", "encumbrance register covers this parcel: yes",
                   "Mortgage, lien or attachment", "Boundary overlap with other registered parcels"):
        assert needle.lower() in t.lower(), needle
    t2 = text_of(rg.generate_verify_report(case_for(con, "DV-023"))[1])
    assert "Safety summary: RED" in t2 and "DV-024" in t2 and "boundary overlap" in t2.lower()


def test_report_has_mouza_price_and_a_clickable_google_maps_link(con):
    case = case_for(con, "DV-011")
    path, data = rg.generate_verify_report(case)
    t = text_of(data)
    lat, lon = case["metrics"]["centroid"]
    url = rg.google_maps_url(lat, lon)
    assert "Demo Mouza" in t and "BDT" in t and "not a valuation" in t
    links = []
    reader = PdfReader(io.BytesIO(data))
    for pg in reader.pages:
        for a in pg.get("/Annots") or []:
            o = a.get_object()
            if o.get("/A") and o["/A"].get("/URI"):
                links.append(o["/A"]["/URI"])
    assert url in links and url.startswith("https://www.google.com/maps?q=23.9")
