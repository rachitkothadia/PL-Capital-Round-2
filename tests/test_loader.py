from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_atomic_idempotent(tmp_path):
    from pl_capital.database import initialize, readonly

    path = tmp_path / "snapshot.db"
    first = initialize(ROOT, path)
    assert first["counts"]["holdings"] == 95
    assert first["counts"]["portfolios"] == 13
    assert initialize(ROOT, path) == first
    import sqlite3

    with sqlite3.connect(path) as trusted:
        assert trusted.execute("PRAGMA foreign_key_check").fetchall() == []
    with readonly(path) as conn:
        with pytest.raises(Exception, match="not authorized|readonly|read-only"):
            conn.execute("DELETE FROM holdings")


def test_changed_inputs_require_explicit_rebuild(tmp_path):
    import shutil

    from pl_capital.database import initialize
    from pl_capital.errors import DataError

    root = tmp_path / "source"
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copy(ROOT / "database_schema.sql", root / "database_schema.sql")
    path = tmp_path / "portfolio.db"
    initialize(root, path)
    with (root / "data" / "holdings.csv").open("a") as f:
        f.write("\n")
    before = path.read_bytes()
    with pytest.raises(DataError, match="changed"):
        initialize(root, path)
    assert path.read_bytes() == before
    initialize(root, path, rebuild=True)


def test_bad_source_cannot_replace_database(tmp_path):
    import shutil

    from pl_capital.database import initialize
    from pl_capital.errors import DataError

    root = tmp_path / "source"
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copy(ROOT / "database_schema.sql", root / "database_schema.sql")
    path = tmp_path / "portfolio.db"
    initialize(root, path)
    before = path.read_bytes()
    with (root / "data" / "holdings.csv").open("a") as f:
        f.write("999,999,1,2,2,2020-01-01,0.1,4\n")
    with pytest.raises(DataError):
        initialize(root, path, rebuild=True)
    assert path.read_bytes() == before
