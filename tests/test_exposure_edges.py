import sqlite3

import pytest

from pl_capital.errors import DataError
from pl_capital.exposure import calculate, resolve_portfolio


def test_incomplete_weights_stay_visible(db_path):
    result = calculate(db_path, "Total Stock Market Index Fund")
    assert float(result.all_recorded_weights_total) == pytest.approx(0.98)
    assert sum(s.whole_portfolio_pct for s in result.sectors) == pytest.approx(98)
    assert sum(s.equity_normalized_pct for s in result.sectors) == pytest.approx(100, abs=1e-5)
    assert any("98" in w for w in result.warnings)


@pytest.mark.parametrize("weight", [None, -0.1, float("inf"), float("nan")])
def test_invalid_weights_fail_closed(db_path, weight):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE holdings SET current_weight=? WHERE holding_id=1", (weight,))
    with pytest.raises(DataError, match="weight"):
        calculate(db_path, "Growth Equity Fund")


def test_missing_sector_is_not_fabricated(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE securities SET sector_id=NULL WHERE security_id=1")
    with pytest.raises(DataError, match="sector"):
        calculate(db_path, "Growth Equity Fund")


def test_duplicate_holdings_are_not_double_counted(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
          CREATE TABLE holdings_copy AS SELECT * FROM holdings;
          DROP TABLE holdings;
          ALTER TABLE holdings_copy RENAME TO holdings;
          INSERT INTO holdings SELECT * FROM holdings WHERE holding_id=1;
        """)
    with pytest.raises(DataError, match="Duplicate"):
        calculate(db_path, "Growth Equity Fund")


def test_zero_weight_equities_have_no_division_by_zero(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE holdings SET current_weight=0 WHERE portfolio_id=3")
    result = calculate(db_path, "Tech Innovation Fund")
    assert result.status == "no_equity_holdings"
    assert result.equity_holding_count == 8
    assert result.sectors == []


@pytest.mark.parametrize(
    "name", ["tech innovation fund", "TECH INNOVATION FUND", "Tech Innovaton", 3]
)
def test_controlled_entity_resolution(db_path, name):
    assert resolve_portfolio(db_path, name) == (3, "Tech Innovation Fund")
