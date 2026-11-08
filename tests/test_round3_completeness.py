import pytest

from pl_capital.errors import QueryError


def test_latest_common_date_must_be_visible():
    from pl_capital.verification import validate_requested_output

    with pytest.raises(QueryError, match="date"):
        validate_requested_output(
            "SELECT portfolio_name,beta FROM portfolios JOIN risk_metrics USING(portfolio_id)",
            "Report beta on each portfolio latest common date",
        )
    validate_requested_output(
        "SELECT calculation_date AS as_of,beta FROM risk_metrics",
        "Report beta on the latest common date",
    )


def test_every_sell_transaction_has_stable_identity():
    from pl_capital.verification import validate_requested_output

    with pytest.raises(QueryError, match="transaction_id"):
        validate_requested_output(
            "SELECT quantity,price FROM transactions", "List every SELL transaction"
        )
    validate_requested_output(
        "SELECT transaction_id,quantity,price FROM transactions", "List every SELL transaction"
    )


def test_empty_sector_verification_contains_both_counts():
    from pl_capital.verification import validate_requested_output

    with pytest.raises(QueryError, match="count"):
        validate_requested_output(
            "SELECT sector_name FROM sectors",
            "List sectors with no security assigned and verify whether any holding belongs to them",
        )


@pytest.mark.parametrize(
    "sql,question,field",
    [
        (
            "SELECT nav AS nav_change_pct FROM portfolio_performance",
            "Rank NAV change from first to last observations by percentage",
            "first_nav",
        ),
        (
            "SELECT var_95 AS signed_change FROM risk_metrics",
            "Compare VaR on first and last observation",
            "first_date",
        ),
        ("SELECT quantity FROM holdings", "Show each bond and its market value", "symbol"),
        (
            "SELECT portfolio_name FROM portfolios LIMIT 5",
            "For every portfolio compare AUM with holdings and show five largest mismatches",
            "every requested",
        ),
        (
            "SELECT portfolio_name FROM portfolios",
            "Identify the largest equity sector twice where winning sector differs",
            "top_gap_pp",
        ),
        (
            "SELECT portfolio_name FROM portfolios",
            "Show bond weight, stock weight and each sector as equity-only allocations",
            "portfolio_pct",
        ),
        (
            "SELECT symbol FROM securities",
            "Each holding share of stock market value compared with current_weight normalized over equities",
            "equity_market_value",
        ),
        (
            "SELECT symbol FROM securities",
            "Using first to last observed close identify best and worst stocks",
            "extreme",
        ),
    ],
)
def test_compound_audit_fields_are_not_silently_omitted(sql, question, field):
    from pl_capital.verification import validate_requested_output

    with pytest.raises(QueryError, match=field):
        validate_requested_output(sql, question)


def test_unrequested_simple_result_keeps_its_original_shape():
    from pl_capital.verification import validate_requested_output

    validate_requested_output("SELECT nav FROM portfolio_performance", "Show NAV observations")
