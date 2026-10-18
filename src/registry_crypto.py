"""Cryptographic validation for the SYNTHETIC registry: Ed25519 issuer signatures, a hash-chained append-only document ledger, and QR payloads.

IMPORTANT: the demo issuer key is derived from a fixed public string so the demo is reproducible. It is NOT a real authority and carries no
legal weight; it only demonstrates how signed documents and tamper-evident logs would work in a real registry.
Interface used by src/verification_engine.py: verify_chain(entries) and verify_signature(public_key_hex, sha256_hex, signature_hex)."""
import hashlib
import io
import re

import cv2
import numpy as np
import qrcode
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ISSUER_KID = "DEMO-ISSUER-SUBREGISTRY-01"
ISSUER_LABEL = "Demo Sub-Registry Office (SIMULATED issuer, not a real authority)"
GENESIS = "0" * 64


def demo_private_key() -> Ed25519PrivateKey:
    seed = hashlib.sha256(b"JomiLens synthetic demo issuer - key is public by design, NOT a real authority").digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_hex(private_key=None) -> str:
    return (private_key or demo_private_key()).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def sign_hash(sha256_hex: str, private_key=None) -> str:
    """Sign the SHA-256 hex digest of a document (the signed payload is the hex text itself)."""
    return (private_key or demo_private_key()).sign(sha256_hex.encode()).hex()


def verify_signature(public_key_hex: str, sha256_hex: str, signature_hex: str) -> bool:
    """True only if the signature is valid for exactly this digest. Never raises on malformed input."""
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(bytes.fromhex(signature_hex), sha256_hex.encode())
        return True
    except (InvalidSignature, ValueError, TypeError, AttributeError):
        return False


# ----------------------------------------------------------------------------------------------- ledger
def entry_hash(prev_hash, entry_index, ts, doc_id, sha256, signature, signer_kid) -> str:
    return hashlib.sha256("|".join([prev_hash, str(entry_index), str(ts), str(doc_id), str(sha256), str(signature), str(signer_kid)]).encode()).hexdigest()


def build_entry(prev_hash, entry_index, ts, doc_id, sha256, signature, signer_kid) -> dict:
    return {"entry_index": entry_index, "ts": ts, "doc_id": doc_id, "sha256": sha256, "signature": signature, "signer_kid": signer_kid,
            "prev_hash": prev_hash, "entry_hash": entry_hash(prev_hash, entry_index, ts, doc_id, sha256, signature, signer_kid)}


def verify_chain(entries) -> dict:
    """Recompute every link and hash. Detects edited, removed, inserted or reordered entries.
    Returns {ok, checked, bad_index, reason}."""
    prev = GENESIS
    ents = sorted(entries or [], key=lambda e: e["entry_index"])
    for i, e in enumerate(ents):
        if e["prev_hash"] != prev:
            return {"ok": False, "checked": i, "bad_index": e["entry_index"],
                    "reason": "the link to the previous entry is broken (an entry was removed, inserted or reordered)"}
        if entry_hash(e["prev_hash"], e["entry_index"], e["ts"], e["doc_id"], e["sha256"], e["signature"], e["signer_kid"]) != e["entry_hash"]:
            return {"ok": False, "checked": i, "bad_index": e["entry_index"], "reason": "the entry no longer matches its hash (it was edited after being written)"}
        prev = e["entry_hash"]
    return {"ok": True, "checked": len(ents), "bad_index": None, "reason": "every link and hash verifies" if ents else "ledger is empty"}


# ----------------------------------------------------------------------------------------------- QR
_PAYLOAD = re.compile(r"^JOMILENS-VERIFY\|v1\|doc=([A-Za-z0-9\-]{3,40})\|parcel=([A-Za-z0-9\-]{3,40})\|sha256=([0-9a-f]{64})\|issuer=([A-Za-z0-9\-]{3,60})\|sig=([0-9a-f]{128})$")


def build_payload(doc_id: str, parcel_id: str, sha256: str, issuer_kid: str, signature: str) -> str:
    return f"JOMILENS-VERIFY|v1|doc={doc_id}|parcel={parcel_id}|sha256={sha256}|issuer={issuer_kid}|sig={signature}"


def parse_payload(text) -> dict:
    """Strictly parse a QR payload; returns {} if it does not match the expected format."""
    m = _PAYLOAD.match((text or "").strip())
    return {} if not m else {"doc_id": m[1], "parcel_id": m[2], "sha256": m[3], "issuer_kid": m[4], "signature": m[5]}


def make_qr_png(text: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def decode_qr(image_bytes: bytes):
    """Decode a QR image to text (None if none found). Size-capped."""
    if not image_bytes or len(image_bytes) > 5_000_000:
        return None
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    text, _pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return text or None


def verify_qr_against_file(qr_text: str, file_bytes: bytes, issuer_keys: dict) -> dict:
    """Check a scanned QR payload against a supplied file: does the file hash match the QR's hash, and does the issuer signature verify?"""
    p = parse_payload(qr_text)
    if not p:
        return {"ok": False, "reason": "The QR code is not a JomiLens verification code (unknown format)."}
    got = hashlib.sha256(file_bytes).hexdigest()
    pub = (issuer_keys or {}).get(p["issuer_kid"])
    sig_ok = bool(pub) and verify_signature(pub, p["sha256"], p["signature"])
    hash_ok = got == p["sha256"]
    reason = ("The file matches the hash in the QR code and the issuer signature verifies." if hash_ok and sig_ok else
              "The file does NOT match the hash in the QR code." if not hash_ok else
              "The issuer key is not recognised." if not pub else "The QR code's issuer signature does not verify.")
    return {"ok": hash_ok and sig_ok, "hash_match": hash_ok, "signature_valid": sig_ok, "doc_id": p["doc_id"], "parcel_id": p["parcel_id"],
            "computed_sha256": got, "qr_sha256": p["sha256"], "reason": reason}
