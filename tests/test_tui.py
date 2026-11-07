from pathlib import Path
from types import SimpleNamespace

import pytest

from pl_capital.models import Answer, TraceEvent


class FakeAgent:
    def __init__(self, tmp_path: Path):
        self.settings = SimpleNamespace(model="openai/gpt-oss-120b", cache_dir=tmp_path)
        self.graph = SimpleNamespace(status=lambda: {"backend": "sqlite", "reason": "test fallback"})
        self.questions = []
        self.resets = 0

    def answer_question(self, question):
        self.questions.append(question)
        return Answer(
            intent="sql_query", tool="sql_query", message="13 portfolios in the supplied snapshot.",
            sql="SELECT COUNT(*) FROM portfolios", result={"columns": ["count"], "rows": [[13]],
            "row_count": 1}, trace=[TraceEvent(stage="validation", detail="Read-only SQL accepted")],
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
        assert "13" in app.query_one(".answer-body").source


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
        assert "Groq unavailable" in app.query_one(".answer-body").source
        assert not app.busy
