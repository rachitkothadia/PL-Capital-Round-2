import json

import pytest
from test_tui_refinement import ReplyAgent, ask

from pl_capital.clipboard import ClipboardOutcome
from pl_capital.models import Answer


class ClipboardSpy:
    def __init__(self, confirmed=True):
        self.confirmed = confirmed
        self.calls = []

    def copy_sql(self, answer, *, terminal_copy):
        self.calls.append(answer.executed_sql)
        terminal_copy(answer.executed_sql)
        return ClipboardOutcome(self.confirmed, "mock clipboard",
                                "SQL copied using mock clipboard." if self.confirmed else
                                "Clipboard confirmation unavailable. Use Show SQL or Save SQL.")


async def activate(app, pilot, selector, method):
    # Expansion and feedback can invalidate geometry after a worker completes.
    await pilot.pause()
    button = app.query_one(selector)
    button.focus(scroll_visible=False)
    await pilot.pause()
    button.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    if method == "mouse":
        assert await pilot.click(button, offset=(2, 1))
    else:
        await pilot.press("enter")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["mouse", "keyboard"])
async def test_copy_and_export_are_separate_exact_actions(tmp_path, method, monkeypatch):
    from pl_capital.tui.app import CapitalApp

    agent = ReplyAgent(tmp_path)
    agent.answer.sql = "SELECT * FROM portfolios /* proposed, never executed */"
    clipboard = ClipboardSpy()
    app = CapitalApp(agent, clipboard_service=clipboard)
    terminal_copies = []
    monkeypatch.setattr(app, "copy_to_clipboard", terminal_copies.append)
    async with app.run_test(size=(80, 24)) as pilot:
        await ask(app, pilot)
        await activate(app, pilot, ".copy-sql", method)
        assert clipboard.calls == [agent.answer.executed_sql]
        assert terminal_copies == [agent.answer.executed_sql]
        assert not list((agent.settings.cache_dir / "exports").glob("*.json"))
        await activate(app, pilot, ".export-answer", method)
        paths = list((agent.settings.cache_dir / "exports").glob("*.json"))
        assert len(paths) == 1
        exported = json.loads(paths[0].read_text())
        assert exported["question"] == "How many portfolios?"
        assert exported["sql"] == agent.answer.executed_sql
        assert exported["result"]["rows"] == [[13]]
        assert "assumptions" in exported and "source_dates" in exported


@pytest.mark.asyncio
async def test_unconfirmed_clipboard_reveals_manual_sql_and_safe_save(tmp_path):
    from pl_capital.tui.app import CapitalApp

    agent = ReplyAgent(tmp_path)
    app = CapitalApp(agent, clipboard_service=ClipboardSpy(confirmed=False))
    async with app.run_test(size=(100, 30)) as pilot:
        await ask(app, pilot)
        await activate(app, pilot, ".copy-sql", "keyboard")
        feedback = str(app.query_one(".action-feedback").render())
        assert "unavailable" in feedback.lower()
        assert not app.query_one(".execution-trace").collapsed
        assert app.query_one(".save-sql").display
        await activate(app, pilot, ".save-sql", "mouse")
        paths = list((agent.settings.cache_dir / "exports").glob("*.sql"))
        assert len(paths) == 1
        assert paths[0].read_text() == agent.answer.executed_sql + "\n"
        assert str(paths[0]) in str(app.query_one(".action-feedback").render())


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [Answer(intent="exposure_calculator", message="No equities"),
    Answer(error="Rejected SQL", sql="SELECT * FROM portfolios")])
async def test_copy_is_disabled_without_successfully_executed_sql(tmp_path, answer):
    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path, answer), clipboard_service=ClipboardSpy())
    async with app.run_test(size=(80, 24)) as pilot:
        await ask(app, pilot)
        assert app.query_one(".copy-sql").disabled
        assert not app.query_one(".export-answer").disabled
        assert "executed SQL" in str(app.query_one(".sql-unavailable").render())


@pytest.mark.asyncio
async def test_copy_export_shortcuts_and_debug_are_real_controls(tmp_path, monkeypatch):
    from pl_capital.tui.app import CapitalApp

    clipboard = ClipboardSpy()
    agent = ReplyAgent(tmp_path)
    app = CapitalApp(agent, clipboard_service=clipboard)
    monkeypatch.setattr(app, "copy_to_clipboard", lambda _sql: None)
    async with app.run_test(size=(120, 35)) as pilot:
        await ask(app, pilot)
        await pilot.press("f6")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert clipboard.calls == [agent.answer.executed_sql]
        await pilot.press("f7")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(list((agent.settings.cache_dir / "exports").glob("*.json"))) == 1
        assert app.query_one(".raw-diagnostics").collapsed
        await ask(app, pilot, "/debug")
        assert not app.query_one(".raw-diagnostics").collapsed


@pytest.mark.asyncio
async def test_export_failure_is_visible_without_claiming_a_saved_file(tmp_path):
    from pl_capital.errors import CapitalError
    from pl_capital.tui.app import CapitalApp

    class FailingExport:
        def export_answer(self, _answer):
            raise CapitalError("Export directory permission denied.")

    app = CapitalApp(ReplyAgent(tmp_path), export_service=FailingExport())
    async with app.run_test(size=(80, 24)) as pilot:
        await ask(app, pilot)
        await activate(app, pilot, ".export-answer", "keyboard")
        feedback = str(app.query_one(".action-feedback").render())
        assert "permission denied" in feedback
        assert "exported to" not in feedback.lower()
