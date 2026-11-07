import pytest


@pytest.mark.parametrize(
    "question",
    [
        "For Growth Equity Fund show Technology sector holdings value and percentage of portfolio value",
        "For each portfolio show Technology value and percentage, top 5 only",
        "For each active portfolio show Technology holding value and percentage",
        "For each portfolio show Technology value as a percentage of AUM",
    ],
)
def test_specialized_filters_retain_general_sql_path(db_path, question):
    from pl_capital.verification import verify_market_values

    assert not verify_market_values(db_path, question, ["Technology"], {})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT n,x.d,ROUND(n/d*100,2) AS pct FROM ratios x ORDER BY pct DESC",
        "SELECT n,d,ROUND(n/d*100,2) AS pct FROM ratios ORDER BY 3 DESC",
        "SELECT n,d,ROUND(n/d*100,2) AS pct FROM ratios ORDER BY ROUND(n/d*100,2) DESC",
    ],
)
def test_equivalent_auditable_sql_forms(sql):
    from pl_capital.sql_safety import validate_audit_projection

    validate_audit_projection(sql)
