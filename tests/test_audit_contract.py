import pytest

from pl_capital.errors import QueryError


def test_ratio_denominator_must_be_visible():
    from pl_capital.sql_safety import validate_audit_projection

    with pytest.raises(QueryError, match="denominator"):
        validate_audit_projection(
            "SELECT name,numerator,100.0*numerator/denominator AS percentage FROM ratios ORDER BY percentage DESC"
        )


def test_percentages_are_rounded_and_default_to_descending():
    from pl_capital.sql_safety import validate_audit_projection

    with pytest.raises(QueryError, match="ROUND"):
        validate_audit_projection("SELECT n,d,n/d*100 AS pct FROM ratios ORDER BY pct DESC")
    with pytest.raises(QueryError, match="descending"):
        validate_audit_projection("SELECT n,d,ROUND(n/d*100,2) AS pct FROM ratios ORDER BY n")
    validate_audit_projection("SELECT n,d,ROUND(n/d*100,2) AS pct FROM ratios ORDER BY pct DESC")


def test_nonpercentage_and_diversification_queries_are_unaffected():
    from pl_capital.sql_safety import validate_audit_projection

    validate_audit_projection("SELECT COUNT(*) FROM portfolios")
    validate_audit_projection(
        "SELECT sector_count,total_holdings,ROUND(CAST(sector_count AS REAL)/total_holdings,3) AS ratio FROM x ORDER BY ratio DESC"
    )
