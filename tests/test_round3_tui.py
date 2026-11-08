import pytest
from test_tui_refinement import ReplyAgent, ask

from pl_capital.clipboard import ClipboardOutcome
from pl_capital.models import Answer
from pl_capital.tui.app import CapitalApp


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [80, 110, 160])
async def test_non_computation_has_one_reason_and_targeted_next_step(tmp_path, width):
    reason = "Historical observations required for this comparison are unavailable."
    answer = Answer(intent="sql_query", status="missing_data", message=reason,
                    next_step="Choose a date present in the supplied snapshot.")
    app = CapitalApp(ReplyAgent(tmp_path, answer))
    async with app.run_test(size=(width, 28)) as pilot:
        await ask(app, pilot)
        text = " ".join(str(w.render()) for w in app.query("Static"))
        assert text.count(reason) == 1
        assert "How this was calculated" not in text
        assert "Why I couldn't calculate this" in text
        assert answer.next_step in text
        assert app.query_one(".execution-trace").collapsed
        assert app.query_one(".copy-sql").disabled


@pytest.mark.asyncio
async def test_scenario_offers_calculation_copy_and_sector_drilldown(tmp_path, monkeypatch):
    from pl_capital.tui.widgets import RecordDetailScreen, ResultTable

    class Clipboard:
        def copy_calculation(self, answer, *, terminal_copy):
            from pl_capital.presentation import calculation_text
            terminal_copy(calculation_text(answer))
            return ClipboardOutcome(True, "fixture", "Calculation copied.")

    answer = Answer(intent="scenario_analysis", tool="scenario_analysis", status="success",
        result={"scenario_label": "Hypothetical test", "columns": ["portfolio_name", "currency",
                "pre_portfolio_value", "post_portfolio_value", "portfolio_pnl", "portfolio_return_pct",
                "equity_return_pct", "top_loss_sector"],
                "rows": [["Mixed fund", "USD", "100", "90", "-10", "-10", "-20", "Technology"]],
                "row_count": 1, "assumptions": ["Bonds unchanged."],
                "formulas": ["pnl = post - pre"],
                "portfolios": [{"portfolio_name": "Mixed fund", "sectors": [{"sector": "Technology",
                    "post_sector_equity_value": "40", "post_equity_normalized_sector_exposure_pct": "100"}]}]})
    app = CapitalApp(ReplyAgent(tmp_path, answer), clipboard_service=Clipboard())
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=(80, 28)) as pilot:
        await ask(app, pilot, "Stress test all portfolios")
        assert app.query(".copy-calculation") and not app.query(".copy-sql")
        await pilot.press("f6")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(copied) == 1 and "post - pre" in copied[0]
        grid = app.query_one(ResultTable)
        grid.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RecordDetailScreen)
        text = " ".join(str(w.render()) for w in app.screen.query(".record-field"))
        assert "Technology" in text and "100" in text
        await pilot.press("escape")
        await ask(app, pilot, "/help")
        assert "scenario" in " ".join(w.source.lower() for w in app.query("Markdown"))


@pytest.mark.asyncio
async def test_graph_command_uses_actual_health_result_not_import_status(tmp_path):
    calls = []
    agent = ReplyAgent(tmp_path)

    def health():
        calls.append("health")
        return {"backend": "falkordblite", "status": "ready", "reason": "Embedded graph ready.",
                "graph_used": True, "native_ready": True, "snapshot_id": "fixture-snapshot",
                "counts": {"Portfolio": 13, "HOLDS": 100},
                "sample_cypher": {"query": "MATCH (p:Portfolio) RETURN count(p)", "rows": [[13]]},
                "sample_retrieval": {"used": True, "entities": ["Growth Equity Fund"]}}

    agent.graph.health = health
    app = CapitalApp(agent)
    async with app.run_test(size=(80, 28)) as pilot:
        await ask(app, pilot, "/graph")
        text = " ".join(w.source for w in app.query("Markdown"))
        assert calls == ["health"]
        assert "falkordblite" in text and "fixture-snapshot" in text
        assert "MATCH (p:Portfolio)" in text and "[[13]]" in text
        assert "Sample graph context used:** True" in text
