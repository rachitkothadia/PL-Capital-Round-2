import pytest

from pl_capital.errors import QueryError
from pl_capital.sql_tool import execute


@pytest.mark.parametrize(
    "condition",
    [
        "status='Active' AND total_aum>0",
        "status='Active' OR status='Inactive'",
        "NOT (status='Inactive')",
        "total_aum BETWEEN 1 AND 1000000000",
        "portfolio_id IN (SELECT portfolio_id FROM holdings)",
        "total_aum IS NOT NULL",
        "EXISTS(SELECT 1 FROM holdings h WHERE h.portfolio_id=p.portfolio_id)",
    ],
)
def test_structural_conditions_remain_readonly_queries(db_path, condition):
    assert execute(db_path, f"SELECT COUNT(*) FROM portfolios p WHERE {condition}", {}).rows


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM holdings h JOIN securities s USING(security_id) WHERE s.asset_type='Stock' AND s.current_price>0",
        "SELECT p.portfolio_name,r.var_95 FROM portfolios p JOIN risk_metrics r ON r.portfolio_id=p.portfolio_id JOIN portfolio_performance f ON f.portfolio_id=r.portfolio_id AND f.performance_date=r.calculation_date",
        "SELECT SUM(CASE WHEN asset_type='Stock' AND current_price>0 THEN 1 ELSE 0 END) FROM securities",
    ],
)
def test_multi_condition_joins_and_aggregates(db_path, sql):
    assert execute(db_path, sql, {}).rows


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT readfile('.env') WHERE 1=1 AND 2=2",
        "SELECT 1 WHERE NOT(load_extension('x') IS NULL)",
        "SELECT 1 WHERE 1=1 OR EXISTS(SELECT * FROM sqlite_master)",
    ],
)
def test_boolean_operators_cannot_hide_forbidden_access(db_path, sql):
    with pytest.raises(QueryError):
        execute(db_path, sql, {})
