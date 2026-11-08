import asyncio
from types import SimpleNamespace

import pytest

from pl_capital.models import Answer, TraceEvent


class ReplyAgent:
    def __init__(self, tmp_path, answer=None):
        self.settings = SimpleNamespace(
            cache_dir=tmp_path / "cache", config_dir=tmp_path / "config",
            model="gemini-2.5-pro", data_root=tmp_path,
        )
        self.graph = SimpleNamespace(status=lambda: {"backend": "sqlite", "reason": "offline UI fixture"})
        self.answer = answer or Answer(
            intent="sql_query", tool="sql_query", question="How many portfolios?",
            message="fund_count: 13", sql="SELECT COUNT(*) AS fund_count FROM portfolios",
            executed_sql="SELECT COUNT(*) AS fund_count FROM portfolios",
            result={"columns": ["fund_count"], "rows": [[13]], "row_count": 1,
                    "source_tables": ["portfolios"], "truncated": False},
            trace=[TraceEvent(stage="validation", detail="Read-only SELECT validated.",
                              data={"schema": {"portfolios": {"portfolio_id": "INTEGER"}}})],
        )

    def answer_question(self, _question):
        return self.answer

    def reset_context(self):
        pass

    def set_model(self, model):
        self.settings.model = model


async def ask(app, pilot, text="How many portfolios?"):
    composer = app.query_one("#composer")
    composer.text = text
    composer.focus()
    await pilot.press("enter")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (100, 30), (120, 35), (160, 45)])
async def test_answer_is_visible_before_collapsed_details(tmp_path, size):
    from textual.widgets import Collapsible

    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path))
    async with app.run_test(size=size) as pilot:
        await ask(app, pilot)
        headline = app.query_one(".answer-headline")
        viewport = app.query_one("#timeline").content_region
        assert viewport.y <= headline.region.y < viewport.bottom
        assert headline.region.bottom <= viewport.bottom
        assert "13" in str(headline.render())
        assert 2 <= len(app.query(".explanation-step")) <= 5
        assert app.query_one(".execution-trace", Collapsible).collapsed
        assert app.query_one(".raw-diagnostics", Collapsible).collapsed
        assert app.query_one(".raw-json").region.height == 0


@pytest.mark.asyncio
async def test_new_answer_starts_collapsed_after_previous_trace_was_opened(tmp_path):
    from textual.widgets import Collapsible

    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await ask(app, pilot)
        app.action_toggle_trace()
        await pilot.pause()
        assert not app.query_one(".execution-trace", Collapsible).collapsed
        await ask(app, pilot, "How many in total?")
        traces = list(app.query(".execution-trace"))
        assert len(traces) == 2 and traces[-1].collapsed
        assert app.query_one(".raw-diagnostics", Collapsible).collapsed


@pytest.mark.asyncio
async def test_failure_outcome_is_anchored_and_not_a_fake_result(tmp_path):
    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path, Answer(error="Gemini unavailable; retry later.")))
    async with app.run_test(size=(80, 24)) as pilot:
        await ask(app, pilot)
        headline = app.query_one(".answer-headline")
        viewport = app.query_one("#timeline").content_region
        assert viewport.y <= headline.region.y < viewport.bottom
        rendered = " ".join(str(widget.render()) for widget in app.query("Static"))
        assert "Gemini unavailable" in rendered
        assert not app.query(".result-table")
        assert app.query_one(".execution-trace").collapsed


@pytest.mark.asyncio
async def test_composer_grows_with_content_then_shrinks_after_submit(tmp_path):
    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one("#composer")
        async def wait_for_height(expected):
            # TextArea and resize/layout messages span multiple event cycles on
            # slow runners. Assert the settled state with a bounded deadline.
            deadline = asyncio.get_running_loop().time() + 5
            while composer.region.height != expected and asyncio.get_running_loop().time() < deadline:
                await pilot.pause(.01)
            assert composer.region.height == expected
        await wait_for_height(3)
        composer.text = "first\nsecond\nthird"
        await wait_for_height(5)
        composer.text = "\n".join(["a line"] * 12)
        await wait_for_height(7)
        await ask(app, pilot)
        await wait_for_height(3)
        assert composer.placeholder


@pytest.mark.asyncio
async def test_page_keys_scroll_history_from_the_composer(tmp_path):
    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        for index in range(3):
            await ask(app, pilot, f"Count request {index}")
        timeline = app.query_one("#timeline")
        bottom = timeline.scroll_y
        assert bottom > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert timeline.scroll_y < bottom
        previous = timeline.scroll_y
        await pilot.press("pagedown")
        await pilot.pause()
        assert timeline.scroll_y > previous
