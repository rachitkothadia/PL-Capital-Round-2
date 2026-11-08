"""Full bounded results stay navigable without squeezing identifiers into letters."""

import copy

import pytest
from test_tui_refinement import ReplyAgent, ask
from textual.widgets import DataTable

from pl_capital.models import Answer
from pl_capital.tui.app import CapitalApp


def historical_answer(count=13):
    columns = ["portfolio_name", "date", "previous_nav", "nav", "nav_change",
               "nav_change_pct", "previous_sharpe_ratio", "sharpe_ratio_change",
               "previous_beta", "beta_change", "previous_var", "var_change", "note"]
    rows = [["Conservative Income Fund" if i == 0 else f"Portfolio number {i:03d}",
             "2023-09-27", 108.45, 108.62, .17, .1567542646, 1.58, -.02,
             .36, .01, 2.4, None, "A long note " * 10] for i in range(count)]
    return Answer(intent="sql_query", tool="sql_query", currency="USD",
                  executed_sql="SELECT * FROM portfolio_performance",
                  result={"columns": columns, "rows": rows, "row_count": count})


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [80, 110, 160])
async def test_wide_table_keeps_every_row_column_and_keyboard_detail(tmp_path, width):
    from pl_capital.tui.widgets import FullTableScreen, RecordDetailScreen, ResultTable

    answer = historical_answer(213)
    original = copy.deepcopy(answer.result)
    app = CapitalApp(ReplyAgent(tmp_path, answer))
    async with app.run_test(size=(width, 32)) as pilot:
        await ask(app, pilot)
        grid = app.query_one(ResultTable)
        assert isinstance(grid, DataTable)
        assert grid.row_count == 213 and len(grid.columns) == 13
        assert grid.fixed_columns == 1 and grid.header_height == 1
        assert all(row.height == 1 for row in grid.rows.values())
        assert all(column.width >= 8 for column in grid.columns.values())
        assert grid.get_row_at(0)[0].plain == "Conservative Income Fund"
        assert grid.get_row_at(0)[1].plain == "2023-09-27"
        assert grid.max_scroll_x > 0
        grid.focus()
        await pilot.press("right", "right", "down")
        await pilot.pause()
        assert grid.scroll_x > 0 and grid.cursor_row == 1
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RecordDetailScreen)
        details = " ".join(str(w.render()) for w in app.screen.query(".record-field"))
        assert "previous_sharpe_ratio" in details and "var_change" in details
        assert "A long note " * 10 in details
        fields = app.screen.query_one(".record-fields")
        await pilot.press("pagedown")
        await pilot.pause()
        assert fields.scroll_y > 0
        await pilot.press("escape")
        card = app.query_one(".answer-card")
        card.open_full_table()
        await pilot.pause()
        assert isinstance(app.screen, FullTableScreen)
        full = app.screen.query_one(ResultTable)
        assert full.row_count == 213 and len(full.columns) == 13
        full.focus()
        await pilot.press("ctrl+end")
        await pilot.pause()
        assert full.scroll_y > 0
        await pilot.press("escape")
        assert answer.result == original
        assert not grid.get_row_at(0)[2].plain.startswith("$")


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 13])
async def test_full_table_preserves_nulls_sort_and_json_export(tmp_path, count):
    import json

    from pl_capital.tui.widgets import ResultTable

    answer = historical_answer(count)
    original = copy.deepcopy(answer.result)
    app = CapitalApp(ReplyAgent(tmp_path, answer))
    async with app.run_test(size=(80, 26)) as pilot:
        await ask(app, pilot)
        if count:
            grid = app.query_one(ResultTable)
            assert grid.row_count == count
            assert grid.get_row_at(0)[11].plain in {"Not available", "N/A"}
            assert "nav_change_pct" in grid.column_names
        else:
            assert not app.query(ResultTable)
        await app.query_one(".answer-card").export_answer()
        saved = next((tmp_path / "cache" / "exports").glob("*.json"))
        assert json.loads(saved.read_text())["result"] == original
        assert answer.result == original


@pytest.mark.asyncio
async def test_full_table_mouse_button_resize_and_page_keys_stay_in_grid(tmp_path):
    from ui_test_helpers import settle_button

    from pl_capital.tui.widgets import FullTableScreen, ResultTable

    app = CapitalApp(ReplyAgent(tmp_path, historical_answer(213)))
    async with app.run_test(size=(80, 24)) as pilot:
        await ask(app, pilot)
        button = app.query_one(".full-table")
        await settle_button(pilot, button)
        assert await pilot.click(button, offset=(2, 1))
        await pilot.pause()
        assert isinstance(app.screen, FullTableScreen)
        grid = app.screen.query_one(ResultTable)
        assert app.focused is grid
        await pilot.press("pagedown")
        await pilot.pause()
        assert grid.cursor_row > 0
        await pilot.press("f7")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert len(list((tmp_path / "cache" / "exports").glob("*.json"))) == 1
        await pilot.resize_terminal(160, 40)
        await pilot.pause()
        assert grid.row_count == 213 and len(grid.columns) == 13
        assert grid.content_size.width > 100
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert grid.content_size.width < 80
        assert grid.max_scroll_x > 0
        assert all(row.height == 1 for row in grid.rows.values())
        close = app.screen.query_one(".close-table")
        await settle_button(pilot, close)
        assert await pilot.click(close, offset=(2, 1))
        await pilot.pause()
        assert not isinstance(app.screen, FullTableScreen)
