import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pl_capital.models import Answer, TraceEvent


class FakeAgent:
    def __init__(self, tmp_path: Path):
        self.settings = SimpleNamespace(model="openai/gpt-oss-120b", cache_dir=tmp_path, data_root=tmp_path)
        self.graph = SimpleNamespace(status=lambda: {"backend": "sqlite", "reason": "test fallback"})
        self.questions = []
        self.resets = 0

    def answer_question(self, question):
        self.questions.append(question)
        return Answer(
            intent="sql_query", tool="sql_query", message="13 portfolios in the supplied snapshot.",
            sql="SELECT COUNT(*) FROM portfolios", result={"columns": ["count"], "rows": [[13]],
            "source_tables": ["portfolios"],
            "row_count": 1}, trace=[TraceEvent(stage="validation", detail="Read-only SQL accepted")],
            executed_sql="SELECT COUNT(*) FROM portfolios",
        )

    def reset_context(self):
        self.resets += 1

    def set_model(self, model):
        self.settings.model = model


async def send(app, pilot, text):
    composer = app.query_one("#composer")
    composer.text = text
    composer.focus()
    await pilot.press("enter")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.asyncio
async def test_enter_calls_agent_and_renders_result(tmp_path):
    from pl_capital.tui.app import CapitalApp

    agent = FakeAgent(tmp_path)
    app = CapitalApp(agent)
    async with app.run_test(size=(130, 40)) as pilot:
        await send(app, pilot, "How many portfolios?")
        assert agent.questions == ["How many portfolios?"]
        assert app.query_one("#composer").text == ""
        assert len(app.query(".answer-card")) == 1
        assert "13" in str(app.query_one(".answer-headline").render())


@pytest.mark.asyncio
async def test_multiline_and_layout_resize(tmp_path):
    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(FakeAgent(tmp_path))
    async with app.run_test(size=(160, 40)) as pilot:
        composer = app.query_one("#composer")
        composer.focus()
        await pilot.press("a", "ctrl+j", "b")
        assert composer.text == "a\nb"
        assert app.query_one("#sidebar").display
        assert app.query_one("#inspector").display
        await pilot.resize_terminal(70, 24)
        await pilot.pause()
        assert not app.query_one("#sidebar").display
        assert not app.query_one("#inspector").display
        assert composer.display


@pytest.mark.asyncio
async def test_commands_reset_context_switch_models_and_open_palette(tmp_path):
    from pl_capital.tui.app import CapitalApp

    agent = FakeAgent(tmp_path)
    app = CapitalApp(agent)
    async with app.run_test(size=(110, 35)) as pilot:
        await send(app, pilot, "/model openai/gpt-oss-20b")
        assert agent.settings.model == "openai/gpt-oss-20b"
        await send(app, pilot, "/new")
        assert agent.resets == 1
        assert agent.questions == []
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_agent_error_is_visible_without_crash(tmp_path):
    from pl_capital.tui.app import CapitalApp

    agent = FakeAgent(tmp_path)
    agent.answer_question = lambda _: Answer(error="Groq unavailable; retry later.")
    app = CapitalApp(agent)
    async with app.run_test(size=(85, 26)) as pilot:
        await send(app, pilot, "A question")
        assert "Groq unavailable" in str(app.query_one(".answer-headline").render())
        assert not app.busy


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 45), (80, 24)], ids=["wide", "compact"])
async def test_trace_keyboard_toggle_and_copy_sql_export(tmp_path, monkeypatch, size):
    from textual.widgets import Button, Collapsible

    from pl_capital.clipboard import ClipboardOutcome
    from pl_capital.tui.app import CapitalApp

    class ApplicationClipboard:
        def copy_sql(self, answer, *, terminal_copy):
            terminal_copy(answer.executed_sql)
            return ClipboardOutcome(True, "mock", "SQL copied using a mocked clipboard.")

    app = CapitalApp(FakeAgent(tmp_path), clipboard_service=ApplicationClipboard())
    copied = []
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
    async with app.run_test(size=size) as pilot:
        await send(app, pilot, "Count portfolios")
        trace = app.query_one(".execution-trace", Collapsible)
        assert trace.collapsed
        title = trace.query_one("CollapsibleTitle")
        title.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert not trace.collapsed
        steps = " ".join(str(widget.render()) for widget in app.query(".explanation-step"))
        assert "read-only SELECT" in steps
        copy_button = app.query_one(".copy-sql", Button)
        copy_button.focus(scroll_visible=False)
        copy_button.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(copy_button, offset=(2, 1))
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert copied == ["SELECT COUNT(*) FROM portfolios"]
        export_button = app.query_one(".export-answer", Button)
        export_button.focus(scroll_visible=False)
        export_button.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(export_button, offset=(2, 1))
        await pilot.pause()
        await app.workers.wait_for_complete()
        paths = list((tmp_path / "exports").glob("*.json"))
        assert len(paths) == 1
        assert json.loads(paths[0].read_text())["sql"] == copied[0]
        await send(app, pilot, "/trace")
        assert trace.collapsed


@pytest.mark.asyncio
async def test_exposure_card_uses_both_denominators_and_coverage(tmp_path):
    from pl_capital.tui.app import CapitalApp

    agent = FakeAgent(tmp_path)
    agent.answer_question = lambda _: Answer(
        intent="exposure_calculator", tool="exposure_calculator", message="Recorded equity exposure.",
        result={"portfolio_name": "Mixed fund", "sectors": [{"sector": "Technology", "weight": "0.4",
        "whole_portfolio_pct": 40.0, "equity_normalized_pct": 100.0}], "equity_weight_total": "0.4",
        "bond_weight_total": "0.6", "all_recorded_weights_total": "1.0", "equity_holding_count": 2,
        "bond_exclusion_count": 3, "formula": "sector weight / stock weight"},
        warnings=["Bonds excluded from the sector breakdown."],
    )
    app = CapitalApp(agent)
    async with app.run_test(size=(100, 40)) as pilot:
        await send(app, pilot, "Mixed fund exposure")
        card = app.query_one(".exposure-card")
        from rich.console import Console

        console = Console(width=100, color_system=None)
        with console.capture() as capture:
            console.print(card.query_one(".result-table").render())
        rendered = capture.get() + " ".join(str(widget.render()) for widget in card.query("Static"))
        assert "40%" in rendered and "100%" in rendered
        assert "0.6" in rendered and "3" in rendered
        assert "Technology" in rendered


@pytest.mark.asyncio
async def test_eval_command_calls_real_evaluator_hook_without_blocking(tmp_path, monkeypatch):
    import sys
    from types import ModuleType

    from pl_capital.tui.app import CapitalApp

    calls = []

    def evaluate(agent, root, *, report, live):
        calls.append((agent, root, report, live))
        return {"passed": 9, "total": 10, "accuracy": 0.9}

    evaluator = ModuleType("pl_capital.evaluator")
    evaluator.evaluate = evaluate
    monkeypatch.setitem(sys.modules, "pl_capital.evaluator", evaluator)
    agent = FakeAgent(tmp_path)
    app = CapitalApp(agent)
    async with app.run_test(size=(110, 36)) as pilot:
        await send(app, pilot, "/eval")
        assert calls == [(agent, tmp_path, tmp_path / "evaluation.json", True)]
        assert not app.busy
        rendered = " ".join(widget.source for widget in app.query("Markdown"))
        assert "9/10" in rendered


def test_display_redacts_credentials_and_terminal_controls():
    from pl_capital.tui.widgets import plain, safe_json

    assert "\x1b" not in plain("hello\x1b[31mworld")
    assert "gsk_" not in plain("gsk_" + "a" * 50)
    data = safe_json({"authorization": "bearer secret", "token": "sensitive", "rows": [[13]]})
    assert "sensitive" not in data and "bearer secret" not in data
    assert "13" in data
