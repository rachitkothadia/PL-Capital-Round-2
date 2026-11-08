from pl_capital.models import Plan


class Planner:
    def __init__(self, sql, parameters=None, portfolio=None):
        self.sql, self.parameters, self.portfolio = sql, parameters or [], portfolio
        self.calls = 0

    def plan(self, *_args, **_kwargs):
        self.calls += 1
        return Plan(
            intent="sql_query",
            sql=self.sql,
            parameters=self.parameters,
            portfolio=self.portfolio,
            message=None,
        )

    def close(self):
        pass


def test_compound_sql_context_label_does_not_require_one_portfolio(settings):
    from pl_capital.agent import PortfolioAgent

    planner = Planner(
        "SELECT portfolio_name FROM portfolios ORDER BY portfolio_name",
        portfolio="Conservative Income Fund and Balanced Portfolio",
    )
    agent = PortfolioAgent(settings, planner=planner)
    try:
        answer = agent.answer_question("Compare these two funds")
        assert answer.error is None
        assert answer.result["row_count"] == 13
        assert planner.calls == 1
        assert agent.previous_portfolio is None
    finally:
        agent.close()


def test_only_accepted_executed_sql_and_bindings_are_published(settings):
    from pl_capital.agent import PortfolioAgent
    from pl_capital.models import Parameter

    planner = Planner(
        " SELECT portfolio_name FROM portfolios WHERE status=:status ",
        [Parameter(name="status", value="Active")],
    )
    agent = PortfolioAgent(settings, planner=planner)
    try:
        answer = agent.answer_question("Show active portfolios")
        assert answer.question == "Show active portfolios"
        assert answer.executed_sql == planner.sql.strip()
        assert answer.executed_parameters == {"status": "Active"}
        assert answer.source_dates["historical_prices"] == ["2023-09-25", "2023-10-09"]
        assert (
            next(e for e in answer.trace if e.stage == "execution").data["sql"]
            == answer.executed_sql
        )
    finally:
        agent.close()


def test_failed_sql_never_has_copyable_executed_statement(settings):
    from pl_capital.agent import PortfolioAgent

    agent = PortfolioAgent(settings, planner=Planner("DELETE FROM holdings"))
    try:
        answer = agent.answer_question("Count holdings")
        assert answer.error
        assert answer.executed_sql is None
        assert answer.result == {}
    finally:
        agent.close()


def test_legitimate_window_ratio_keeps_requested_precision_and_shape(settings):
    from pl_capital.agent import PortfolioAgent

    sql = "SELECT portfolio_name,total_aum,ROUND(total_aum/SUM(total_aum) OVER()*100,6) AS aum_pct FROM portfolios ORDER BY portfolio_name"
    planner = Planner(sql)
    agent = PortfolioAgent(settings, planner=planner)
    try:
        answer = agent.answer_question(
            "Show every fund's AUM and percentage of aggregate AUM, to six decimals, sorted by name"
        )
        assert answer.error is None
        assert answer.result["row_count"] == 13
        assert planner.calls == 1
    finally:
        agent.close()


def test_unrequested_average_rounding_is_corrected_before_execution(settings):
    from pl_capital.agent import PortfolioAgent

    unrounded = "SELECT AVG(current_price) AS avg_price FROM securities WHERE sector_id=1"

    class CorrectingPlanner(Planner):
        def plan(self, *_args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Plan(
                    intent="sql_query",
                    sql=unrounded.replace("AVG(current_price)", "ROUND(AVG(current_price),2)"),
                    parameters=[],
                    portfolio=None,
                    message=None,
                )
            assert "round" in kwargs["correction"]["error"].casefold()
            return Plan(
                intent="sql_query", sql=unrounded, parameters=[], portfolio=None, message=None
            )

    planner = CorrectingPlanner(unrounded)
    agent = PortfolioAgent(settings, planner=planner)
    try:
        answer = agent.answer_question(
            "What is the average current price in the technology sector?"
        )
        assert answer.error is None
        assert answer.result["rows"] == [[719.245]]
        assert planner.calls == 2
        assert len([event for event in answer.trace if event.stage == "execution"]) == 1
    finally:
        agent.close()


def test_explicit_average_rounding_is_allowed(settings):
    from pl_capital.agent import PortfolioAgent

    planner = Planner(
        "SELECT ROUND(AVG(current_price),2) AS avg_price FROM securities WHERE sector_id=1"
    )
    agent = PortfolioAgent(settings, planner=planner)
    try:
        answer = agent.answer_question("Round the average current price to two decimals")
        assert answer.error is None
        assert answer.result["rows"] == [[719.25]]
        assert planner.calls == 1
    finally:
        agent.close()


def test_live_agent_switches_provider_without_reusing_the_other_key(settings, monkeypatch):
    from pl_capital.agent import PortfolioAgent

    monkeypatch.setenv("GEMINI_API_KEY", "new-gemini-fixture")
    agent = PortfolioAgent(settings)

    class Previous:
        closed = False

        def close(self):
            self.closed = True

    previous = Previous()
    agent._planner = previous
    try:
        agent.set_model("gemini-2.5-pro")
        assert previous.closed
        assert agent._planner is None
        assert agent.settings.provider == "gemini"
        assert agent.settings.api_key == "new-gemini-fixture"
        assert agent.settings.db_path == settings.db_path
    finally:
        agent.close()


def test_missing_cross_provider_key_preserves_current_provider(settings, monkeypatch, tmp_path):
    import pytest

    from pl_capital.agent import PortfolioAgent
    from pl_capital.errors import PlanningError

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    agent = PortfolioAgent(settings)
    try:
        with pytest.raises(PlanningError, match="GEMINI_API_KEY"):
            agent.set_model("gemini-2.5-pro")
        assert agent.settings == settings
    finally:
        agent.close()
