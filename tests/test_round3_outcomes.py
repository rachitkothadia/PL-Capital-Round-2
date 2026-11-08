import pytest

from pl_capital.agent import PortfolioAgent
from pl_capital.errors import PlanningError
from pl_capital.models import Answer, Plan
from pl_capital.presentation import build_answer_view, format_cell


class Planner:
    def __init__(self, plan):
        self.value = plan

    def plan(self, *args, **kwargs):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value

    def close(self):
        pass


def plan(intent, **kwargs):
    return Plan(intent=intent, sql=None, parameters=[], portfolio=None, message=None, **kwargs)


def test_no_computation_has_one_reason_and_targeted_next_step():
    answer = Answer(
        intent="unsupported_analysis",
        message="Option contracts are not supplied.",
        status="unsupported_analysis",
        next_step="Use supplied stocks or bonds.",
    )
    view = build_answer_view(answer)
    assert view.explanation_title == "Why I couldn't calculate this"
    assert str(view).count("Option contracts are not supplied.") == 1
    assert view.next_step == "Use supplied stocks or bonds."
    assert not view.table


def test_nav_and_risk_ratios_are_not_dollars():
    assert "$" not in format_cell(108.62, "nav", currency="USD")
    assert "$" not in format_cell(0.17, "nav_change", currency="USD")
    assert "$" not in format_cell(0.01, "beta_change", currency="USD")


@pytest.mark.parametrize(
    "intent,status",
    [
        ("out_of_domain", "out_of_domain"),
        ("unsupported_analysis", "unsupported_analysis"),
        ("missing_data", "missing_data"),
        ("needs_clarification", "needs_clarification"),
    ],
)
def test_canonical_non_tool_outcome(settings, intent, status):
    p = plan(intent)
    p.message = "No suitable observations."
    a = PortfolioAgent(settings, planner=Planner(p))
    try:
        answer = a.answer_question("Descriptive analysis of the supplied snapshot")
        assert answer.status == status
        assert answer.executed_sql is None
    finally:
        a.close()


def test_model_failure_is_tool_error_not_refusal(settings):
    a = PortfolioAgent(settings, planner=Planner(PlanningError("Gemini unavailable")))
    try:
        answer = a.answer_question("Count portfolios")
        assert answer.status == "tool_error"
        assert answer.next_step
    finally:
        a.close()


def test_valid_empty_query_is_not_out_of_domain(settings):
    p = plan("sql_query")
    p.sql = "SELECT portfolio_name FROM portfolios WHERE total_aum < 0"
    a = PortfolioAgent(settings, planner=Planner(p))
    try:
        assert a.answer_question("List funds with negative AUM").status == "empty_result"
    finally:
        a.close()


@pytest.mark.parametrize("question", ["", "x" * 4001, None])
def test_invalid_question_needs_clarification_before_model(settings, question):
    a = PortfolioAgent(settings, planner=Planner(AssertionError("must not plan")))
    try:
        answer = a.answer_question(question)
        assert answer.status == "needs_clarification"
        assert answer.error is None
    finally:
        a.close()


def test_missing_performance_is_not_an_empty_match(settings):
    p = plan("sql_query")
    p.sql = "SELECT nav FROM portfolio_performance JOIN portfolios USING(portfolio_id) WHERE portfolio_name=:name"
    from pl_capital.models import Parameter

    p.parameters = [Parameter(name="name", value="Dividend Aristocrats")]
    p.portfolio = "Dividend Aristocrats"
    a = PortfolioAgent(settings, planner=Planner(p))
    try:
        answer = a.answer_question("Latest NAV for Dividend Aristocrats")
        assert answer.status == "missing_data"
        assert "portfolio_performance" in answer.message
        assert "not zero" in answer.message
    finally:
        a.close()


def test_failed_partial_scenario_has_no_calculation_heading():
    answer = Answer(tool="scenario_analysis", error="Stopped", result={"portfolios": [1]})
    view = build_answer_view(answer)
    assert view.explanation_title == "Why I couldn't calculate this"
    assert view.table is None


def test_scenario_display_cents_and_no_sector_losses_do_not_modify_data():
    assert format_cell("1565292.5", "post_portfolio_value", currency="USD") == "$1,565,292.50"
    assert format_cell(None, "top_loss_sector") == "None (no sector losses)"
