def test_scalar_percentage_does_not_require_table_ordering():
    from pl_capital.sql_safety import validate_audit_projection

    validate_audit_projection("SELECT ROUND(100.0*SUM(x)/COUNT(*),2) AS percentage FROM x")


def test_explicit_requested_order_is_respected():
    from pl_capital.sql_safety import validate_audit_projection

    validate_audit_projection(
        "SELECT n,d,ROUND(n/d*100,2) AS pct FROM ratios ORDER BY n",
        question="show percentage breakdown sorted by name",
    )
