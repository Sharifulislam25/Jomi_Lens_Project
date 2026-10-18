import hashlib

import pytest

from src import registry_crypto as rc

H = hashlib.sha256(b"deed").hexdigest()
SIG = rc.sign_hash(H)
PUB = rc.public_hex()


def test_signature_validity_and_rejection():
    assert rc.verify_signature(PUB, H, SIG)
    assert not rc.verify_signature(PUB, hashlib.sha256(b"deed!").hexdigest(), SIG)          # different content
    assert not rc.verify_signature(PUB, H, "00" * 64)                                        # wrong signature
    other = rc.sign_hash(H, rc.Ed25519PrivateKey.generate())
    assert not rc.verify_signature(PUB, H, other)                                            # signed by someone else
    for bad in (("zz", "zz", "zz"), ("", "", ""), (None, None, None)):
        assert rc.verify_signature(*bad) is False                                            # never raises


def make(n=3):
    out, prev = [], rc.GENESIS
    for i in range(1, n + 1):
        e = rc.build_entry(prev, i, "t", f"D{i}", H, SIG, rc.ISSUER_KID)
        out.append(e)
        prev = e["entry_hash"]
    return out


def test_ledger_chain_detects_edit_removal_insertion_and_reorder():
    ok = make()
    assert rc.verify_chain(ok)["ok"] and rc.verify_chain([])["ok"]
    edited = [dict(ok[0]), dict(ok[1], sha256="0" * 64), dict(ok[2])]
    r = rc.verify_chain(edited)
    assert not r["ok"] and r["bad_index"] == 2 and "edited" in r["reason"]
    assert not rc.verify_chain([ok[0], ok[2]])["ok"]                                         # middle entry removed
    assert not rc.verify_chain([ok[1], ok[2]])["ok"]                                         # first entry removed
    assert rc.verify_chain([ok[0], ok[2], ok[1]])["ok"]                                      # input order does not matter: entries are ordered by index
    extra = rc.build_entry(rc.GENESIS, 2, "t", "X", H, SIG, rc.ISSUER_KID)                   # forged entry spliced in
    assert not rc.verify_chain([ok[0], extra, ok[2]])["ok"]


def test_qr_payload_round_trip_and_strict_parsing():
    payload = rc.build_payload("DV-001-D1", "DV-001", H, rc.ISSUER_KID, SIG)
    assert rc.parse_payload(payload)["sha256"] == H
    for bad in ("", None, "hello", payload.replace("v1", "v9"), payload + "x", payload.replace(H, "zz")):
        assert rc.parse_payload(bad) == {}


def test_qr_image_encode_decode():
    payload = rc.build_payload("DV-001-D1", "DV-001", H, rc.ISSUER_KID, SIG)
    assert rc.decode_qr(rc.make_qr_png(payload)) == payload
    assert rc.decode_qr(b"not an image") is None and rc.decode_qr(b"") is None and rc.decode_qr(b"x" * 6_000_000) is None


def test_qr_against_file():
    payload = rc.build_payload("DV-001-D1", "DV-001", H, rc.ISSUER_KID, SIG)
    keys = {rc.ISSUER_KID: PUB}
    assert rc.verify_qr_against_file(payload, b"deed", keys)["ok"]
    bad = rc.verify_qr_against_file(payload, b"deed!", keys)
    assert not bad["ok"] and not bad["hash_match"]
    assert not rc.verify_qr_against_file(payload, b"deed", {})["ok"]                         # unknown issuer
    forged = rc.build_payload("DV-001-D1", "DV-001", H, rc.ISSUER_KID, "00" * 64)
    assert not rc.verify_qr_against_file(forged, b"deed", keys)["signature_valid"]
    assert not rc.verify_qr_against_file("garbage", b"deed", keys)["ok"]
