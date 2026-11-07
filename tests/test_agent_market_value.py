from pl_capital.models import Plan


def test_market_value_failure_uses_one_real_tool_correction(settings):
    from pl_capital.agent import PortfolioAgent

    correct = """WITH n AS (
      SELECT h.portfolio_id,SUM(h.quantity*s.current_price) AS value FROM holdings h
      JOIN securities s USING(security_id) JOIN sectors sec USING(sector_id)
      WHERE sec.sector_name='Energy' GROUP BY h.portfolio_id
    ), d AS (SELECT h.portfolio_id,SUM(h.quantity*s.current_price) AS total FROM holdings h
      JOIN securities s USING(security_id) GROUP BY h.portfolio_id)
    SELECT p.portfolio_name,n.value,d.total,ROUND(100.0*n.value/d.total,2) AS percentage
    FROM n JOIN d USING(portfolio_id) JOIN portfolios p USING(portfolio_id) ORDER BY percentage DESC"""

    class Planner:
        def __init__(self):
            self.calls = []

        def plan(self, question, context, **kwargs):
            self.calls.append(kwargs)
            return Plan(
                intent="sql_query",
                sql="SELECT portfolio_name,0,0,0 FROM portfolios"
                if len(self.calls) == 1
                else correct,
                parameters=[],
                portfolio=None,
                message=None,
            )

        def close(self):
            pass

    planner = Planner()
    agent = PortfolioAgent(settings, planner=planner)
    try:
        answer = agent.answer_question(
            "For each portfolio, show Energy sector holding value and percentage of portfolio value"
        )
        assert answer.error is None
        assert len(planner.calls) == 2
        assert "correction" in planner.calls[1]
        assert answer.sql == correct
        assert any(e.stage == "metric_verification" for e in answer.trace)
    finally:
        agent.close()
