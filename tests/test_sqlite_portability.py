import sqlite3

import pytest


def test_sqlite_without_extension_loading_keeps_readonly_guards(db_path, monkeypatch):
    from pl_capital import database

    original = sqlite3.connect

    class WithoutExtensions(sqlite3.Connection):
        @property
        def enable_load_extension(self):
            raise AttributeError("SQLite compiled without extension loading")

    def connect(*args, **kwargs):
        return original(*args, **kwargs, factory=WithoutExtensions)

    monkeypatch.setattr(database.sqlite3, "connect", connect)
    with database.readonly(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 13
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT load_extension('untrusted')")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM holdings")
