import json
import sqlite3
from contextlib import closing, contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

import pl_capital.database as database
import pl_capital.sql_tool as sql_tool
from pl_capital.errors import DataError, QueryError
from pl_capital.exposure import calculate

ROOT = Path(__file__).resolve().parents[1]


def capture_connections(monkeypatch):
    original = sqlite3.connect
    captured = []

    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        captured.append(conn)
        return conn

    monkeypatch.setattr(database.sqlite3, "connect", connect)
    return captured


def assert_closed(connections):
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def test_import_closes_sqlite_before_atomic_rename(monkeypatch, tmp_path):
    connections = capture_connections(monkeypatch)
    original = database.os.replace

    def replace(source, target):
        assert_closed(connections)
        return original(source, target)

    monkeypatch.setattr(database.os, "replace", replace)
    try:
        database.initialize(ROOT, tmp_path / "snapshot.db")
    finally:
        for conn in connections:
            conn.close()


def test_failed_import_closes_connections_and_removes_temporary_file(monkeypatch, tmp_path):
    import shutil

    source = tmp_path / "source"
    shutil.copytree(ROOT / "data", source / "data")
    shutil.copy(ROOT / "database_schema.sql", source / "database_schema.sql")
    with (source / "data" / "holdings.csv").open("a") as stream:
        stream.write("999,999,1,2,2,2020-01-01,0.1,4\n")
    connections = capture_connections(monkeypatch)
    try:
        with pytest.raises(DataError):
            database.initialize(source, tmp_path / "snapshot.db")
        assert_closed(connections)
        assert list(tmp_path.glob("import-*.db")) == []
    finally:
        for conn in connections:
            conn.close()


def test_existing_manifest_and_introspection_connections_are_closed(db_path, monkeypatch):
    connections = capture_connections(monkeypatch)
    try:
        database.initialize(ROOT, db_path)
        database.schema_context(db_path)
        assert_closed(connections)
    finally:
        for conn in connections:
            conn.close()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: {},
        lambda manifest: [],
        lambda manifest: None,
        lambda manifest: dict(manifest, fingerprint=13),
        lambda manifest: dict(manifest, fingerprint="not-a-sha256"),
        lambda manifest: dict(manifest, counts={}),
        lambda manifest: dict(manifest, counts={**manifest["counts"], "holdings": "95"}),
        lambda manifest: dict(manifest, counts={**manifest["counts"], "holdings": True}),
        lambda manifest: dict(manifest, counts={**manifest["counts"], "holdings": -1}),
    ],
)
def test_invalid_manifest_is_a_safe_recoverable_error(db_path, mutation):
    with closing(sqlite3.connect(db_path)) as conn, conn:
        original = json.loads(conn.execute("SELECT manifest FROM _dataset_meta").fetchone()[0])
        conn.execute("UPDATE _dataset_meta SET manifest=?", (json.dumps(mutation(original)),))
    with pytest.raises(DataError, match="invalid|rebuild"):
        database.initialize(ROOT, db_path)
    database.initialize(ROOT, db_path, rebuild=True)


def test_cumulative_output_budget_stops_fetching_early(db_path, monkeypatch):
    observed = {"rows": 0}
    readonly = sql_tool.readonly

    class Cursor:
        def __init__(self, cursor):
            self.cursor = cursor
            self.description = cursor.description

        def fetchone(self):
            row = self.cursor.fetchone()
            observed["rows"] += row is not None
            return row

        def fetchmany(self, count):
            rows = self.cursor.fetchmany(count)
            observed["rows"] += len(rows)
            return rows

    class Connection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, *args):
            return Cursor(self.conn.execute(*args))

    @contextmanager
    def bounded_reader(*args, **kwargs):
        with readonly(*args, **kwargs) as conn:
            yield Connection(conn)

    monkeypatch.setattr(sql_tool, "readonly", bounded_reader)
    expression = "'a'"
    for _ in range(17):
        expression = f"replace({expression},'a','aa')"
    with pytest.raises(QueryError, match="output|size|budget"):
        sql_tool.execute(db_path, f"SELECT {expression} FROM historical_prices", {}, max_rows=20)
    assert observed["rows"] <= 2


def test_sqlite_cell_budget_rejects_large_derived_values(db_path):
    expression = "'a'"
    for _ in range(18):
        expression = f"replace({expression},'a','aa')"
    with pytest.raises(QueryError, match="too big|size|budget"):
        sql_tool.execute(db_path, "SELECT " + expression, {})


def test_output_budget_counts_utf8_bytes(db_path):
    expression = ":value"
    for _ in range(6):
        expression = f"replace({expression},'é','éé')"
    with pytest.raises(QueryError, match="output|size|budget"):
        sql_tool.execute(
            db_path, f"SELECT {expression} FROM historical_prices LIMIT 2", {"value": "é" * 1000}
        )


@pytest.mark.parametrize("weight", [1.000001, 1e20, 1e308])
def test_weights_outside_fraction_budget_are_diagnosed(db_path, weight):
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("UPDATE holdings SET current_weight=? WHERE holding_id=1", (weight,))
    with pytest.raises(DataError, match="weight|fraction"):
        calculate(db_path, "Growth Equity Fund")


def test_subnormal_positive_weight_has_safe_normalization(db_path):
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("UPDATE holdings SET current_weight=0 WHERE portfolio_id=3")
        conn.execute(
            "UPDATE holdings SET current_weight=? WHERE holding_id=(SELECT MIN(holding_id) FROM holdings WHERE portfolio_id=3)",
            (5e-324,),
        )
    result = calculate(db_path, "Tech Innovation Fund")
    assert result.status == "ok"
    assert Decimal(result.equity_weight_total) > 0
    assert result.sectors[0].equity_normalized_pct == 100
    assert result.sectors[0].whole_portfolio_pct == 0  # Explicit six-place display rounding.
