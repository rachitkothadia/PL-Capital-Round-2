import json

import pytest
from test_tui_refinement import ReplyAgent, ask


def test_theme_preferences_are_bounded_and_corruption_safe(tmp_path):
    from pl_capital.tui.preferences import load_theme, save_theme

    assert load_theme(tmp_path) == "capital-dark"
    save_theme(tmp_path, "capital-light")
    path = tmp_path / "preferences.json"
    assert json.loads(path.read_text()) == {"theme": "capital-light", "version": 1}
    assert load_theme(tmp_path) == "capital-light"
    path.write_text("{broken")
    assert load_theme(tmp_path) == "capital-dark"
    path.write_text(json.dumps({"theme": "unregistered", "version": 1}))
    assert load_theme(tmp_path) == "capital-dark"
    with pytest.raises(ValueError, match="theme"):
        save_theme(tmp_path, "../../source")


def contrast(foreground, background):
    def luminance(color):
        values = [getattr(color, channel) / 255 for channel in ("r", "g", "b")]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(x * weight for x, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    first, second = sorted((luminance(foreground), luminance(background)))
    return (second + 0.05) / (first + 0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (160, 45)])
async def test_theme_changes_actual_widget_and_code_styles_and_restarts(tmp_path, size):
    from pl_capital.tui.app import CapitalApp

    agent = ReplyAgent(tmp_path)
    app = CapitalApp(agent)
    async with app.run_test(size=size) as pilot:
        await ask(app, pilot)
        app.action_toggle_trace()
        await pilot.pause()
        selectors = ["Screen", "#banner", "#composer", ".answer-card", ".execution-trace"]
        dark = {selector: (app.screen if selector == "Screen" else app.query_one(selector)).styles.background.hex for selector in selectors}
        code = app.query_one(".code-view")
        dark_code = code.render()._get_base_style().bgcolor
        await ask(app, pilot, "/theme light")
        light = {selector: (app.screen if selector == "Screen" else app.query_one(selector)).styles.background.hex for selector in selectors}
        assert all(dark[selector] != light[selector] for selector in selectors)
        assert code.render()._get_base_style().bgcolor != dark_code
        assert app.theme == "capital-light"
        for selector in ("Screen", "#composer", ".answer-headline"):
            widget = app.screen if selector == "Screen" else app.query_one(selector)
            assert contrast(widget.styles.color, widget.styles.background) >= 4.5
        await ask(app, pilot, "/theme dark")
        assert app.theme == "capital-dark"
        await ask(app, pilot, "/theme light")
    restarted = CapitalApp(ReplyAgent(tmp_path))
    async with restarted.run_test(size=size) as pilot:
        await pilot.pause()
        assert restarted.theme == "capital-light"


@pytest.mark.asyncio
async def test_theme_chooser_keyboard_mouse_and_escape(tmp_path):
    from pl_capital.tui.app import CapitalApp

    app = CapitalApp(ReplyAgent(tmp_path))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        assert app.screen.query("#theme-dialog")
        assert await pilot.click("#theme-light", offset=(2, 1))
        await pilot.pause()
        assert app.theme == "capital-light" and len(app.screen_stack) == 1
        await pilot.press("f2")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.theme == "capital-dark" and len(app.screen_stack) == 1
        await ask(app, pilot, "/theme")
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
