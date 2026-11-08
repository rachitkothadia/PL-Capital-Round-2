import json
from decimal import Decimal

import pytest

from pl_capital.agent import PortfolioAgent
from pl_capital.models import Answer, Plan
from pl_capital.scenario import ScenarioRequest, calculate_scenario


class Planner:
    def __init__(self, request):
        self.request = request

    def plan(self, *_args, **_kwargs):
        return Plan(
            intent="scenario_analysis",
            sql=None,
            parameters=[],
            portfolio=None,
            message=None,
            scenario=self.request,
        )

    def close(self):
        pass


def test_scenario_agent_uses_typed_deterministic_tool(settings):
    request = ScenarioRequest(
        sector_shocks={"Technology": "-.22", "Energy": ".11", "Financials": "-.07"}
    )
    agent = PortfolioAgent(settings, planner=Planner(request))
    try:
        answer = agent.answer_question("Stress the supplied holdings")
        assert answer.status == "success" and answer.tool == "scenario_analysis"
        assert answer.result == calculate_scenario(settings.db_path, request)
        assert answer.executed_sql is None
        assert any(e.stage == "calculation" and "Decimal" in e.detail for e in answer.trace)
        assert Decimal(answer.result["totals"]["portfolio_pnl"]) == Decimal("-2060474.23")
    finally:
        agent.close()


def test_scenario_clipboard_and_export_use_actual_evidence(settings, monkeypatch):
    from pl_capital import clipboard
    from pl_capital.clipboard import ClipboardService
    from pl_capital.exporting import ExportService

    result = calculate_scenario(
        settings.db_path, ScenarioRequest(sector_shocks={"Technology": "-.22"})
    )
    answer = Answer(
        intent="scenario_analysis",
        tool="scenario_analysis",
        result=result,
        status="success",
        currency=result["currency"],
    )
    captured = []
    monkeypatch.setattr(clipboard.shutil, "which", lambda _: None)
    outcome = ClipboardService().copy_calculation(answer, terminal_copy=captured.append)
    assert not outcome.confirmed  # OSC52 receipt cannot prove host clipboard success.
    assert "quantity" in captured[0] and "post = pre" in captured[0]
    example = next(h for p in result["portfolios"] for h in p["holdings"] if Decimal(h["pnl"]) != 0)
    assert example["symbol"] in captured[0] and example["pnl"] in captured[0]
    assert all(p["portfolio_name"] in captured[0] for p in result["portfolios"])
    saved = json.loads(ExportService(settings).export_answer(answer).read_text())
    assert saved["status"] == "success"
    assert saved["sql"] is None and saved["result"] == result
    assert sum(len(p["holdings"]) for p in saved["result"]["portfolios"]) == 95
    assert not ClipboardService().copy_sql(answer).confirmed


def test_scenario_cli_has_no_model_dependency(settings, monkeypatch, capsys):
    from pl_capital import cli

    monkeypatch.setenv("PL_CAPITAL_DATA_DIR", str(settings.data_root))
    monkeypatch.setenv("PL_CAPITAL_CACHE_DIR", str(settings.cache_dir))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(cli, "PortfolioAgent", lambda _: pytest.fail("No model is required"))
    assert (
        cli.main(["scenario", "--shock", "Technology=-22%", "--shock", "Energy=11%", "--json"]) == 0
    )
    answer = json.loads(capsys.readouterr().out)
    assert answer["result"]["sector_shocks"] == {"Technology": "-0.22", "Energy": "0.11"}
    assert answer["result"]["row_count"] == 13
    for bad in ["Technology=-101%", "Technology=nan", "Technology=1+1", "missing"]:
        assert cli.main(["scenario", "--shock", bad, "--json"]) == 1
        assert "error" in json.loads(capsys.readouterr().out)


def test_recorded_nav_lag_is_verified_independently(settings):
    from pl_capital.database import readonly
    from pl_capital.sql_tool import execute

    sql = """WITH observations AS (
      SELECT portfolio_name,performance_date,nav,sharpe_ratio,beta,
        LAG(nav) OVER (PARTITION BY p.portfolio_id ORDER BY performance_date) AS previous_nav,
        LAG(sharpe_ratio) OVER (PARTITION BY p.portfolio_id ORDER BY performance_date) AS previous_sharpe,
        LAG(beta) OVER (PARTITION BY p.portfolio_id ORDER BY performance_date) AS previous_beta
      FROM portfolio_performance pp JOIN portfolios p USING(portfolio_id)
      JOIN risk_metrics r ON r.portfolio_id=p.portfolio_id AND r.calculation_date=pp.performance_date
    ) SELECT performance_date,previous_nav,nav,previous_sharpe,sharpe_ratio,previous_beta,beta,
      100.0*(nav-previous_nav)/NULLIF(previous_nav,0) AS nav_change_pct FROM observations
      WHERE portfolio_name=:name AND performance_date=:date"""
    result = execute(
        settings.db_path, sql, {"name": "Conservative Income Fund", "date": "2023-09-27"}
    )
    assert result.rows == [
        ["2023-09-27", 108.45, 108.62, 1.58, 1.56, 0.36, 0.37, pytest.approx(100 * 0.17 / 108.45)]
    ]
    with readonly(settings.db_path) as conn:
        records = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM portfolio_performance WHERE portfolio_id=2 ORDER BY performance_date"
            )
        ]
    # SQL window results are checked against distinct chronological source rows, not a saved expected answer.
    current = next(i for i, r in enumerate(records) if r["performance_date"] == "2023-09-27")
    assert records[current - 1]["nav"] == result.rows[0][1]
    assert records[current]["nav"] == result.rows[0][2]
