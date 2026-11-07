import pytest

from pl_capital.errors import QueryError


def test_verifier_rejects_fraction_and_zero_filled_portfolios(db_path):
    from pl_capital.verification import verify_market_values

    question = (
        "For each portfolio show Technology sector holdings value and percentage of portfolio value"
    )
    with pytest.raises(QueryError, match="percentage|market-value|portfolio"):
        verify_market_values(
            db_path,
            question,
            ["Technology"],
            {
                "columns": ["fund", "sector", "total", "percentage"],
                "rows": [["Tech Innovation Fund", 1565292.5, 1565292.5, 1.0]],
            },
        )


def test_verifier_generalizes_to_other_sectors(db_path):
    from pl_capital.sql_tool import execute
    from pl_capital.verification import verify_market_values

    sql = """WITH n AS (
      SELECT h.portfolio_id,SUM(h.quantity*s.current_price) AS value FROM holdings h
      JOIN securities s USING(security_id) JOIN sectors sec USING(sector_id)
      WHERE sec.sector_name=:sector GROUP BY h.portfolio_id
    ), d AS (SELECT h.portfolio_id,SUM(h.quantity*s.current_price) AS total FROM holdings h
      JOIN securities s USING(security_id) GROUP BY h.portfolio_id)
    SELECT p.portfolio_name,n.value,d.total,ROUND(100.0*n.value/d.total,2) AS percentage
    FROM n JOIN d USING(portfolio_id) JOIN portfolios p USING(portfolio_id) ORDER BY percentage DESC"""
    for sector in ["Technology", "Automotive", "Energy"]:
        result = execute(db_path, sql, {"sector": sector}).model_dump()
        assert verify_market_values(
            db_path, f"Portfolio {sector} sector value and percentage", [sector], result
        )
        result["rows"][0][3] /= 100
        with pytest.raises(QueryError, match="percentage"):
            verify_market_values(
                db_path, f"Portfolio {sector} sector value and percentage", [sector], result
            )


def test_general_sql_is_not_misclassified(db_path):
    from pl_capital.verification import verify_market_values

    assert not verify_market_values(db_path, "Count portfolios", ["Technology"], {})
