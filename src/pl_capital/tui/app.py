import asyncio
from collections.abc import Iterable

from textual import on
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Collapsible, DataTable, Footer, LoadingIndicator, Markdown, Static

from pl_capital.clipboard import ClipboardService
from pl_capital.config import MODELS
from pl_capital.errors import CapitalError
from pl_capital.exporting import ExportService
from pl_capital.models import Answer
from pl_capital.tui.preferences import THEMES, load_theme, save_theme
from pl_capital.tui.themes import DARK_THEME, LIGHT_THEME, ThemeChooser
from pl_capital.tui.widgets import AnswerCard, CodeView, Composer, plain

HELP = """## Portfolio workspace
Ask descriptive questions about the supplied historical portfolio snapshot.

**Enter** sends · **Ctrl+J** or **Shift+Enter** inserts a newline · **Ctrl+P** opens commands.

`/help` — show this guide  
`/new` — start a fresh session and reset follow-up context  
`/clear` — clear current conversation and context  
`/sessions` — list this run's sessions  
`/model [model ID]` — inspect or switch the active model planner

`/graph` — inspect actual graph backend and fallback reason  
`/trace` — expand or collapse recorded execution events  
`/eval` — run all supplied questions through the live agent  
`/theme` — choose a theme; `/theme dark` or `/theme light` applies it  
`/copy` or **F6** — copy exact executed SQL, or the scenario calculation  
`/export` or **F7** — export the latest answer as private JSON  
`/debug` — explicitly toggle the latest answer's raw diagnostics  
`/quit` or `:q` — exit

**PageUp / PageDown** scroll the conversation. **F2** opens the theme chooser.

SQL and scenario tables: **← / →** scroll columns, **↑ / ↓** select a record,
**Enter** opens every field and scenario sector exposures. **Full Table** opens a
larger view; **Esc** closes it. All returned rows remain available in the table and export.

Extra capability: ask for a **hypothetical scenario** with named sector shocks,
for example Technology down 22%, Energy up 11%, Financials down 7%, other equities
and bonds unchanged. The deterministic calculator uses the supplied historical prices.

No live prices or personal investment recommendations. Session history stays in memory and ends when the app closes.
"""


class CapitalApp(App):
    TITLE = "PL Capital | Portfolio workspace"
    CSS_PATH = "styles.tcss"
    COMMAND_PALETTE_BINDING = "ctrl+p"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "new_session", "New session"),
        Binding("f1", "help", "Help"),
        Binding("ctrl+t", "toggle_trace", "Trace", priority=True),
        Binding("f2", "choose_theme", "Theme", priority=True),
        Binding("f6", "copy_sql", "Copy", priority=True),
        Binding("f7", "export_answer", "Export", priority=True),
        Binding("pageup", "timeline_up", "Scroll up", priority=True, show=False),
        Binding("pagedown", "timeline_down", "Scroll down", priority=True, show=False),
    ]

    def __init__(self, agent, *, clipboard_service=None, export_service=None):
        super().__init__()
        self.agent = agent
        self.clipboard_service = clipboard_service or ClipboardService(agent.settings)
        self.export_service = export_service or ExportService(agent.settings)
        self.busy = False
        self.sessions = ["Session 1"]
        self.turn_count = 0
        self.trace_expanded = False
        self.session_number = 1
        self.preferences_dir = getattr(agent.settings, "config_dir", None) or agent.settings.cache_dir / "preferences"

    def compose(self) -> ComposeResult:
        yield Static("PL CAPITAL  /  portfolio workspace", id="banner", markup=False)
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Static("WORKSPACE", classes="section-title")
                yield Static("Historical snapshot\nSQLite authoritative\nModel interpretation", markup=False)
                yield Static("TOOLS", classes="section-title")
                yield Static("SQL query\nSector exposure\nGround truth evaluator\nScenario analysis (extra)", markup=False)
                yield Static("SESSIONS", classes="section-title")
                yield Static("Session 1", id="session-list", markup=False)
                yield Static("/help for commands", classes="muted", markup=False)
            with Vertical(id="main"):
                with VerticalScroll(id="timeline"):
                    yield Markdown(
                        "# Your portfolio, explained.\n\nAsk a question. Inspect the evidence.\n\n"
                        "Try: **How many portfolios do we have?**\n\n"
                        "Or: **Sector exposure for international equity**",
                        id="welcome", open_links=False,
                    )
                yield LoadingIndicator(id="loading")
                yield Composer(id="composer", soft_wrap=True, show_line_numbers=False,
                               placeholder="Ask about the supplied portfolios…")
                yield Static("Enter send · Ctrl+J newline · Ctrl+P commands", id="composer-hint")
            with Vertical(id="inspector"):
                yield Static("CONTEXT", classes="section-title")
                yield Static(self.agent.settings.model, id="model-status", markup=False)
                yield Static("SOURCE", classes="section-title")
                yield Static("Supplied CSV snapshot\nNo live pricing\nRead-only analytics", markup=False)
                yield Static("BOUNDARIES", classes="section-title")
                yield Static("Bound SQL parameters\nValidated SELECT only\nDeterministic calculations", markup=False)
                yield Static("Graph status: /graph", classes="muted", markup=False)
        yield Static("READY  ·  Local data, auditable answers", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(DARK_THEME)
        self.register_theme(LIGHT_THEME)
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        self.theme = load_theme(self.preferences_dir)
        self.query_one("#loading").display = False
        self.query_one("#composer").focus()
        self._resize_panels(self.size.width)

    def on_resize(self, event) -> None:
        if self.is_mounted and self.query("#sidebar"):
            self._resize_panels(event.size.width)

    def _resize_panels(self, width: int) -> None:
        self.query_one("#sidebar").display = width >= 120
        self.query_one("#inspector").display = width >= 160

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("New portfolio session", "Clear context and start again", self.action_new_session)
        yield SystemCommand("Portfolio help", "Show keyboard shortcuts and commands", self.action_help)
        yield SystemCommand("Graph backend status", "Inspect graph usage or SQLite fallback", self.action_graph)
        yield SystemCommand("Clear portfolio conversation", "Remove current messages and context", self.action_clear)
        yield SystemCommand("Toggle execution traces", "Expand or collapse actual operational events", self.action_toggle_trace)
        yield SystemCommand("Run live ground truth evaluation", "Call the active provider for all supplied questions", self.action_evaluate)
        yield SystemCommand("Choose portfolio theme", "Switch between readable dark and light palettes", self.action_choose_theme)
        yield SystemCommand("Portfolio theme: dark", "Apply the restrained dark palette", self.action_theme_dark)
        yield SystemCommand("Portfolio theme: light", "Apply the bright light palette", self.action_theme_light)
        yield SystemCommand("Copy latest calculation or SQL", "Copy scenario calculation or exact executed SQL", self.action_copy_sql)
        yield SystemCommand("Export latest answer", "Save safe JSON in the private application cache", self.action_export_answer)

    async def _append(self, widget) -> None:
        timeline = self.query_one("#timeline", VerticalScroll)
        await timeline.mount(widget)
        while len(timeline.children) > 100:
            await timeline.children[0].remove()
        if isinstance(widget, AnswerCard):
            self.call_after_refresh(timeline.scroll_to_widget, widget, top=True, animate=False, immediate=True)
        else:
            timeline.scroll_end(animate=False)

    async def _notice(self, text: str) -> None:
        await self._append(Markdown(text, classes="notice", open_links=False))

    @on(Composer.Submitted)
    async def submitted(self, event: Composer.Submitted) -> None:
        event.stop()
        if self.busy:
            self.query_one("#composer", Composer).text = event.text
            await self._notice("An analysis is running. Your next question remains in the composer.")
            return
        if event.text.startswith("/") or event.text == ":q":
            try:
                await self._command(event.text)
            except CapitalError as exc:
                await self._notice(plain(exc))
            return
        if len(event.text) > 4000:
            await self._notice("Keep questions under 4,000 characters.")
            return
        await self._append(Static("YOU\n" + plain(event.text, 4000), classes="user-card", markup=False))
        self.busy = True
        self.query_one("#loading").display = True
        self.query_one("#status", Static).update("WORKING  ·  Interpreting question and running validated analytics")
        self.run_worker(self._answer(event.text), name="portfolio-answer", group="analysis")

    async def _answer(self, question: str) -> None:
        try:
            answer = await asyncio.to_thread(self.agent.answer_question, question)
            self.turn_count += 1
            await self._append(AnswerCard(answer))
            status = getattr(answer, "status", "tool_error" if answer.error else "success")
            self.query_one("#status", Static).update(
                f"{status.replace('_', ' ').upper()}  ·  "
                f"{answer.tool or answer.intent}  ·  {answer.elapsed_ms:.0f} ms"
            )
        except CapitalError as exc:
            await self._append(AnswerCard(Answer(error=plain(exc))))
            self.query_one("#status", Static).update("ACTION NEEDED  ·  Analysis could not complete")
        except Exception:
            await self._append(AnswerCard(Answer(error="Analysis could not complete. Check configuration with pl-capital doctor and retry.")))
            self.query_one("#status", Static).update("ACTION NEEDED  ·  Analysis could not complete")
        finally:
            self.busy = False
            self.query_one("#loading").display = False
            self.query_one("#composer").focus()

    async def _command(self, text: str) -> None:
        command, _, argument = text.partition(" ")
        if command in {"/quit", ":q"}:
            self.exit()
        elif command == "/help":
            await self.action_help()
        elif command == "/new":
            await self.action_new_session()
        elif command == "/clear":
            await self.action_clear()
        elif command == "/sessions":
            await self._notice("## Sessions this run\n\n" + "\n\n".join(self.sessions) + "\n\nOnly the current session's follow-up context is active.")
        elif command == "/model":
            if not argument.strip():
                await self._notice("Current model: `" + self.agent.settings.model + "`\n\nAvailable: " + ", ".join(f"`{m}`" for m in MODELS))
            elif argument.strip() in MODELS:
                self.agent.set_model(argument.strip())
                self.query_one("#model-status", Static).update(self.agent.settings.model)
                await self._notice("Planner switched to `" + self.agent.settings.model + "`.")
            else:
                await self._notice("Choose one of the documented Gemini model IDs with /model.")
        elif command == "/graph":
            await self.action_graph()
        elif command == "/trace":
            self.action_toggle_trace()
        elif command == "/eval":
            self.action_evaluate()
        elif command == "/theme":
            if not argument.strip():
                self.action_choose_theme()
            elif argument.strip().lower() in THEMES:
                self._set_theme(argument.strip().lower())
            else:
                await self._notice("Choose `/theme dark` or `/theme light`, or press F2 for the chooser.")
        elif command == "/copy":
            self.action_copy_sql()
        elif command == "/export":
            self.action_export_answer()
        elif command == "/debug":
            self.action_toggle_debug()
        else:
            await self._notice("Unknown command. Type /help for working commands.")

    async def action_help(self) -> None:
        await self._notice(HELP)

    async def action_clear(self) -> None:
        if self.busy:
            return
        await self.query_one("#timeline", VerticalScroll).remove_children()
        self.agent.reset_context()
        await self._notice("Conversation cleared. Follow-up context reset.")

    async def action_new_session(self) -> None:
        if self.busy:
            return
        self.session_number += 1
        self.sessions.append(f"Session {self.session_number}")
        self.sessions = self.sessions[-10:]
        await self.action_clear()
        self.query_one("#session-list", Static).update("\n".join(self.sessions[-5:]))

    async def action_graph(self) -> None:
        check = getattr(self.agent.graph, "health", self.agent.graph.status)
        status = await asyncio.to_thread(check)
        details = []
        for key in ("native_ready", "import_ok", "package_version", "python_version", "platform", "architecture",
                    "sync_status", "snapshot_id", "schema_version", "graph_used", "startup_ms"):
            if key in status:
                details.append(f"**{key.replace('_', ' ').title()}:** {plain(status[key], 200)}")
        if counts := status.get("counts"):
            details.append("**Grounded graph counts:** " + ", ".join(f"{plain(key)} {plain(value)}" for key, value in counts.items()))
        if sample := status.get("sample_cypher"):
            details.append("**Actual sample Cypher:** `" + plain(sample.get("query", ""), 500) + "`")
            details.append("**Sample results:** " + plain(sample.get("rows", []), 1500))
        if retrieval := status.get("sample_retrieval"):
            details.append(f"**Sample graph context used:** {bool(retrieval.get('used'))}")
            details.append("**Matched entities:** " + plain(retrieval.get("entities", []), 1000))
        await self._notice("## Graph backend\n\n" + plain(status.get("backend", "unknown")) +
                           " — " + plain(status.get("status", "status unavailable")) +
                           "\n\n" + plain(status.get("reason", "No backend explanation recorded.")) +
                           ("\n\n" + "\n\n".join(details) if details else ""))

    def _latest_answer(self):
        for screen in reversed(self.screen_stack):
            if cards := list(screen.query(AnswerCard)):
                return cards[-1]
        self.notify("Ask a question first.")
        return None

    def action_copy_sql(self) -> None:
        if card := self._latest_answer():
            self.run_worker(card.copy_sql(), name="copy-sql", group="answer-actions")

    def action_export_answer(self) -> None:
        if card := self._latest_answer():
            self.run_worker(card.export_answer(), name="export-answer", group="answer-actions")

    def action_toggle_debug(self) -> None:
        if card := self._latest_answer():
            debug = card.query_one(".raw-diagnostics", Collapsible)
            debug.collapsed = not debug.collapsed
            if not debug.collapsed:
                card.query_one(".execution-trace", Collapsible).collapsed = False

    def action_timeline_up(self) -> None:
        if isinstance(self.focused, (DataTable, VerticalScroll)):
            self.focused.action_page_up()
            return
        timeline = self.query_one("#timeline", VerticalScroll)
        timeline.scroll_relative(y=-max(1, timeline.content_size.height - 2), animate=False, immediate=True)

    def action_timeline_down(self) -> None:
        if isinstance(self.focused, (DataTable, VerticalScroll)):
            self.focused.action_page_down()
            return
        timeline = self.query_one("#timeline", VerticalScroll)
        timeline.scroll_relative(y=max(1, timeline.content_size.height - 2), animate=False, immediate=True)

    def _theme_changed(self, theme) -> None:
        for widget in self.query(CodeView):
            widget.apply_theme(theme)
        if theme.name in THEMES.values():
            try:
                save_theme(self.preferences_dir, theme.name)
            except OSError:
                self.notify("Theme applied for this run; preference could not be saved.", severity="warning")

    def _set_theme(self, choice: str | None) -> None:
        if choice in THEMES:
            self.theme = THEMES[choice]

    def action_choose_theme(self) -> None:
        self.push_screen(ThemeChooser(), self._set_theme)

    def action_theme_dark(self) -> None:
        self._set_theme("dark")

    def action_theme_light(self) -> None:
        self._set_theme("light")

    def action_toggle_trace(self) -> None:
        traces = list(self.query(".execution-trace"))
        self.trace_expanded = not any(not trace.collapsed for trace in traces) if traces else not self.trace_expanded
        for trace in traces:
            if isinstance(trace, Collapsible):
                trace.collapsed = not self.trace_expanded

    def action_evaluate(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.query_one("#loading").display = True
        self.query_one("#status", Static).update("LIVE EVALUATION  ·  Running the supplied questions through the active provider")
        self.run_worker(self._evaluate(), name="live-evaluation", group="analysis")

    async def _evaluate(self) -> None:
        try:
            from pl_capital.evaluator import evaluate

            report = self.agent.settings.cache_dir / "evaluation.json"
            result = await asyncio.to_thread(evaluate, self.agent, self.agent.settings.data_root,
                                            report=report, live=True)
            await self._notice(
                f"## Live ground truth evaluation\n\n**{result['passed']}/{result['total']} passed**. "
                "Each question ran through the real agent; expected values were derived independently.\n\n"
                "Full report: application cache / `evaluation.json`."
            )
            self.query_one("#status", Static).update(f"READY  ·  Live evaluation: {result['passed']}/{result['total']} passed")
        except CapitalError as exc:
            await self._notice("Live evaluation could not complete: " + plain(exc))
        except Exception:
            await self._notice("Live evaluation could not complete. Check provider configuration with pl-capital doctor and retry.")
        finally:
            self.busy = False
            self.query_one("#loading").display = False
            self.query_one("#composer").focus()
