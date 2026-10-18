import re

import pytest

from src import vdb, vstate
from src.privacy import personal_data_reason
from src.verification_engine import run_verification


def test_schema_and_counts(con):
    c = vdb.counts(con)
    assert c["parcels"] == 25 and c["records"] > 100 and c["transactions"] > 15 and c["documents"] > 30 and c["classifications"] == 25
    assert c["pending_cases"] >= 2 and c["khas_entries"] >= 2 and c["encumbrances"] >= 2 and c["ledger_entries"] > 20


def test_everything_is_synthetic_and_has_no_personal_data(con):
    assert con.execute("SELECT COUNT(*) FROM parcels WHERE is_synthetic != 1").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM land_records WHERE is_synthetic != 1").fetchone()[0] == 0
    phone_or_nid = re.compile(r"\d{10,}")
    for table, cols in (("land_records", "record_reference,recorded_party_label,notes,source_description"),
                        ("transactions", "buyer_demo_id,seller_demo_id"), ("parcels", "boundary_source,scenario_description")):
        for row in con.execute(f"SELECT {cols} FROM {table}").fetchall():
            for v in row:
                assert not phone_or_nid.search(str(v or "")), (table, v)
    labels = {r[0] for r in con.execute("SELECT recorded_party_label FROM land_records")} | {r[0] for r in con.execute("SELECT buyer_demo_id FROM transactions")}
    assert all(str(l).startswith("DEMO-PARTY-") for l in labels if l)


def test_parcel_boundaries_are_labelled_synthetic(con):
    for p in vdb.list_parcels(con):
        assert p["boundary_type"] == "synthetic_demo" and "NOT a real" in p["boundary_source"]


def test_sql_is_parameterised(con):
    evil = "DV-001' OR '1'='1"
    assert vdb.get_parcel(con, evil) is None and vdb.get_records(con, evil) == []
    assert vdb.counts(con)["parcels"] == 25                                        # nothing dropped or leaked
    assert vdb.get_parcel(con, "DV-001")["parcel_id"] == "DV-001"


def test_fixture_reader_blocks_path_traversal(seeded):
    assert vdb.read_fixture("../../../etc/passwd") is None
    assert vdb.read_fixture("") is None and vdb.read_fixture(None) is None


def test_runs_are_appended_not_overwritten(con):
    p = "DV-003"
    run = run_verification(p, vdb.get_records(con, p), vdb.get_transactions(con, p), vdb.get_documents(con, p))
    r1, r2 = vdb.save_run(con, p, run), vdb.save_run(con, p, run)
    assert r1 != r2 and {r["run_id"] for r in vdb.list_runs(con, p)} >= {r1, r2}
    back = vdb.get_run(con, r1)
    assert back["overall_status"] == run["overall_status"] and back["settings"] == run["settings"] and back["results"] == run["results"]


def test_imagery_and_classification_storage(con):
    vdb.save_imagery_observations(con, "DV-001", [{"provider": "Esri", "imagery_item_id": "x", "release_date": "2024-01-01", "capture_date": None, "resolution_m": 1.09,
                                                    "quality_notes": "n", "attribution": "a"}])
    obs = vdb.get_imagery_observations(con, "DV-001")
    assert obs and obs[0]["capture_date"] is None                                  # capture date is never invented
    vdb.save_classification(con, "DV-001", {"class_label": "unknown", "method": "rules", "confidence": None, "model_version": "rules-v1", "evidence_summary": "e"})
    assert vdb.get_classifications(con, "DV-001")[0]["confidence"] is None


# ------------------------------------------------------------------ state invalidation
def test_selecting_another_parcel_clears_results():
    st = {}
    vstate.select_parcel(st, "DV-001")
    vstate.store_run(st, {"parcel_id": "DV-001", "settings": {}, "uploaded_documents": []}, "RUN-1")
    vstate.store_imagery(st, "DV-001", {"prepared": [1]})
    st["vp_class"], st["vp_report"] = {"parcel_id": "DV-001"}, {"parcel_id": "DV-001"}
    assert vstate.current_run(st) and vstate.current_imagery(st)
    assert vstate.select_parcel(st, "DV-002") is True
    assert vstate.current_run(st) is None and vstate.current_imagery(st) is None and "vp_class" not in st and "vp_report" not in st


def test_reselecting_same_parcel_keeps_results():
    st = {}
    vstate.select_parcel(st, "DV-001")
    vstate.store_run(st, {"parcel_id": "DV-001", "settings": {}, "uploaded_documents": []})
    assert vstate.select_parcel(st, "DV-001") is False and vstate.current_run(st)


def test_run_for_other_parcel_is_refused_and_a_stale_run_is_never_returned():
    st = {}
    vstate.select_parcel(st, "DV-002")
    with pytest.raises(ValueError):
        vstate.store_run(st, {"parcel_id": "DV-001"})
    with pytest.raises(ValueError):
        vstate.store_imagery(st, "DV-001", {})
    st["vp_run"] = {"parcel_id": "DV-001"}                                          # injected stale value
    assert vstate.current_run(st) is None


def test_new_run_invalidates_old_report_and_settings_change_marks_stale():
    st = {}
    vstate.select_parcel(st, "DV-001")
    st["vp_report"] = {"parcel_id": "DV-001"}
    run = {"parcel_id": "DV-001", "settings": {"area_tolerance_pct": 2.0}, "uploaded_documents": []}
    vstate.store_run(st, run)
    assert "vp_report" not in st
    assert not vstate.run_is_stale(run, {"area_tolerance_pct": 2.0})
    assert vstate.run_is_stale(run, {"area_tolerance_pct": 5.0})
    assert vstate.run_is_stale(run, {"area_tolerance_pct": 2.0}, ["DV-001-D1"])


# ------------------------------------------------------------------ privacy guard
@pytest.mark.parametrize("text,flag", [("Party A", False), ("DEMO-PARTY-B1", False), ("K-1234", False), ("01712345678", True), ("+880 1712-345678", True),
                                        ("1234567890123", True), ("someone@example.com", True), ("", False), (None, False)])
def test_personal_data_guard(text, flag):
    assert bool(personal_data_reason(text)) is flag
