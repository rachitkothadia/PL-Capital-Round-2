import json
import sqlite3

import pytest

from pl_capital.errors import QueryError
from pl_capital.sql_tool import execute


@pytest.mark.parametrize("index", range(8))
def test_all_supplied_analytical_sql_matches_independent_connection(settings, index):
    question = json.loads((settings.data_root / "ground_truth_dataset.json").read_text())[
        "questions"
    ][index]
    sql = question["ground_truth"]["sql_query"]
    with sqlite3.connect(settings.db_path) as conn:
        expected = [list(r) for r in conn.execute(sql)]
    actual = execute(settings.db_path, sql, {})
    assert actual.rows == expected
    assert not actual.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT symbol, SUM(quantity) FROM holdings JOIN securities USING(security_id) GROUP BY symbol",
        "SELECT portfolio_name FROM portfolios WHERE portfolio_id IN (SELECT portfolio_id FROM holdings)",
        "SELECT portfolio_id,ROW_NUMBER() OVER(ORDER BY portfolio_id) FROM portfolios",
        "SELECT COUNT(*) FROM portfolios WHERE portfolio_name LIKE :pattern",
        "SELECT COALESCE(SUM(current_weight),0) FROM holdings WHERE portfolio_id=:id",
    ],
)
def test_parameterized_analytical_forms(db_path, sql):
    params = {"pattern": "%Fund%"} if ":pattern" in sql else {"id": 3} if ":id" in sql else {}
    assert execute(db_path, sql, params).rows


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT CAST(readfile('/etc/passwd') AS TEXT)",
        "WITH x AS (SELECT 1) SELECT * FROM sqlite_master",
        "SELECT * FROM portfolios UNION SELECT * FROM portfolios; DELETE FROM portfolios",
        "SELECT * FROM portfolios WHERE portfolio_name=readfile('.env')",
    ],
)
def test_nested_escapes_rejected(db_path, sql):
    with pytest.raises(QueryError):
        execute(db_path, sql, {})
