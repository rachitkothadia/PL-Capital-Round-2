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
