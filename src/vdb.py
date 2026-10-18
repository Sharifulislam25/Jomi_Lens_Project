"""SQLite data layer for JomiLens Verify. All SQL is parameterised. Everything stored here is SYNTHETIC.
Designed so the same tables/columns can later move to PostgreSQL/PostGIS (geometry is stored as GeoJSON text)."""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "verify" / "verify.sqlite"
DOC_DIR = ROOT / "data" / "verify" / "docs"
SCHEMA_VERSION = 5
BOUNDARY_TYPES = ("official_verified", "synthetic_demo", "user_drawn", "approximate_feature", "unknown")

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels(
  parcel_id TEXT PRIMARY KEY, geometry_geojson TEXT NOT NULL, area_calculated REAL, area_unit TEXT DEFAULT 'sqm',
  perimeter_calculated REAL, boundary_type TEXT NOT NULL CHECK (boundary_type IN ('official_verified','synthetic_demo','user_drawn','approximate_feature','unknown')),
  boundary_source TEXT, boundary_source_date TEXT, administrative_area TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT, scenario_code TEXT, scenario_title TEXT, scenario_description TEXT, expected_overall TEXT,
  mouza TEXT, asking_price_bdt INTEGER, created_by TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS land_records(
  record_id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id),
  record_type TEXT NOT NULL CHECK (record_type IN ('deed','khatian','mutation','survey reference','transaction','other')),
  record_reference TEXT, dag_ref TEXT, khatian_ref TEXT, recorded_area REAL, area_unit TEXT,
  recorded_party_label TEXT, record_status TEXT, record_date TEXT, source_description TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1, notes TEXT,
  survey_gen TEXT, prev_dag_ref TEXT, issuing_office TEXT);
CREATE TABLE IF NOT EXISTS transactions(
  transaction_id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), source_record_id TEXT REFERENCES land_records(record_id),
  buyer_demo_id TEXT, seller_demo_id TEXT, transaction_date TEXT, transaction_status TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS document_hashes(
  document_id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES land_records(record_id), sha256_hash TEXT, hash_created_at TEXT,
  document_source_status TEXT, fixture_file TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1, signature TEXT, signer_kid TEXT);
CREATE TABLE IF NOT EXISTS imagery_observations(
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), provider TEXT,
  imagery_item_id TEXT, release_date TEXT, capture_date TEXT, resolution_m REAL, quality_notes TEXT, attribution TEXT, retrieved_at TEXT);
CREATE TABLE IF NOT EXISTS classifications(
  classification_id INTEGER PRIMARY KEY AUTOINCREMENT, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), class_label TEXT NOT NULL,
  method TEXT NOT NULL CHECK (method IN ('manual','rules','model')), confidence REAL, model_version TEXT, evidence_summary TEXT,
  review_status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS verification_runs(
  run_id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), created_at TEXT, overall_status TEXT,
  settings_json TEXT, results_json TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1, user_id INTEGER, username TEXT);
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL CHECK (role IN ('user','admin')),
  password_hash TEXT NOT NULL, display_name TEXT, active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT, created_by TEXT, last_login_at TEXT);
CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, door TEXT, ok INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT, role TEXT, action TEXT NOT NULL, target TEXT, detail_json TEXT);
CREATE TABLE IF NOT EXISTS problem_reports(
  report_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id), parcel_id TEXT, category TEXT NOT NULL, description TEXT NOT NULL,
  lat REAL, lon REAL, status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_review','resolved','rejected')), created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages(
  message_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_user_id INTEGER NOT NULL REFERENCES users(user_id), sender_id INTEGER NOT NULL REFERENCES users(user_id),
  sender_role TEXT NOT NULL, report_id TEXT, body TEXT NOT NULL, created_at TEXT, read_by_user INTEGER NOT NULL DEFAULT 0, read_by_admin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS notifications(
  notification_id INTEGER PRIMARY KEY AUTOINCREMENT, recipient_id INTEGER REFERENCES users(user_id), title TEXT NOT NULL, body TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('info','warning','important')), sender TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS notification_reads(notification_id INTEGER NOT NULL, user_id INTEGER NOT NULL, read_at TEXT, PRIMARY KEY (notification_id, user_id));
CREATE INDEX IF NOT EXISTS ix_msg_thread ON messages(thread_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);
CREATE TABLE IF NOT EXISTS pending_cases(
  case_id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), case_type TEXT, court_label TEXT, status TEXT,
  filed_date TEXT, restricts_transfer INTEGER DEFAULT 0, notes TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS khas_acquisition(
  entry_id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), status_type TEXT CHECK (status_type IN ('khas','vested','acquisition')),
  authority_label TEXT, notice_ref TEXT, notice_date TEXT, status TEXT, notes TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS registry_coverage(
  parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), registry TEXT NOT NULL, covered INTEGER NOT NULL, note TEXT, PRIMARY KEY (parcel_id, registry));
CREATE TABLE IF NOT EXISTS ledger(
  entry_index INTEGER PRIMARY KEY, parcel_id TEXT, ts TEXT, doc_id TEXT, sha256 TEXT, signature TEXT, signer_kid TEXT, prev_hash TEXT, entry_hash TEXT);
CREATE TABLE IF NOT EXISTS issuer_keys(kid TEXT PRIMARY KEY, public_key_hex TEXT, label TEXT, is_simulated INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS encumbrances(
  entry_id TEXT PRIMARY KEY, parcel_id TEXT NOT NULL REFERENCES parcels(parcel_id), kind TEXT CHECK (kind IN ('mortgage','lien','attachment')),
  holder_label TEXT, status TEXT, registered_date TEXT, released_date TEXT, notes TEXT, is_synthetic INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_rec_parcel ON land_records(parcel_id);
CREATE INDEX IF NOT EXISTS ix_tx_parcel ON transactions(parcel_id);
CREATE INDEX IF NOT EXISTS ix_run_parcel ON verification_runs(parcel_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(con) -> None:
    con.executescript(SCHEMA)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()


def ensure_db(path=None):
    """Create and seed the synthetic database if it does not exist yet. Returns the path."""
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():                       # an older schema holds only synthetic data: rebuild it instead of migrating
        with closing(connect(p)) as con:
            old = con.execute("PRAGMA user_version").fetchone()[0]
        if old != SCHEMA_VERSION:
            p.unlink()
    with closing(connect(p)) as con:
        init_db(con)
        n = con.execute("SELECT COUNT(*) FROM parcels").fetchone()[0]
    if n == 0:
        from src.verify_seed import seed
        seed(p)
    return p


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def list_parcels(con, synthetic_only=True, include_retired=False):
    q = "SELECT * FROM parcels WHERE 1=1" + (" AND is_synthetic = 1" if synthetic_only else "") + ("" if include_retired else " AND status = 'active'")
    return _rows(con.execute(q + " ORDER BY parcel_id"))


def get_parcel(con, parcel_id):
    r = con.execute("SELECT * FROM parcels WHERE parcel_id = ?", (parcel_id,)).fetchone()
    return dict(r) if r else None


def get_records(con, parcel_id):
    return _rows(con.execute("SELECT * FROM land_records WHERE parcel_id = ? ORDER BY record_date, record_id", (parcel_id,)))


def get_transactions(con, parcel_id):
    return _rows(con.execute("SELECT * FROM transactions WHERE parcel_id = ? ORDER BY transaction_date, transaction_id", (parcel_id,)))


def read_fixture(name):
    """Read a bundled fixture file safely (basename only, must live in DOC_DIR)."""
    if not name:
        return None
    p = (DOC_DIR / Path(name).name).resolve()
    if p.parent != DOC_DIR.resolve() or not p.is_file():
        return None
    return p.read_bytes()


def get_documents(con, parcel_id):
    rows = _rows(con.execute("SELECT d.*, r.record_reference, r.record_type FROM document_hashes d JOIN land_records r ON r.record_id = d.record_id "
                             "WHERE r.parcel_id = ? ORDER BY d.document_id", (parcel_id,)))
    return [{"document_id": r["document_id"], "record_id": r["record_id"], "record_type": r["record_type"], "filename": r["fixture_file"],
             "expected_sha256": r["sha256_hash"], "source_status": r["document_source_status"], "signature": r["signature"], "signer_kid": r["signer_kid"],
             "content": read_fixture(r["fixture_file"])} for r in rows]


def get_cases(con, parcel_id):
    return _rows(con.execute("SELECT * FROM pending_cases WHERE parcel_id = ? ORDER BY filed_date", (parcel_id,)))


def get_khas(con, parcel_id):
    return _rows(con.execute("SELECT * FROM khas_acquisition WHERE parcel_id = ? ORDER BY notice_date", (parcel_id,)))


def get_coverage(con, parcel_id) -> dict:
    return {r["registry"]: bool(r["covered"]) for r in con.execute("SELECT registry, covered FROM registry_coverage WHERE parcel_id = ?", (parcel_id,))}


def get_ledger(con, parcel_id=None):
    """Document ledger entries. Each parcel has its own hash chain, so one tampered chain cannot break another parcel's check."""
    if parcel_id is None:
        return _rows(con.execute("SELECT * FROM ledger ORDER BY entry_index"))
    return _rows(con.execute("SELECT * FROM ledger WHERE parcel_id = ? ORDER BY entry_index", (parcel_id,)))


def get_issuer_keys(con) -> dict:
    return {r["kid"]: r["public_key_hex"] for r in con.execute("SELECT kid, public_key_hex FROM issuer_keys")}


def get_encumbrances(con, parcel_id):
    return _rows(con.execute("SELECT * FROM encumbrances WHERE parcel_id = ? ORDER BY registered_date", (parcel_id,)))


def parcel_points(row) -> list:
    """[(lon, lat), ...] of a parcel row (closing vertex removed)."""
    return [tuple(p) for p in json.loads(row["geometry_geojson"])["coordinates"][0]][:-1]


def other_parcels(con, parcel_id):
    """Every OTHER registered parcel as {parcel_id, title, points}: used by the boundary-overlap check."""
    return [{"parcel_id": r["parcel_id"], "title": r["scenario_title"], "points": parcel_points(r)}
            for r in con.execute("SELECT parcel_id, scenario_title, geometry_geojson FROM parcels WHERE parcel_id != ? ORDER BY parcel_id", (parcel_id,))]


def find_by_reference(con, query, limit=30):
    """Parcels whose dag or khatian reference matches `query` after normalisation ('Dag No. 0125' == '125').
    Returns [{parcel_id, title, field, value, record_type, survey_gen}] (one row per matching record)."""
    from src.verification_engine import normalize_ref
    q = normalize_ref(query)
    if not q:
        return []
    out = []
    for r in con.execute("SELECT r.parcel_id, p.scenario_title, p.administrative_area, r.record_type, r.survey_gen, r.dag_ref, r.khatian_ref "
                         "FROM land_records r JOIN parcels p ON p.parcel_id = r.parcel_id ORDER BY r.parcel_id, r.record_id"):
        for field, value in (("dag", r["dag_ref"]), ("khatian", r["khatian_ref"])):
            if value and normalize_ref(value) == q:
                out.append({"parcel_id": r["parcel_id"], "title": r["scenario_title"], "area": r["administrative_area"], "field": field, "value": value,
                            "record_type": r["record_type"], "survey_gen": r["survey_gen"]})
    return out[:limit]


def verification_context(con, parcel_id) -> dict:
    """Everything the engine needs beyond records / transactions / documents."""
    row = get_parcel(con, parcel_id)
    return {"cases": get_cases(con, parcel_id), "khas": get_khas(con, parcel_id), "coverage": get_coverage(con, parcel_id),
            "ledger": get_ledger(con, parcel_id), "issuer_keys": get_issuer_keys(con), "encumbrances": get_encumbrances(con, parcel_id),
            "points": parcel_points(row) if row else None, "other_parcels": other_parcels(con, parcel_id)}


def get_classifications(con, parcel_id):
    return _rows(con.execute("SELECT * FROM classifications WHERE parcel_id = ? ORDER BY classification_id DESC", (parcel_id,)))


def get_imagery_observations(con, parcel_id):
    return _rows(con.execute("SELECT * FROM imagery_observations WHERE parcel_id = ? ORDER BY release_date", (parcel_id,)))


def save_run(con, parcel_id, run, is_synthetic=True, user=None) -> str:
    """Append a verification run (history is kept, never overwritten). Returns the run id. `user` = {user_id, username} of who ran it."""
    run_id = "RUN-" + uuid.uuid4().hex[:10].upper()
    con.execute("INSERT INTO verification_runs(run_id,parcel_id,created_at,overall_status,settings_json,results_json,is_synthetic,user_id,username) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, parcel_id, run["created_at"], run["overall_status"], json.dumps(run["settings"], sort_keys=True),
                 json.dumps({"results": run["results"], "engine_version": run.get("engine_version"),
                             "uploaded_documents": run.get("uploaded_documents", [])}), int(is_synthetic),
                 (user or {}).get("user_id"), (user or {}).get("username")))
    con.commit()
    return run_id


def list_runs(con, parcel_id, user_id=None):
    """Runs for a parcel. With user_id, only that user's runs (citizens never see each other's history)."""
    if user_id is None:
        return _rows(con.execute("SELECT run_id, created_at, overall_status, username FROM verification_runs WHERE parcel_id = ? ORDER BY created_at DESC", (parcel_id,)))
    return _rows(con.execute("SELECT run_id, created_at, overall_status FROM verification_runs WHERE parcel_id = ? AND user_id = ? ORDER BY created_at DESC",
                             (parcel_id, user_id)))


def runs_for_user(con, user_id):
    return _rows(con.execute("SELECT run_id, parcel_id, created_at, overall_status FROM verification_runs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)))


def all_runs(con, limit=2000):
    return _rows(con.execute("SELECT run_id, parcel_id, created_at, overall_status, username FROM verification_runs ORDER BY created_at DESC LIMIT ?", (limit,)))


def audit(con, actor, role, action, target=None, detail=None):
    """Append-only audit trail. Never pass passwords or personal data in `detail`."""
    con.execute("INSERT INTO audit_log(ts,actor,role,action,target,detail_json) VALUES (?,?,?,?,?,?)",
                (utcnow(), actor, role, action, None if target is None else str(target)[:120], json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)[:2000]))
    con.commit()


def get_run(con, run_id):
    r = con.execute("SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    payload = json.loads(d.pop("results_json"))
    d["settings"] = json.loads(d.pop("settings_json"))
    d.update(payload)
    return d


def save_imagery_observations(con, parcel_id, items):
    """items: [{provider, imagery_item_id, release_date, capture_date, resolution_m, quality_notes, attribution}]"""
    ts = utcnow()
    con.executemany("INSERT INTO imagery_observations(parcel_id,provider,imagery_item_id,release_date,capture_date,resolution_m,quality_notes,attribution,retrieved_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", [(parcel_id, i.get("provider"), i.get("imagery_item_id"), i.get("release_date"), i.get("capture_date"),
                                                    i.get("resolution_m"), i.get("quality_notes"), i.get("attribution"), ts) for i in items])
    con.commit()


def save_classification(con, parcel_id, c):
    con.execute("INSERT INTO classifications(parcel_id,class_label,method,confidence,model_version,evidence_summary,review_status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (parcel_id, c["class_label"], c["method"], c.get("confidence"), c.get("model_version"), c.get("evidence_summary"),
                 c.get("review_status", "unreviewed"), utcnow()))
    con.commit()


def counts(con) -> dict:
    out = {}
    for name, table in (("parcels", "parcels"), ("records", "land_records"), ("transactions", "transactions"), ("documents", "document_hashes"),
                        ("pending_cases", "pending_cases"), ("khas_entries", "khas_acquisition"), ("users", "users"), ("problem_reports", "problem_reports"),
                        ("messages", "messages"), ("notifications", "notifications"), ("audit_entries", "audit_log"), ("encumbrances", "encumbrances"), ("ledger_entries", "ledger"), ("imagery_observations", "imagery_observations"), ("classifications", "classifications"), ("runs", "verification_runs")):
        out[name] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]    # table names are fixed literals above
    return out
