"""Rebuild the synthetic Verify database and its fixture documents:  python tools/seed_verify_db.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import vdb
from src.verify_seed import seed
if vdb.DB_PATH.exists():
    vdb.DB_PATH.unlink()
vdb.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
seed(vdb.DB_PATH)
print("Seeded", vdb.DB_PATH)
