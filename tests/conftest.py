import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import vdb  # noqa: E402
from src.verify_seed import seed  # noqa: E402


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    """A throw-away synthetic database + fixture documents (never touches the real data/verify folder)."""
    d = tmp_path_factory.mktemp("verify")
    db, docs = d / "t.sqlite", d / "docs"
    old_doc = vdb.DOC_DIR
    vdb.DOC_DIR = docs
    seed(db, doc_dir=docs)
    yield db
    vdb.DOC_DIR = old_doc


@pytest.fixture()
def con(seeded):
    c = vdb.connect(seeded)
    yield c
    c.close()


@pytest.fixture()
def fresh(seeded, tmp_path):
    """A private copy of the seeded database for tests that write (accounts, reports, edits)."""
    import shutil
    db = tmp_path / "w.sqlite"
    shutil.copy(seeded, db)
    c = vdb.connect(db)
    yield c
    c.close()
