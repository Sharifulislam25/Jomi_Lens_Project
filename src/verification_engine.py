"""Verification engine: pure, testable functions (no Streamlit, no database).

All inputs are plain dicts/lists. Every check returns the same structured result:
  {check_id, title, status, summary, evidence[], limitations[], meaning, timestamp}
Statuses: PASS | REVIEW_REQUIRED | CONFLICT_FOUND | UNAVAILABLE | NOT_RUN.
A result is never a legal finding: it only compares the synthetic records it is given."""
import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone

from src.geo_tools import to_sqm
from src.registry_crypto import verify_chain, verify_signature

ENGINE_VERSION = "3.0"
PASS, REVIEW, CONFLICT, UNAVAILABLE, NOT_RUN = "PASS", "REVIEW_REQUIRED", "CONFLICT_FOUND", "UNAVAILABLE", "NOT_RUN"
STATUSES = (PASS, REVIEW, CONFLICT, UNAVAILABLE, NOT_RUN)
DEFAULT_SETTINGS = {"area_tolerance_pct": 2.0, "area_tolerance_abs_sqm": 1.0, "overlap_days": 30,
                    "required_record_types": ["deed", "khatian"], "mutation_deadline_days": 90, "survey_area_drift_pct": 15.0,
                    "expected_survey_generations": ["CS", "SA", "RS", "BS"], "as_of_date": None, "rapid_days": 60,
                    "overlap_tolerance_sqm": 1.0, "overlap_tolerance_pct": 1.0}
SURVEY_ORDER = ["CS", "SA", "RS", "BS"]
COMPARABLE_TYPES = ("deed", "khatian", "mutation", "survey reference")
_STOP = {"dag", "no", "number", "num", "khatian", "kh", "plot", "nr"}

MEANING = {
    "record_consistency": {
        PASS: "The compared fictional records agree on the references and areas that they all state. This does not prove the records are real or complete.",
        REVIEW: "No direct contradiction was found, but something is missing or out of order. A person should look at the items listed.",
        CONFLICT: "At least two records disagree on a reference, area or date. In a real case this needs checking against the original records.",
        UNAVAILABLE: "There were not enough records to compare, so no conclusion is possible.",
        NOT_RUN: "This check has not been run yet."},
    "conflicting_sales": {
        PASS: "The simulated transfer history is in a consistent order with no overlapping claims. This is not proof that no problem exists.",
        REVIEW: "The history is not contradictory by itself, but one detail (such as the recorded holder) does not line up.",
        CONFLICT: "A rule flagged an inconsistent or overlapping simulated sale. This is a prompt for human review, not proof of fraud.",
        UNAVAILABLE: "No transactions are recorded for this parcel, so nothing could be evaluated.",
        NOT_RUN: "This check has not been run yet."},
    "document_integrity": {
        PASS: "The checked file is byte-for-byte identical to the copy recorded earlier. It does NOT show the document was originally genuine or legally valid.",
        REVIEW: "Some documents matched, but others could not be checked. The unchecked ones remain open.",
        CONFLICT: "A checked file differs from the recorded copy (it was changed, replaced or the wrong file was supplied).",
        UNAVAILABLE: "No document could be checked (no stored hash or no file).",
        NOT_RUN: "This check has not been run yet."},
}


MEANING.update({
    "survey_chain": {
        PASS: "The survey generations (CS, SA, RS, BS) link to each other through their dag numbers and the area changes stay modest. This does not prove any survey record is real.",
        REVIEW: "A survey generation is missing or the area changed a lot between generations. A person should read the survey records.",
        CONFLICT: "A later survey does not point back to the dag of the earlier survey (a broken lineage). In a real case this needs the original khatians.",
        UNAVAILABLE: "Fewer than two survey generations are recorded, so no lineage can be checked.", NOT_RUN: "This check has not been run yet."},
    "registration_mutation": {
        PASS: "The deed registered at the sub-registry has a matching mutation at the AC Land office in the same party label. This is a consistency check of synthetic records only.",
        REVIEW: "The registration and the mutation do not yet line up (no mutation after the deadline, or the order of dates is odd).",
        CONFLICT: "The mutation names a different party than the registered deed. In a real case this is a serious mismatch between the two offices' records.",
        UNAVAILABLE: "There is no registered deed to compare with a mutation.", NOT_RUN: "This check has not been run yet."},
    "pending_cases": {
        PASS: "No pending case is recorded in the (synthetic) case register for this parcel. This does not prove that no case exists in the real world.",
        REVIEW: "A pending case is recorded that does not by itself restrict transfer. Read it before going further.",
        CONFLICT: "A pending case that restricts transfer (such as an injunction) is recorded. Do not proceed without proper legal advice.",
        UNAVAILABLE: "The case register is not covered for this parcel, so pending cases were not checked.", NOT_RUN: "This check has not been run yet."},
    "khas_acquisition": {
        PASS: "No khas, vested-property or acquisition entry is recorded in the (synthetic) register for this parcel. This does not prove there is none.",
        REVIEW: "An acquisition is only proposed. Ask the authority for its current status.",
        CONFLICT: "The parcel is recorded as khas/vested land or as under notified or completed acquisition. A private sale may not be possible.",
        UNAVAILABLE: "The khas/acquisition register is not covered for this parcel, so it was not checked.", NOT_RUN: "This check has not been run yet."},
    "document_authenticity": {
        PASS: "The signature verifies under the SIMULATED issuer key and the ledger holds the same hash. This shows the demo mechanism works; it does not verify any real government document.",
        REVIEW: "Some documents verified but others could not be checked (no signature or no file).",
        CONFLICT: "A signature does not verify, the issuer key is unknown, the ledger entry is missing or different, or the ledger itself was altered.",
        UNAVAILABLE: "No signed document could be checked.", NOT_RUN: "This check has not been run yet."}})


MEANING.update({
    "boundary_overlap": {
        PASS: "This parcel's (synthetic) boundary does not overlap any other registered parcel beyond the drawing tolerance.",
        REVIEW: "The boundary could only be partly compared with neighbouring registered parcels.",
        CONFLICT: "Part of this parcel is also inside another registered parcel. The same land may have been registered or sold twice; a surveyor must resolve the boundary.",
        UNAVAILABLE: "There is no valid boundary for this parcel, so overlap could not be checked.",
        NOT_RUN: "This check has not been run yet."},
    "encumbrance": {
        PASS: "No active mortgage, lien or attachment is recorded in the (synthetic) encumbrance register.",
        REVIEW: "An active mortgage or lien is recorded. A buyer would normally need it released, or the lender's written consent, before the transfer.",
        CONFLICT: "A court attachment is recorded against the parcel. A transfer while it is in force may be void.",
        UNAVAILABLE: "The encumbrance register does not cover this parcel, so absence of a mortgage or lien cannot be confirmed.",
        NOT_RUN: "This check has not been run yet."},
})


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_ref(value):
    """Normalise a dag / khatian reference for comparison without erasing real differences.
    'Dag No. 0125' -> '125'; 'DAG-125/A' -> '125a'; '125' != '152'. Several dags written together ('125, 131', '131 and 125') become an
    order-independent canonical list ('125,131'), so a holding of several dags can be compared as a set. Returns None if nothing meaningful remains."""
    if value is None:
        return None
    s = unicodedata.normalize("NFKC", str(value)).strip().lower()
    s = "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in s)        # Bangla digits -> ASCII
    outs = []
    for piece in re.split(r"\s*(?:,|;|&|\band\b)\s*", s):
        tokens = [t for t in re.findall(r"[^\W_]+", piece) if t not in _STOP]
        if tokens:
            outs.append(re.sub(r"^0+(?=\d)", "", "".join(tokens)))
    return ",".join(sorted(set(outs))) if outs else None


def parse_date(value):
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _result(check_id, title, status, summary, evidence, limitations, now=None):
    assert status in STATUSES
    return {"check_id": check_id, "title": title, "status": status, "summary": summary, "evidence": evidence,
            "limitations": limitations, "meaning": MEANING[check_id][status], "timestamp": now or now_iso()}


# ----------------------------------------------------------------------------------------------- check 1
def check_record_consistency(records, settings=None, now=None) -> dict:
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    title = "Record consistency"
    lim = ["Compares only the synthetic records supplied; it cannot tell whether a record is genuine.",
           "Reference text is normalised (case, 'Dag No.', leading zeros) but different numbers are never treated as equal.",
           f"Area tolerance: {cfg['area_tolerance_pct']}% or {cfg['area_tolerance_abs_sqm']} m², whichever is larger."]
    recs = [r for r in (records or []) if r.get("record_type") in COMPARABLE_TYPES and (r.get("survey_gen") in (None, "", "BS"))]
    if len(recs) < 2:
        return _result("record_consistency", title, UNAVAILABLE,
                       f"Only {len(recs)} comparable record(s) found; at least 2 are needed.",
                       [{"record_id": r.get("record_id"), "record_type": r.get("record_type")} for r in recs], lim, now)
    evidence, conflicts, review = [], [], []
    for field, label in (("dag_ref", "Dag / plot reference"), ("khatian_ref", "Khatian reference")):
        raw = {r["record_id"]: r.get(field) for r in recs}
        norm = {k: normalize_ref(v) for k, v in raw.items()}
        present = {k: v for k, v in norm.items() if v is not None}
        if len(present) < 2:
            evidence.append({"field": label, "result": "not comparable", "values": raw,
                             "detail": "Fewer than two records state this field."})
            review.append(f"{label} is stated in fewer than two records.")
        elif len(set(present.values())) > 1:
            conflicts.append(f"{label} differs between records.")
            evidence.append({"field": label, "result": "CONFLICT", "values": raw, "normalised": norm,
                             "detail": "After normalisation the references are not the same."})
        else:
            evidence.append({"field": label, "result": "match", "values": raw, "normalised": norm,
                             "detail": "Same reference after normalisation."})
    areas = {}
    for r in recs:
        if r.get("recorded_area") is None:
            continue
        try:
            areas[r["record_id"]] = to_sqm(r["recorded_area"], r.get("area_unit") or "")
        except (ValueError, TypeError):
            review.append(f"Record {r['record_id']} has an unreadable area or unit.")
    if len(areas) < 2:
        evidence.append({"field": "Recorded area", "result": "not comparable", "detail": "Fewer than two records state a readable area."})
        review.append("Recorded area is stated in fewer than two records.")
    else:
        hi, lo = max(areas.values()), min(areas.values())
        allowed = max(cfg["area_tolerance_abs_sqm"], hi * cfg["area_tolerance_pct"] / 100)
        row = {"field": "Recorded area", "values_sqm": {k: round(v, 2) for k, v in areas.items()},
               "difference_sqm": round(hi - lo, 2), "allowed_sqm": round(allowed, 2)}
        if hi - lo > allowed:
            conflicts.append(f"Recorded areas differ by {hi - lo:.1f} m², more than the allowed {allowed:.1f} m².")
            row.update(result="CONFLICT", detail="The difference is larger than the tolerance.")
        else:
            row.update(result="match", detail="Within the tolerance.")
        evidence.append(row)
    deed = [parse_date(r.get("record_date")) for r in recs if r["record_type"] == "deed"]
    mut = [parse_date(r.get("record_date")) for r in recs if r["record_type"] == "mutation"]
    if any(r.get("record_date") and parse_date(r.get("record_date")) is None for r in recs):
        review.append("At least one record date could not be read.")
    if [d for d in deed if d] and [m for m in mut if m]:
        if min(m for m in mut if m) < min(d for d in deed if d):
            review.append("A mutation is dated before the deed it should follow.")
            evidence.append({"field": "Date order", "result": "REVIEW", "detail": "Mutation date is earlier than the deed date."})
        else:
            evidence.append({"field": "Date order", "result": "ok", "detail": "Mutation is not earlier than the deed."})
    have = {r["record_type"] for r in recs}
    for t in cfg["required_record_types"]:
        if t not in have:
            review.append(f"No {t} record is available to compare.")
            evidence.append({"field": f"Required record: {t}", "result": "missing"})
    if conflicts:
        return _result("record_consistency", title, CONFLICT, " ".join(conflicts), evidence, lim, now)
    if review:
        return _result("record_consistency", title, REVIEW, "No contradiction found, but: " + " ".join(review), evidence, lim, now)
    return _result("record_consistency", title, PASS, f"{len(recs)} records agree on every field they share.", evidence, lim, now)


# ----------------------------------------------------------------------------------------------- check 2
def check_conflicting_sales(transactions, records=None, settings=None, now=None) -> dict:
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    title = "Conflicting or duplicate sales"
    lim = ["Uses only simulated transactions for this internal parcel ID; real-world fraud cannot be concluded from it.",
           f"Consecutive transfers within {cfg['rapid_days']} days are flagged as rapid (possible flipping) for review.",
           "The first seller is assumed to be the starting owner because earlier history is not modelled.",
           f"Claims by the same seller to different buyers within {cfg['overlap_days']} days are treated as overlapping."]
    txs = list(transactions or [])
    if not txs:
        return _result("conflicting_sales", title, UNAVAILABLE, "No transactions are recorded for this parcel.", [], lim, now)
    active = [t for t in txs if (t.get("transaction_status") or "").lower() != "cancelled"]
    if not active:
        return _result("conflicting_sales", title, PASS, "All recorded transactions were cancelled, so there are no active claims.",
                       [{"transaction_id": t["transaction_id"], "status": "cancelled"} for t in txs], lim, now)
    far = date.max
    active.sort(key=lambda t: (parse_date(t.get("transaction_date")) or far, t["transaction_id"]))
    conflicts, review, evidence, flagged = [], [], [], set()
    for t in active:
        if parse_date(t.get("transaction_date")) is None:
            review.append(f"Transaction {t['transaction_id']} has no readable date.")
        if t.get("seller_demo_id") == t.get("buyer_demo_id"):
            review.append(f"Transaction {t['transaction_id']} has the same party as seller and buyer.")
    # Rule 1: overlapping claims by one seller on different buyers
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            da, db = parse_date(a.get("transaction_date")), parse_date(b.get("transaction_date"))
            if a["seller_demo_id"] == b["seller_demo_id"] and a["buyer_demo_id"] != b["buyer_demo_id"] and da and db \
                    and abs((db - da).days) <= cfg["overlap_days"]:
                conflicts.append(f"{a['transaction_id']} and {b['transaction_id']}: the same seller claims to sell to two buyers within "
                                 f"{abs((db - da).days)} days.")
                evidence.append({"rule": "OVERLAPPING_CLAIMS", "transactions": [a["transaction_id"], b["transaction_id"]],
                                 "detail": f"Seller {a['seller_demo_id']} -> {a['buyer_demo_id']} and {b['buyer_demo_id']}, {abs((db - da).days)} days apart."})
                flagged.update([a["transaction_id"], b["transaction_id"]])
    # Rule 2: walk the ownership chain
    owner, previous = active[0]["seller_demo_id"], set()
    for t in active:
        if t["transaction_id"] not in flagged and t["seller_demo_id"] != owner:
            if t["seller_demo_id"] in previous:
                rule, why = "DUPLICATE_SALE", f"{t['seller_demo_id']} already sold this parcel earlier and sells it again."
            else:
                rule, why = "CHAIN_BREAK", f"The seller {t['seller_demo_id']} is not the recorded current owner ({owner})."
            conflicts.append(f"{t['transaction_id']}: {why}")
            evidence.append({"rule": rule, "transactions": [t["transaction_id"]], "detail": why})
        previous.add(t["seller_demo_id"])
        owner = t["buyer_demo_id"]
    # Rule 4: suspicious rapid transfers (flipping)
    rapid = [(a, b) for a, b in zip(active, active[1:]) if parse_date(a.get("transaction_date")) and parse_date(b.get("transaction_date"))
             and 0 <= (parse_date(b["transaction_date"]) - parse_date(a["transaction_date"])).days <= cfg["rapid_days"]]
    if len(rapid) >= 1 and not conflicts:
        for a, b in rapid:
            days = (parse_date(b["transaction_date"]) - parse_date(a["transaction_date"])).days
            review.append(f"Rapid transfer: {a['transaction_id']} and {b['transaction_id']} are {days} days apart (limit {cfg['rapid_days']}).")
            evidence.append({"rule": "RAPID_TRANSFER", "transactions": [a["transaction_id"], b["transaction_id"]], "detail": f"{days} days between consecutive transfers."})
    # Rule 3: last buyer vs recorded holder
    holders = [(parse_date(r.get("record_date")) or date.min, r["recorded_party_label"]) for r in (records or [])
               if r.get("record_type") in ("deed", "khatian", "mutation") and r.get("recorded_party_label")]
    if holders:
        holder = max(holders)[1]
        if owner != holder and not conflicts:
            review.append(f"The last buyer ({owner}) differs from the holder named in the latest record ({holder}).")
            evidence.append({"rule": "HOLDER_MISMATCH", "detail": f"Last buyer {owner} vs recorded holder {holder}."})
    if not evidence:
        evidence.append({"rule": "SEQUENCE_OK", "transactions": [t["transaction_id"] for t in active],
                         "detail": "Each seller was the previous buyer and there are no overlapping claims."})
    if conflicts:
        return _result("conflicting_sales", title, CONFLICT, " ".join(conflicts), evidence, lim, now)
    if review:
        return _result("conflicting_sales", title, REVIEW, " ".join(review), evidence, lim, now)
    return _result("conflicting_sales", title, PASS, f"{len(active)} transaction(s) form a consistent chain.", evidence, lim, now)


# ----------------------------------------------------------------------------------------------- check 3
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


def check_document_integrity(documents, uploaded=None, now=None) -> dict:
    title = "Document integrity (SHA-256)"
    lim = ["A matching hash only shows the file equals the copy whose hash was stored. It does not show the original was authentic, who issued it, "
           "that any signature is valid, or that it has legal effect.",
           "No government signature or seal is verified; all documents here are synthetic fixtures."]
    docs = list(documents or [])
    uploaded = uploaded or {}
    if not docs:
        return _result("document_integrity", title, UNAVAILABLE, "No documents are attached to this parcel.", [], lim, now)
    evidence, counts = [], {"match": 0, "mismatch": 0, "unchecked": 0}
    for d in docs:
        content = uploaded.get(d["document_id"], d.get("content"))
        row = {"document_id": d["document_id"], "record_id": d.get("record_id"), "file": d.get("filename"),
               "expected_sha256": d.get("expected_sha256"), "source": "uploaded file" if d["document_id"] in uploaded else "bundled fixture"}
        exp = d.get("expected_sha256")
        if not exp:
            row.update(result="no stored hash", detail="No hash was recorded for this document, so it cannot be checked.")
            counts["unchecked"] += 1
        elif not _HEX.match(exp):
            row.update(result="invalid stored hash", detail="The stored hash is not a valid SHA-256 value.")
            counts["unchecked"] += 1
        elif content is None:
            row.update(result="no file", detail="No file was supplied to hash.")
            counts["unchecked"] += 1
        else:
            got = sha256_hex(content)
            row.update(computed_sha256=got, size_bytes=len(content))
            if got.lower() == exp.lower():
                row.update(result="match", detail="Computed hash equals the stored hash.")
                counts["match"] += 1
            else:
                row.update(result="MISMATCH", detail="Computed hash differs from the stored hash.")
                counts["mismatch"] += 1
        evidence.append(row)
    if counts["mismatch"]:
        return _result("document_integrity", title, CONFLICT, f"{counts['mismatch']} document(s) do not match their stored hash.", evidence, lim, now)
    if counts["match"] and counts["unchecked"]:
        return _result("document_integrity", title, REVIEW, f"{counts['match']} matched; {counts['unchecked']} could not be checked.", evidence, lim, now)
    if counts["match"]:
        return _result("document_integrity", title, PASS, f"All {counts['match']} checked document(s) match their stored hash.", evidence, lim, now)
    return _result("document_integrity", title, UNAVAILABLE, "No document could be checked.", evidence, lim, now)




def _as_of(settings):
    return parse_date(settings.get("as_of_date")) or date.today()


# ----------------------------------------------------------------------------------------------- check: survey chain
def check_survey_chain(records, settings=None, now=None) -> dict:
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    title = "Survey generations (CS -> SA -> RS -> BS)"
    lim = ["Compares only the synthetic survey references supplied.", "Each later survey must name the earlier survey's dag (prev_dag_ref); renumbering is allowed only if it is declared.",
           f"Area drift between neighbouring generations above {cfg['survey_area_drift_pct']}% needs review."]
    gens = {}
    for r in records or []:
        g = (r.get("survey_gen") or "").upper()
        if g in SURVEY_ORDER:
            gens[g] = r
    if len(gens) < 2:
        return _result("survey_chain", title, UNAVAILABLE, f"Only {len(gens)} survey generation(s) recorded; at least 2 are needed.", [{"generations": sorted(gens)}], lim, now)
    present = [g for g in SURVEY_ORDER if g in gens]
    conflicts, review, evidence = [], [], []
    for g in cfg["expected_survey_generations"]:
        if g not in gens:
            review.append(f"The {g} survey record is missing.")
            evidence.append({"generation": g, "result": "missing"})
    for a, b in zip(present, present[1:]):
        ra, rb = gens[a], gens[b]
        prev, dag = normalize_ref(rb.get("prev_dag_ref")), normalize_ref(ra.get("dag_ref"))
        row = {"link": f"{a} -> {b}", f"{a} dag": ra.get("dag_ref"), f"{b} declares previous dag": rb.get("prev_dag_ref")}
        if prev is None:
            review.append(f"{b} does not declare which {a} dag it came from.")
            row["result"] = "no lineage declared"
        elif prev != dag:
            conflicts.append(f"{b} says it came from dag {rb.get('prev_dag_ref')}, but the {a} record is dag {ra.get('dag_ref')}.")
            row["result"] = "LINEAGE BREAK"
        else:
            row["result"] = "ok"
        try:
            xa, xb = to_sqm(ra["recorded_area"], ra["area_unit"]), to_sqm(rb["recorded_area"], rb["area_unit"])
            drift = abs(xb - xa) / max(xa, xb) * 100
            row["area_drift_pct"] = round(drift, 1)
            if drift > cfg["survey_area_drift_pct"]:
                review.append(f"Area changed by {drift:.1f}% between {a} and {b}.")
        except (KeyError, TypeError, ValueError):
            review.append(f"Area could not be compared between {a} and {b}.")
        evidence.append(row)
    if conflicts:
        return _result("survey_chain", title, CONFLICT, " ".join(conflicts), evidence, lim, now)
    if review:
        return _result("survey_chain", title, REVIEW, " ".join(review), evidence, lim, now)
    return _result("survey_chain", title, PASS, f"{len(present)} survey generations link correctly.", evidence, lim, now)


# ----------------------------------------------------------------------------------------------- check: registration vs mutation
def check_registration_mutation(records, settings=None, now=None) -> dict:
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    title = "Registration (sub-registry) vs mutation (AC Land)"
    asof = _as_of(cfg)
    lim = ["Registration and mutation are held by different offices; this compares only the synthetic copies of both.",
           f"The {cfg['mutation_deadline_days']}-day deadline is an illustrative setting, not a statement of the legal time limit.",
           "A late mutation is shown as evidence but not flagged; a missing one after the deadline is flagged."]
    deeds = [r for r in records or [] if r.get("record_type") == "deed" and parse_date(r.get("record_date"))]
    muts = [r for r in records or [] if r.get("record_type") == "mutation"]
    if not deeds:
        return _result("registration_mutation", title, UNAVAILABLE, "No registered deed with a readable date was found.", [], lim, now)
    deed = max(deeds, key=lambda r: parse_date(r["record_date"]))
    dd = parse_date(deed["record_date"])
    ev = [{"record": deed["record_id"], "type": "deed (registration)", "date": deed["record_date"], "party": deed.get("recorded_party_label")}]
    if not muts:
        days = (asof - dd).days
        ev.append({"result": "no mutation", "days_since_registration": days, "deadline_days": cfg["mutation_deadline_days"], "as_of": asof.isoformat()})
        if days > cfg["mutation_deadline_days"]:
            return _result("registration_mutation", title, REVIEW, f"No mutation is recorded {days} days after registration (deadline setting {cfg['mutation_deadline_days']} days).", ev, lim, now)
        return _result("registration_mutation", title, PASS, f"No mutation yet, but only {days} days have passed (within the {cfg['mutation_deadline_days']}-day setting).", ev, lim, now)
    mut = max(muts, key=lambda r: parse_date(r.get("record_date")) or date.min)
    md = parse_date(mut.get("record_date"))
    ev.append({"record": mut["record_id"], "type": "mutation (AC Land)", "date": mut.get("record_date"), "party": mut.get("recorded_party_label")})
    pd_, pm = deed.get("recorded_party_label"), mut.get("recorded_party_label")
    if pd_ and pm and pd_ != pm:
        ev.append({"result": "PARTY MISMATCH", "detail": f"Deed names {pd_}; mutation names {pm}."})
        return _result("registration_mutation", title, CONFLICT, f"The mutation names {pm} but the registered deed names {pd_}.", ev, lim, now)
    if md and md < dd:
        ev.append({"result": "ORDER", "detail": "The mutation is dated before the deed."})
        return _result("registration_mutation", title, REVIEW, "The mutation is dated before the deed it should follow.", ev, lim, now)
    if not pd_ or not pm:
        ev.append({"result": "party not stated"})
        return _result("registration_mutation", title, REVIEW, "A party label is missing on the deed or the mutation, so they cannot be matched.", ev, lim, now)
    late = md and (md - dd).days > cfg["mutation_deadline_days"]
    ev.append({"result": "match", "days_to_mutation": (md - dd).days if md else None, "note": "mutation was later than the deadline setting (shown, not flagged)" if late else ""})
    return _result("registration_mutation", title, PASS, "The mutation matches the registered deed.", ev, lim, now)


# ----------------------------------------------------------------------------------------------- check: pending cases / khas
def _coverage(coverage, key):
    return bool((coverage or {}).get(key))


def check_pending_cases(cases, coverage=None, now=None) -> dict:
    title = "Pending cases (synthetic case register)"
    lim = ["Reads only a SYNTHETIC case register made by the team; the real court systems are not queried.", "Absence of a record is not proof that no case exists."]
    if not _coverage(coverage, "case_register"):
        return _result("pending_cases", title, UNAVAILABLE, "The case register is not covered for this parcel.", [], lim, now)
    rows = list(cases or [])
    pending = [c for c in rows if (c.get("status") or "").lower() == "pending"]
    ev = [{"case_id": c["case_id"], "type": c.get("case_type"), "court": c.get("court_label"), "status": c.get("status"), "filed": c.get("filed_date"),
           "restricts_transfer": bool(c.get("restricts_transfer"))} for c in rows]
    if any(c.get("restricts_transfer") for c in pending):
        return _result("pending_cases", title, CONFLICT, "A pending case that restricts transfer is recorded.", ev, lim, now)
    if pending:
        return _result("pending_cases", title, REVIEW, f"{len(pending)} pending case(s) recorded that do not restrict transfer by themselves.", ev, lim, now)
    return _result("pending_cases", title, PASS, "No pending case is recorded." + (f" ({len(rows)} closed case(s) listed.)" if rows else ""), ev or [{"result": "no cases on record"}], lim, now)


def check_khas_acquisition(entries, coverage=None, now=None) -> dict:
    title = "Khas / vested / acquisition status (synthetic register)"
    lim = ["Reads only a SYNTHETIC register made by the team; real khas, vested-property and acquisition records are not queried.", "Absence of a record is not proof of free title."]
    if not _coverage(coverage, "khas_register"):
        return _result("khas_acquisition", title, UNAVAILABLE, "The khas/acquisition register is not covered for this parcel.", [], lim, now)
    rows = list(entries or [])
    ev = [{"entry_id": e["entry_id"], "type": e.get("status_type"), "authority": e.get("authority_label"), "notice": e.get("notice_ref"), "date": e.get("notice_date"),
           "status": e.get("status")} for e in rows]
    live = [e for e in rows if (e.get("status") or "").lower() != "released"]
    block = [e for e in live if e.get("status_type") in ("khas", "vested") or (e.get("status_type") == "acquisition" and (e.get("status") or "").lower() in ("notified", "completed"))]
    if block:
        return _result("khas_acquisition", title, CONFLICT, f"Recorded as {block[0]['status_type']} ({block[0].get('status')}).", ev, lim, now)
    if live:
        return _result("khas_acquisition", title, REVIEW, "An acquisition is recorded as proposed.", ev, lim, now)
    return _result("khas_acquisition", title, PASS, "No khas, vested or acquisition entry is recorded." + (" (A released entry is listed.)" if rows else ""), ev or [{"result": "no entries on record"}], lim, now)


# ----------------------------------------------------------------------------------------------- check: authenticity (simulated)
def check_document_authenticity(documents, ledger=None, issuer_keys=None, uploaded=None, now=None) -> dict:
    title = "Document authenticity (simulated issuer signature + ledger)"
    lim = ["The issuer is SIMULATED by the project team (a public demo key). This is not a government signature and no real document is verified.",
           "A valid signature shows the file is the one the simulated issuer signed; it does not show the content is true or legally effective.",
           "The ledger is append-only by design here; a real deployment would need independent operators."]
    docs = list(documents or [])
    uploaded = uploaded or {}
    if not docs:
        return _result("document_authenticity", title, UNAVAILABLE, "No documents are attached to this parcel.", [], lim, now)
    chain = verify_chain(ledger or [])
    by_doc = {e["doc_id"]: e for e in (ledger or [])}
    keys = issuer_keys or {}
    ev, counts = [], {"valid": 0, "invalid": 0, "unchecked": 0}
    for d in docs:
        content = uploaded.get(d["document_id"], d.get("content"))
        row = {"document_id": d["document_id"], "signer": d.get("signer_kid")}
        if not d.get("signature") or not d.get("expected_sha256"):
            row.update(result="no signature recorded"); counts["unchecked"] += 1
        elif content is None:
            row.update(result="no file"); counts["unchecked"] += 1
        else:
            got, problems = sha256_hex(content), []
            pub = keys.get(d.get("signer_kid"))
            if pub is None:
                problems.append("issuer key not recognised")
            elif not verify_signature(pub, got, d["signature"]):
                problems.append("the signature does not verify for this file")
            e = by_doc.get(d["document_id"])
            if e is None:
                problems.append("no ledger entry for this document")
            elif e["sha256"] != d["expected_sha256"]:
                problems.append("the ledger hash differs from the stored hash")
            row.update(computed_sha256=got, ledger_entry=e["entry_index"] if e else None)
            if problems:
                row.update(result="INVALID", problems="; ".join(problems)); counts["invalid"] += 1
            else:
                row.update(result="valid"); counts["valid"] += 1
        ev.append(row)
    ev.append({"ledger_chain": "intact" if chain["ok"] else "BROKEN", "entries_checked": chain["checked"], "detail": chain["reason"]})
    if not chain["ok"]:
        return _result("document_authenticity", title, CONFLICT, f"The ledger is broken at entry {chain['bad_index']}: {chain['reason']}.", ev, lim, now)
    if counts["invalid"]:
        return _result("document_authenticity", title, CONFLICT, f"{counts['invalid']} document(s) failed signature or ledger verification.", ev, lim, now)
    if counts["valid"] and counts["unchecked"]:
        return _result("document_authenticity", title, REVIEW, f"{counts['valid']} verified; {counts['unchecked']} could not be checked.", ev, lim, now)
    if counts["valid"]:
        return _result("document_authenticity", title, PASS, f"All {counts['valid']} signed document(s) verify and appear in an intact ledger.", ev, lim, now)
    return _result("document_authenticity", title, UNAVAILABLE, "No signed document could be checked.", ev, lim, now)


# ----------------------------------------------------------------------------------------------- check: boundary overlap
def check_boundary_overlap(points, others, settings=None, now=None) -> dict:
    """Does this parcel's boundary overlap any other registered parcel? (Python/Shapely equivalent of a PostGIS ST_Intersects check.)"""
    from src.geo_tools import GeometryError, overlap_sqm, polygon_metrics
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    title = "Boundary overlap with other registered parcels"
    lim = ["Compares only the synthetic parcels in this prototype's register; real neighbouring parcels are not known.",
           f"Overlaps smaller than {cfg['overlap_tolerance_sqm']} m² or {cfg['overlap_tolerance_pct']}% of the smaller parcel are treated as drawing noise.",
           "Overlap area is measured in an equal-area projection. Parcels that only touch along an edge do not overlap."]
    try:
        own = polygon_metrics(points)["area_sqm"]
    except (GeometryError, TypeError):
        return _result("boundary_overlap", title, UNAVAILABLE, "This parcel has no valid boundary to compare.", [], lim, now)
    evidence, conflicts, skipped = [], [], 0
    for o in others or []:
        try:
            shared = overlap_sqm(points, o["points"])
            other = polygon_metrics(o["points"])["area_sqm"]
        except (GeometryError, TypeError, KeyError):
            skipped += 1
            continue
        if shared <= 0:
            continue
        allowed = max(cfg["overlap_tolerance_sqm"], min(own, other) * cfg["overlap_tolerance_pct"] / 100)
        row = {"other_parcel": o["parcel_id"], "shared_sqm": round(shared, 1), "share_of_this_parcel_pct": round(100 * shared / own, 1),
               "share_of_other_parcel_pct": round(100 * shared / other, 1), "allowed_sqm": round(allowed, 1)}
        if shared > allowed:
            row["result"] = "OVERLAP"
            conflicts.append(f"{shared:.0f} m² ({100 * shared / own:.0f}% of this parcel) is also inside {o['parcel_id']}.")
        else:
            row["result"] = "within tolerance"
        evidence.append(row)
    checked = len(others or []) - skipped
    if not evidence:
        evidence.append({"result": "no overlap", "parcels_compared": checked})
    if conflicts:
        return _result("boundary_overlap", title, CONFLICT, " ".join(conflicts), evidence, lim, now)
    if skipped:
        return _result("boundary_overlap", title, REVIEW, f"{skipped} neighbouring boundary(ies) could not be read; {checked} compared without overlap.", evidence, lim, now)
    return _result("boundary_overlap", title, PASS, f"No overlap with any of the {checked} other registered parcels.", evidence, lim, now)


# ----------------------------------------------------------------------------------------------- check: mortgage / lien / attachment
def check_encumbrance(entries, coverage=None, now=None) -> dict:
    title = "Mortgage, lien or attachment (synthetic encumbrance register)"
    lim = ["Reads only a SYNTHETIC register made by the team; real bank or court records are not queried.",
           "Absence of an entry is meaningful only where the register covers the parcel.",
           "Whether a mortgaged parcel can be sold depends on the loan terms and the law; this check only reports what is recorded."]
    if not _coverage(coverage, "encumbrance_register"):
        return _result("encumbrance", title, UNAVAILABLE, "The encumbrance register is not covered for this parcel.", [], lim, now)
    rows = list(entries or [])
    ev = [{"entry_id": e["entry_id"], "kind": e.get("kind"), "holder": e.get("holder_label"), "status": e.get("status"),
           "registered": e.get("registered_date"), "released": e.get("released_date") or "-"} for e in rows]
    active = [e for e in rows if (e.get("status") or "").lower() == "active"]
    attach = [e for e in active if e.get("kind") == "attachment"]
    if attach:
        return _result("encumbrance", title, CONFLICT, f"A court attachment ({attach[0]['entry_id']}) is in force.", ev, lim, now)
    if active:
        e = active[0]
        return _result("encumbrance", title, REVIEW, f"Active {e.get('kind')} held by {e.get('holder_label')} since {e.get('registered_date')}.", ev, lim, now)
    return _result("encumbrance", title, PASS, "No active mortgage, lien or attachment is recorded." + (f" ({len(rows)} released entry(ies) listed.)" if rows else ""),
                   ev or [{"result": "no entries on record"}], lim, now)


# ----------------------------------------------------------------------------------------------- citizen summary (traffic light)
CHECK_ORDER = ["record_consistency", "registration_mutation", "survey_chain", "boundary_overlap", "conflicting_sales", "document_integrity",
               "document_authenticity", "pending_cases", "khas_acquisition", "encumbrance"]
LIGHTS = {
    "red": ("Serious problem found: do not pay or sign without legal advice.", "গুরুতর সমস্যা পাওয়া গেছে: আইনি পরামর্শ ছাড়া টাকা দেবেন না বা কিছুতে সই করবেন না।"),
    "blue": ("Government / khas or acquisition entry: the land may not be freely transferable.", "সরকারি / খাস বা অধিগ্রহণের তথ্য আছে: জমিটি স্বাধীনভাবে হস্তান্তরযোগ্য না-ও হতে পারে।"),
    "amber": ("Needs checking before you buy.", "কেনার আগে যাচাই করা দরকার।"),
    "green": ("No problem found in the checked (synthetic) records. This is not proof of clean title.", "যাচাই করা (কাল্পনিক) রেকর্ডে কোনো সমস্যা পাওয়া যায়নি। এটি পরিষ্কার মালিকানার প্রমাণ নয়।"),
    "grey": ("Not enough information to say anything.", "কিছু বলার মতো যথেষ্ট তথ্য নেই।"),
}


def safety_summary(run) -> dict:
    """Citizen-facing traffic light derived ONLY from the run's own statuses (no extra judgement).
    red = any conflict except khas/acquisition; blue = khas/acquisition conflict (and nothing else red); amber = review or partly unavailable;
    green = every check passed; grey = every check unavailable."""
    res = {r["check_id"]: r for r in run["results"]}
    conflicts = [r for r in run["results"] if r["status"] == CONFLICT]
    reviews = [r for r in run["results"] if r["status"] == REVIEW]
    missing = [r for r in run["results"] if r["status"] in (UNAVAILABLE, NOT_RUN)]
    if any(r["check_id"] != "khas_acquisition" for r in conflicts):
        level = "red"
    elif conflicts:
        level = "blue"
    elif reviews or (missing and len(missing) < len(run["results"])):
        level = "amber"
    elif missing:
        level = "grey"
    else:
        level = "green"
    ordered = sorted(conflicts + reviews + missing, key=lambda r: (["CONFLICT_FOUND", "REVIEW_REQUIRED", "UNAVAILABLE", "NOT_RUN"].index(r["status"]),
                                                                   CHECK_ORDER.index(r["check_id"]) if r["check_id"] in CHECK_ORDER else 99))
    reasons = [{"check_id": r["check_id"], "title": r["title"], "status": r["status"], "summary": r["summary"]} for r in ordered]
    tags = []
    if res.get("encumbrance", {}).get("status") == REVIEW:
        tags.append("mortgaged")
    if res.get("pending_cases", {}).get("status") in (CONFLICT, REVIEW):
        tags.append("case pending")
    if res.get("boundary_overlap", {}).get("status") == CONFLICT:
        tags.append("boundary overlap")
    if res.get("conflicting_sales", {}).get("status") == CONFLICT:
        tags.append("conflicting sale")
    return {"parcel_id": run["parcel_id"], "level": level, "label_en": LIGHTS[level][0], "label_bn": LIGHTS[level][1], "reasons": reasons, "tags": tags,
            "counts": {s: sum(1 for r in run["results"] if r["status"] == s) for s in STATUSES}}


def overall_status(results) -> str:
    """Preserves uncertainty: PASS only if every check ran and passed."""
    st = [r["status"] for r in results]
    if not st:
        return NOT_RUN
    if CONFLICT in st:
        return CONFLICT
    if all(s == UNAVAILABLE for s in st):
        return UNAVAILABLE
    if all(s == PASS for s in st):
        return PASS
    return REVIEW


def run_verification(parcel_id, records, transactions, documents, settings=None, uploaded=None, now=None, context=None) -> dict:
    """Run the checks. Without `context` only the original three run (record consistency, conflicting sales, document integrity).
    With `context` = vdb.verification_context(...) all ten run, in CHECK_ORDER."""
    cfg = {**DEFAULT_SETTINGS, **(settings or {})}
    ts = now or now_iso()
    if context is None:
        results = [check_record_consistency(records, cfg, ts), check_conflicting_sales(transactions, records, cfg, ts), check_document_integrity(documents, uploaded, ts)]
        version = "1.0"
    else:
        results = [check_record_consistency(records, cfg, ts), check_registration_mutation(records, cfg, ts), check_survey_chain(records, cfg, ts),
                   check_boundary_overlap(context.get("points"), context.get("other_parcels"), cfg, ts),
                   check_conflicting_sales(transactions, records, cfg, ts), check_document_integrity(documents, uploaded, ts),
                   check_document_authenticity(documents, context.get("ledger"), context.get("issuer_keys"), uploaded, ts),
                   check_pending_cases(context.get("cases"), context.get("coverage"), ts), check_khas_acquisition(context.get("khas"), context.get("coverage"), ts),
                   check_encumbrance(context.get("encumbrances"), context.get("coverage"), ts)]
        version = ENGINE_VERSION
    return {"parcel_id": parcel_id, "created_at": ts, "engine_version": version, "settings": cfg,
            "uploaded_documents": sorted((uploaded or {}).keys()), "overall_status": overall_status(results), "results": results}
