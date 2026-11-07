import json
import sqlite3

import pytest

from pl_capital.database import EXPECTED_COUNTS, diagnostics, readonly, schema_context


def test_counts_types_coverage_and_weight_gap(db_path):
    report = diagnostics(db_path)
    assert report["counts"] == EXPECTED_COUNTS
    assert report["portfolio_coverage"] == {"portfolio_performance": 4, "risk_metrics": 4}
    gaps = [r for r in report["portfolio_weights"] if r["weight_total"] != 1]
    assert [(r["portfolio_name"], r["weight_total"]) for r in gaps] == [
        ("Total Stock Market Index Fund", 0.98)
    ]
    with readonly(db_path) as conn:
        assert dict(
            conn.execute("SELECT asset_type,COUNT(*) FROM securities GROUP BY asset_type")
        ) == {"Bond": 5, "Stock": 25}
        assert isinstance(
            conn.execute("SELECT current_price FROM securities LIMIT 1").fetchone()[0], float
        )
    assert schema_context(db_path)["holdings"]["cost_basis"] == "REAL"


def test_supplied_sql_independent_fixture_oracle(settings):
    questions = json.loads((settings.data_root / "ground_truth_dataset.json").read_text())[
        "questions"
    ]
    with sqlite3.connect(settings.db_path) as conn:
        result = [conn.execute(q["ground_truth"]["sql_query"]).fetchall() for q in questions[:8]]
    assert result[0] == [(13,)]
    assert len(result[1]) == 10
    assert len(result[2]) == 8
    assert result[3] == [(85_000_000,)]
    assert len(result[4]) == 5
    assert result[4][0][:2] == (1, "AAPL")
    assert len(result[5]) == 7
    assert len(result[6]) == 8
    assert result[7] == [("Total Stock Market Index Fund", 6, 12, 0.5)]


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA database_list",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM _dataset_meta",
        "ATTACH ':memory:' AS other",
    ],
)
def test_readonly_connection_denies_system_access(db_path, sql):
    with readonly(db_path) as conn, pytest.raises(sqlite3.DatabaseError):
        conn.execute(sql)
