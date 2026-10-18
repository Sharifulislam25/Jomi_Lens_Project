"""The P5 checks: survey chain, registration vs mutation, pending cases, khas/acquisition, authenticity (signatures + ledger), rapid transfers."""
import hashlib

import pytest

from src import registry_crypto as rc
from src.verification_engine import (CONFLICT, PASS, REVIEW, UNAVAILABLE, check_conflicting_sales, check_document_authenticity, check_document_integrity,
                                     check_khas_acquisition, check_pending_cases, check_registration_mutation, check_survey_chain, run_verification, sha256_hex)

NOW = "2026-10-01T00:00:00Z"


def sv(gen, dag, prev, area=5.0):
    return {"record_id": f"S-{gen}", "record_type": "survey reference", "survey_gen": gen, "dag_ref": dag, "prev_dag_ref": prev, "recorded_area": area, "area_unit": "decimal"}


GOOD = [sv("CS", "98", None, 5.3), sv("SA", "112", "98", 5.25), sv("RS", "125", "112", 5.2), sv("BS", "125", "125", 5.0)]


def test_survey_chain_passes_and_renumbering_is_allowed():
    assert check_survey_chain(GOOD, now=NOW)["status"] == PASS


def test_survey_lineage_break_is_a_conflict():
    bad = [dict(x) for x in GOOD]
    bad[3]["prev_dag_ref"] = "140"
    r = check_survey_chain(bad, now=NOW)
    assert r["status"] == CONFLICT and any(e.get("result") == "LINEAGE BREAK" for e in r["evidence"])


def test_survey_area_drift_missing_generation_and_undeclared_lineage():
    drift = [dict(x) for x in GOOD]
    drift[2]["recorded_area"] = 12.0
    assert check_survey_chain(drift, now=NOW)["status"] == REVIEW
    no_sa = [GOOD[0], dict(GOOD[2], prev_dag_ref="98"), GOOD[3]]                                  # SA missing, RS honestly names CS as its parent
    r = check_survey_chain(no_sa, now=NOW)
    assert r["status"] == REVIEW and "SA survey record is missing" in r["summary"]
    assert check_survey_chain([GOOD[0], GOOD[2], GOOD[3]], now=NOW)["status"] == CONFLICT       # RS names dag 112 as parent but no SA exists: lineage break
    undeclared = [dict(x) for x in GOOD]
    undeclared[3]["prev_dag_ref"] = None
    assert check_survey_chain(undeclared, now=NOW)["status"] == REVIEW
    assert check_survey_chain([GOOD[0]], now=NOW)["status"] == UNAVAILABLE and check_survey_chain([], now=NOW)["status"] == UNAVAILABLE


def reg(typ, date, party="P1", rid=None):
    return {"record_id": rid or typ.upper(), "record_type": typ, "record_date": date, "recorded_party_label": party}


ASOF = {"as_of_date": "2026-10-01"}


def test_registration_mutation_links():
    assert check_registration_mutation([reg("deed", "2024-01-01"), reg("mutation", "2024-02-01")], ASOF, NOW)["status"] == PASS
    assert check_registration_mutation([reg("deed", "2024-01-01"), reg("mutation", "2024-02-01", "P2")], ASOF, NOW)["status"] == CONFLICT      # parties differ
    assert check_registration_mutation([reg("deed", "2024-01-01"), reg("mutation", "2023-06-01")], ASOF, NOW)["status"] == REVIEW           # impossible order
    assert check_registration_mutation([reg("deed", "2024-01-01")], ASOF, NOW)["status"] == REVIEW                                         # no mutation, far past deadline
    assert check_registration_mutation([reg("deed", "2026-09-01")], ASOF, NOW)["status"] == PASS                                           # still within 90 days
    assert check_registration_mutation([reg("mutation", "2024-02-01")], ASOF, NOW)["status"] == UNAVAILABLE
    assert check_registration_mutation([reg("deed", "2024-01-01", None), reg("mutation", "2024-02-01", None)], ASOF, NOW)["status"] == REVIEW


def test_pending_cases():
    cov = {"case_register": True}
    case = lambda status, restricts: {"case_id": "C1", "case_type": "title suit", "court_label": "x", "status": status, "filed_date": "2024-01-01", "restricts_transfer": restricts}
    assert check_pending_cases([case("pending", 1)], cov, NOW)["status"] == CONFLICT
    assert check_pending_cases([case("pending", 0)], cov, NOW)["status"] == REVIEW
    assert check_pending_cases([case("disposed", 0)], cov, NOW)["status"] == PASS
    assert check_pending_cases([], cov, NOW)["status"] == PASS
    assert check_pending_cases([], {"case_register": False}, NOW)["status"] == UNAVAILABLE          # no coverage -> absence is NOT a pass
    assert check_pending_cases([], None, NOW)["status"] == UNAVAILABLE


def test_khas_acquisition():
    cov = {"khas_register": True}
    e = lambda typ, status: {"entry_id": "K1", "status_type": typ, "status": status, "authority_label": "a", "notice_ref": "n", "notice_date": "2025-01-01"}
    assert check_khas_acquisition([e("khas", "recorded")], cov, NOW)["status"] == CONFLICT
    assert check_khas_acquisition([e("vested", "recorded")], cov, NOW)["status"] == CONFLICT
    assert check_khas_acquisition([e("acquisition", "notified")], cov, NOW)["status"] == CONFLICT
    assert check_khas_acquisition([e("acquisition", "proposed")], cov, NOW)["status"] == REVIEW
    assert check_khas_acquisition([e("khas", "released")], cov, NOW)["status"] == PASS
    assert check_khas_acquisition([], cov, NOW)["status"] == PASS
    assert check_khas_acquisition([], {"khas_register": False}, NOW)["status"] == UNAVAILABLE


# ---------------------------------------------------------------- authenticity
ORIGINAL = b"SYNTHETIC deed text"


def signed_doc(content=ORIGINAL, stored=None, doc_id="D1"):
    h = sha256_hex(ORIGINAL)
    return {"document_id": doc_id, "record_id": "R1", "filename": "d.txt", "content": content, "expected_sha256": stored or h, "signature": rc.sign_hash(h), "signer_kid": rc.ISSUER_KID}


def ledger_for(*docs):
    out, prev = [], rc.GENESIS
    for i, d in enumerate(docs, start=1):
        e = rc.build_entry(prev, i, "t", d["document_id"], sha256_hex(ORIGINAL), d["signature"], d["signer_kid"])
        out.append(e)
        prev = e["entry_hash"]
    return out


KEYS = {rc.ISSUER_KID: rc.public_hex()}


def test_authentic_signed_document_in_intact_ledger_passes():
    d = signed_doc()
    assert check_document_authenticity([d], ledger_for(d), KEYS, now=NOW)["status"] == PASS


def test_altered_content_fails_signature():
    d = signed_doc(content=ORIGINAL + b"!")
    assert check_document_authenticity([d], ledger_for(d), KEYS, now=NOW)["status"] == CONFLICT
    assert check_document_integrity([d], now=NOW)["status"] == CONFLICT


def test_rehashed_forgery_passes_the_plain_hash_check_but_not_the_signature():
    forged = ORIGINAL + b" (forged)"
    d = signed_doc(content=forged, stored=sha256_hex(forged))            # attacker replaced the stored hash too
    assert check_document_integrity([d], now=NOW)["status"] == PASS      # a bare hash check is fooled ...
    r = check_document_authenticity([d], ledger_for(signed_doc()), KEYS, now=NOW)
    assert r["status"] == CONFLICT and any("signature does not verify" in str(e.get("problems", "")) for e in r["evidence"])   # ... the signature is not


def test_tampered_ledger_is_detected():
    d = signed_doc()
    led = ledger_for(d)
    led[0] = dict(led[0], sha256="0" * 64)                                # edited after being written
    r = check_document_authenticity([d], led, KEYS, now=NOW)
    assert r["status"] == CONFLICT and "ledger is broken" in r["summary"]


def test_unknown_signer_unsigned_and_missing_file():
    d = signed_doc()
    assert check_document_authenticity([dict(d, signer_kid="OTHER")], ledger_for(d), KEYS, now=NOW)["status"] == CONFLICT
    unsigned = dict(d, signature=None, signer_kid=None)
    assert check_document_authenticity([unsigned], [], KEYS, now=NOW)["status"] == UNAVAILABLE
    assert check_document_authenticity([d, unsigned], ledger_for(d), KEYS, now=NOW)["status"] == REVIEW
    assert check_document_authenticity([dict(d, content=None)], ledger_for(d), KEYS, now=NOW)["status"] == UNAVAILABLE
    assert check_document_authenticity([], [], KEYS, now=NOW)["status"] == UNAVAILABLE


def test_uploaded_file_replaces_the_fixture_in_the_authenticity_check():
    d = signed_doc(content=ORIGINAL + b"!")
    assert check_document_authenticity([d], ledger_for(d), KEYS, uploaded={"D1": ORIGINAL}, now=NOW)["status"] == PASS


# ---------------------------------------------------------------- rapid transfers
def tx(i, s, b, d):
    return {"transaction_id": f"T{i}", "seller_demo_id": s, "buyer_demo_id": b, "transaction_date": d, "transaction_status": "registered"}


def test_rapid_transfers_need_review_and_the_window_is_configurable():
    txs = [tx(1, "S", "A", "2023-01-05"), tx(2, "A", "B", "2023-01-30"), tx(3, "B", "C", "2023-02-12")]
    r = check_conflicting_sales(txs, now=NOW)
    assert r["status"] == REVIEW and any(e["rule"] == "RAPID_TRANSFER" for e in r["evidence"])
    assert check_conflicting_sales(txs, settings={"rapid_days": 10}, now=NOW)["status"] == PASS
    slow = [tx(1, "S", "A", "2019-01-05"), tx(2, "A", "B", "2021-01-30")]
    assert check_conflicting_sales(slow, now=NOW)["status"] == PASS


def test_run_with_context_runs_ten_checks_in_order():
    d = signed_doc()
    ctx = {"cases": [], "khas": [], "coverage": {"case_register": True, "khas_register": True, "encumbrance_register": True}, "ledger": ledger_for(d),
           "issuer_keys": KEYS, "encumbrances": [], "points": [(90.40, 23.80), (90.4002, 23.80), (90.4002, 23.8002), (90.40, 23.8002)], "other_parcels": []}
    recs = [dict(reg("deed", "2024-01-01"), dag_ref="125", khatian_ref="K", recorded_area=5, area_unit="decimal"),
            dict(reg("khatian", "2024-03-01"), dag_ref="125", khatian_ref="K", recorded_area=5, area_unit="decimal"), reg("mutation", "2024-02-01")] + [dict(x, khatian_ref="K") for x in GOOD]
    run = run_verification("P", recs, [tx(1, "S", "P1", "2024-01-01")], [d], settings=ASOF, context=ctx, now=NOW)
    assert [r["check_id"] for r in run["results"]] == ["record_consistency", "registration_mutation", "survey_chain", "boundary_overlap", "conflicting_sales",
                                                       "document_integrity", "document_authenticity", "pending_cases", "khas_acquisition", "encumbrance"]
    assert run["overall_status"] == PASS
    assert len(run_verification("P", recs, [], [d], now=NOW)["results"]) == 3          # no context -> the original three only
