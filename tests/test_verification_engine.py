import pytest

from src import vdb
from src.verification_engine import (CONFLICT, NOT_RUN, PASS, REVIEW, UNAVAILABLE, check_conflicting_sales, check_document_integrity,
                                     check_record_consistency, normalize_ref, overall_status, run_verification, sha256_hex)

NOW = "2026-10-01T00:00:00Z"


def rec(i, typ, dag="125", kh="KH-1", area=5.0, unit="decimal", date="2018-03-12", party="P1"):
    return {"record_id": f"R{i}", "record_type": typ, "dag_ref": dag, "khatian_ref": kh, "recorded_area": area, "area_unit": unit,
            "record_date": date, "recorded_party_label": party}


def tx(i, seller, buyer, date, status="registered"):
    return {"transaction_id": f"T{i}", "seller_demo_id": seller, "buyer_demo_id": buyer, "transaction_date": date, "transaction_status": status}


def test_normalize_ref():
    assert normalize_ref("Dag No. 0125") == normalize_ref("125") == "125"
    assert normalize_ref("DAG-125/A") == normalize_ref("125 a") == "125a"
    assert normalize_ref("১২৫") == "125"                       # Bangla digits
    assert normalize_ref("125") != normalize_ref("152")        # meaningful differences are kept
    assert normalize_ref(None) is None and normalize_ref("Dag No") is None and normalize_ref("  ") is None


# ------------------------------------------------------------------ record consistency
def test_records_match():
    r = check_record_consistency([rec(1, "deed"), rec(2, "khatian", date="2019-01-10"), rec(3, "mutation", date="2019-02-20")], now=NOW)
    assert r["status"] == PASS and r["check_id"] == "record_consistency" and r["limitations"] and r["timestamp"] == NOW


def test_area_mismatch_is_a_conflict_with_fields_named():
    r = check_record_consistency([rec(1, "deed"), rec(2, "khatian", area=7.5, date="2019-01-10")], now=NOW)
    assert r["status"] == CONFLICT and "Recorded areas differ" in r["summary"]
    assert any(e["field"] == "Recorded area" and e["result"] == "CONFLICT" for e in r["evidence"])


def test_dag_mismatch_is_a_conflict():
    r = check_record_consistency([rec(1, "deed", dag="125"), rec(2, "khatian", dag="152", date="2019-01-10")], now=NOW)
    assert r["status"] == CONFLICT and any(e["field"].startswith("Dag") and e["result"] == "CONFLICT" for e in r["evidence"])


def test_formatting_differences_still_match():
    r = check_record_consistency([rec(1, "deed", dag="Dag No. 0210", kh="KH-2"), rec(2, "khatian", dag="210", kh="Kh 2", date="2019-01-10")], now=NOW)
    assert r["status"] == PASS


def test_area_tolerance_is_configurable():
    recs = [rec(1, "deed", area=5.00), rec(2, "khatian", area=5.075, date="2019-01-10")]            # 1.5% apart
    assert check_record_consistency(recs, now=NOW)["status"] == PASS
    assert check_record_consistency(recs, {"area_tolerance_pct": 1.0}, now=NOW)["status"] == CONFLICT


def test_unit_conversion_in_comparison():
    r = check_record_consistency([rec(1, "deed", area=5.0, unit="decimal"), rec(2, "khatian", area=3.03, unit="katha", date="2019-01-10")], now=NOW)
    assert r["status"] == PASS


def test_missing_required_record_needs_review_not_pass():
    r = check_record_consistency([rec(1, "deed"), rec(2, "mutation", date="2019-02-20")], now=NOW)
    assert r["status"] == REVIEW and "khatian" in r["summary"]


def test_too_few_records_unavailable():
    assert check_record_consistency([rec(1, "deed")], now=NOW)["status"] == UNAVAILABLE
    assert check_record_consistency([], now=NOW)["status"] == UNAVAILABLE
    assert check_record_consistency(None, now=NOW)["status"] == UNAVAILABLE


def test_mutation_before_deed_needs_review():
    r = check_record_consistency([rec(1, "deed", date="2018-08-20"), rec(2, "khatian", date="2019-01-10"), rec(3, "mutation", date="2017-11-02")], now=NOW)
    assert r["status"] == REVIEW and "before the deed" in r["summary"]


def test_missing_field_is_not_assumed_to_match():
    r = check_record_consistency([rec(1, "deed", kh=None), rec(2, "khatian", kh="KH-1", date="2019-01-10")], now=NOW)
    assert r["status"] == REVIEW
    r2 = check_record_consistency([rec(1, "deed", area=None), rec(2, "khatian", area=None, date="2019-01-10")], now=NOW)
    assert r2["status"] == REVIEW


def test_unreadable_unit_and_date_need_review():
    r = check_record_consistency([rec(1, "deed", unit="furlong"), rec(2, "khatian", date="not-a-date")], now=NOW)
    assert r["status"] in (REVIEW, CONFLICT) and r["status"] != PASS


# ------------------------------------------------------------------ conflicting sales
def test_clean_sale_chain_passes():
    r = check_conflicting_sales([tx(1, "S", "A", "2019-01-01"), tx(2, "A", "B", "2021-01-01")], [rec(1, "deed", party="B")], now=NOW)
    assert r["status"] == PASS


def test_duplicate_sale_detected():
    r = check_conflicting_sales([tx(1, "S", "A", "2020-05-04"), tx(2, "S", "B", "2020-09-15")], now=NOW)
    assert r["status"] == CONFLICT and any(e["rule"] == "DUPLICATE_SALE" for e in r["evidence"])


def test_chain_break_detected():
    r = check_conflicting_sales([tx(1, "S", "A", "2019-02-11"), tx(2, "X", "B", "2021-07-30")], now=NOW)
    assert r["status"] == CONFLICT and any(e["rule"] == "CHAIN_BREAK" for e in r["evidence"])


def test_overlapping_claims_including_pending():
    r = check_conflicting_sales([tx(1, "S", "A", "2022-03-01"), tx(2, "S", "B", "2022-03-18", "pending")], now=NOW)
    assert r["status"] == CONFLICT and any(e["rule"] == "OVERLAPPING_CLAIMS" for e in r["evidence"])
    r2 = check_conflicting_sales([tx(1, "S", "A", "2022-03-01"), tx(2, "S", "B", "2022-03-18", "pending")], settings={"overlap_days": 5}, now=NOW)
    assert any(e["rule"] == "DUPLICATE_SALE" for e in r2["evidence"])        # outside the window it is still a duplicate


def test_cancelled_transactions_are_ignored():
    r = check_conflicting_sales([tx(1, "S", "A", "2020-01-01"), tx(2, "S", "B", "2020-02-01", "cancelled")], now=NOW)
    assert r["status"] == PASS
    assert check_conflicting_sales([tx(1, "S", "A", "2020-01-01", "cancelled")], now=NOW)["status"] == PASS


def test_holder_mismatch_needs_review_and_no_transactions_unavailable():
    r = check_conflicting_sales([tx(1, "S", "A", "2020-01-10")], [rec(1, "deed", party="Z")], now=NOW)
    assert r["status"] == REVIEW
    assert check_conflicting_sales([], now=NOW)["status"] == UNAVAILABLE


def test_self_transfer_and_bad_date_need_review():
    assert check_conflicting_sales([tx(1, "S", "S", "2020-01-10")], now=NOW)["status"] == REVIEW
    assert check_conflicting_sales([tx(1, "S", "A", "garbage")], now=NOW)["status"] == REVIEW


# ------------------------------------------------------------------ document integrity
def doc(i, content=b"hello", expected=None, **kw):
    return {"document_id": f"D{i}", "record_id": f"R{i}", "filename": f"d{i}.txt", "content": content,
            "expected_sha256": sha256_hex(b"hello") if expected is None else expected, **kw}


def test_sha256_known_vector():
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_matching_hash_passes_but_limits_are_stated():
    r = check_document_integrity([doc(1)], now=NOW)
    assert r["status"] == PASS and any("authentic" in l for l in r["limitations"]) and "NOT show" in r["meaning"]


def test_mismatching_hash_is_a_conflict():
    r = check_document_integrity([doc(1, content=b"hello!")], now=NOW)
    assert r["status"] == CONFLICT and r["evidence"][0]["result"] == "MISMATCH"
    assert r["evidence"][0]["computed_sha256"] != r["evidence"][0]["expected_sha256"]


def test_uploaded_file_overrides_the_fixture():
    assert check_document_integrity([doc(1, content=b"hello!")], uploaded={"D1": b"hello"}, now=NOW)["status"] == PASS
    assert check_document_integrity([doc(1)], uploaded={"D1": b"changed"}, now=NOW)["status"] == CONFLICT


def test_missing_hash_file_or_invalid_hash_is_not_a_pass():
    assert check_document_integrity([doc(1, expected="")], now=NOW)["status"] == UNAVAILABLE
    assert check_document_integrity([doc(1, content=None)], now=NOW)["status"] == UNAVAILABLE
    assert check_document_integrity([doc(1, expected="xyz")], now=NOW)["status"] == UNAVAILABLE
    assert check_document_integrity([doc(1), doc(2, expected="")], now=NOW)["status"] == REVIEW
    assert check_document_integrity([], now=NOW)["status"] == UNAVAILABLE


# ------------------------------------------------------------------ overall + audit
def test_overall_status_keeps_uncertainty():
    mk = lambda s: {"status": s}
    assert overall_status([mk(PASS), mk(PASS), mk(PASS)]) == PASS
    assert overall_status([mk(PASS), mk(UNAVAILABLE), mk(PASS)]) == REVIEW          # never a clean pass with an unresolved check
    assert overall_status([mk(PASS), mk(NOT_RUN), mk(PASS)]) == REVIEW
    assert overall_status([mk(UNAVAILABLE)] * 3) == UNAVAILABLE
    assert overall_status([mk(CONFLICT), mk(PASS), mk(REVIEW)]) == CONFLICT
    assert overall_status([]) == NOT_RUN


def test_structured_result_and_reproducibility():
    args = ([rec(1, "deed"), rec(2, "khatian", date="2019-01-10")], [tx(1, "S", "P1", "2018-03-12")], [doc(1)])
    a = run_verification("P", *args, now=NOW)
    b = run_verification("P", *args, now=NOW)
    assert a == b                                                                  # same inputs -> same saved result
    for r in a["results"]:
        assert set(r) >= {"check_id", "status", "summary", "evidence", "limitations", "timestamp", "meaning"}
    assert [r["check_id"] for r in a["results"]] == ["record_consistency", "conflicting_sales", "document_integrity"]


def test_all_25_seeded_scenarios_produce_their_designed_result(con):
    parcels = vdb.list_parcels(con)
    assert len(parcels) == 25
    for p in parcels:
        pid = p["parcel_id"]
        run = run_verification(pid, vdb.get_records(con, pid), vdb.get_transactions(con, pid), vdb.get_documents(con, pid), context=vdb.verification_context(con, pid))
        assert len(run["results"]) == 10 and run["engine_version"] == "3.0"
        assert run["overall_status"] == p["expected_overall"], pid
