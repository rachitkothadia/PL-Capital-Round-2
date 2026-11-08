from pl_capital.models import Answer, TraceEvent


def count_answer():
    return Answer(
        question="How many portfolios?",
        intent="sql_query",
        tool="sql_query",
        message="portfolio_count: 13",
        sql="SELECT COUNT(*) AS portfolio_count FROM portfolios",
        executed_sql="SELECT COUNT(*) AS portfolio_count FROM portfolios",
        result={
            "columns": ["portfolio_count"],
            "rows": [[13]],
            "row_count": 1,
            "source_tables": ["portfolios"],
        },
        trace=[
            TraceEvent(
                stage="retrieval",
                detail="SQLite",
                data={
                    "used": False,
                    "reason": "No useful graph context",
                    "schema": {"secret_schema": "x" * 10000},
                },
            ),
            TraceEvent(stage="validation", detail="Single SELECT validated"),
        ],
    )


def test_scalar_is_primary_and_evidence_is_compact():
    from pl_capital.presentation import build_answer_view

    answer = count_answer()
    view = build_answer_view(answer)
    assert view.headline == "13 portfolios"
    assert 2 <= len(view.steps) <= 5
    assert any("portfolios" in step for step in view.steps)
    assert "fallback" in view.provenance.lower() or "sqlite" in view.provenance.lower()
    assert any(section.code == answer.executed_sql for section in view.sections)
    assert "secret_schema" not in str(view)
    assert len(str(view)) < 6000


def test_exposure_explanation_uses_real_intermediate_values():
    from pl_capital.presentation import build_answer_view

    answer = Answer(
        intent="exposure_calculator",
        tool="exposure_calculator",
        result={
            "portfolio_name": "Mixed",
            "status": "ok",
            "sectors": [
                {
                    "sector": "Technology",
                    "weight": "0.22",
                    "whole_portfolio_pct": 22,
                    "equity_normalized_pct": 61.111111,
                }
            ],
            "equity_weight_total": "0.36",
            "bond_weight_total": "0.64",
            "all_recorded_weights_total": "1.00",
            "equity_holding_count": 4,
            "bond_exclusion_count": 4,
        },
    )
    view = build_answer_view(answer)
    assert view.table.columns == ["Sector", "Portfolio %", "Equity %"]
    assert "22" in str(view.table.rows) and "61.111111" in str(view.table.rows)
    assert "0.36" in str(view.sections) and "0.22" in str(view.sections)
    assert "4" in " ".join(view.steps)


def test_error_proposal_is_not_presented_as_executed_sql():
    from pl_capital.presentation import build_answer_view

    view = build_answer_view(Answer(error="Rejected unsafe query", sql="DELETE FROM portfolios"))
    assert "Rejected" in view.headline
    assert not any(s.title == "Executed SQL" for s in view.sections)


def test_numbers_keep_small_differences_and_null_is_not_zero():
    from pl_capital.presentation import format_cell

    assert format_cell(None, "value") == "Not available"
    assert format_cell(0, "count") == "0"
    assert "0.0000042" in format_cell(0.0000042, "hhi_change")
    assert format_cell(-0.0000042, "hhi_change") == "-0.0000042"
    assert format_cell("2023-10-09", "date") == "2023-10-09"
    assert "719.245" in format_cell(719.245, "avg_price", currency="USD")


def test_sql_operations_explain_actual_join_filter_and_grouping():
    from pl_capital.presentation import build_answer_view

    sql = "SELECT s.symbol,SUM(h.quantity) AS shares FROM holdings h JOIN securities s ON s.security_id=h.security_id WHERE s.asset_type=:kind GROUP BY s.symbol ORDER BY shares DESC LIMIT 5"
    answer = Answer(
        tool="sql_query",
        sql=sql,
        executed_sql=sql,
        parameters={"kind": "Stock"},
        result={
            "columns": ["symbol", "shares"],
            "rows": [["AAPL", 200]],
            "row_count": 1,
            "source_tables": ["holdings", "securities"],
        },
    )
    view = build_answer_view(answer)
    evidence = str(view.sections)
    assert "Join" in evidence and "Group" in evidence and "Stock" in evidence
    assert "5" in evidence and "shares" in evidence


def test_distinct_count_is_not_mislabeled_as_holding_rows():
    from pl_capital.presentation import build_answer_view

    sql = "SELECT COUNT(DISTINCT portfolio_id) AS unique_portfolios FROM holdings"
    view = build_answer_view(
        Answer(
            executed_sql=sql,
            result={
                "columns": ["unique_portfolios"],
                "rows": [[13]],
                "row_count": 1,
                "source_tables": ["holdings"],
            },
        )
    )
    assert view.headline == "unique portfolios: 13"
