import asyncio
import json
import re

from rich import box
from rich.cells import cell_len
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Collapsible, Markdown, Static, TextArea

from pl_capital.clipboard import eligible_sql
from pl_capital.errors import CapitalError
from pl_capital.models import Answer


def plain(value: object, limit: int = 2000) -> str:
    """Treat dataset/model strings as text, including terminal control sequences."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", str(value))
    return re.sub(r"(?:gsk_|gh[pousr]_|sk-proj-)[A-Za-z0-9_-]{20,}", "[credential redacted]", text)[:limit]


def safe_json(value: object) -> str:
    """Bound audit metadata and suppress credentials even if an upstream tool errs."""
    def clean(item, depth=0):
        if depth > 6:
            return "[depth limit]"
        if isinstance(item, dict):
            return {plain(k, 80): "[redacted]" if any(
                word in str(k).lower().replace("-", "_")
                for word in ("api_key", "authorization", "password", "secret")
            ) or str(k).lower() == "token" else clean(v, depth + 1)
                    for k, v in list(item.items())[:40]}
        if isinstance(item, (list, tuple)):
            return [clean(v, depth + 1) for v in item[:40]]
        return plain(item, 3000) if isinstance(item, str) else item

    return plain(json.dumps(clean(value), indent=2, ensure_ascii=True, default=str), 12000)


class Composer(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "Send", priority=True),
        Binding("shift+enter", "newline", "Newline", priority=True),
        Binding("ctrl+j", "newline", "Newline", priority=True),
    ]

    class Submitted(Message):
        def __init__(self, text: str):
            self.text = text
            super().__init__()

    def action_submit(self) -> None:
        text = self.text.strip()
        if text:
            self.text = ""
            self.post_message(self.Submitted(text))

    def action_newline(self) -> None:
        self.insert("\n")

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        self._fit_height()

    def on_resize(self) -> None:
        self._fit_height()

    def _fit_height(self) -> None:
        width = max(1, self.content_size.width)
        lines = sum(max(1, (cell_len(line) + width - 1) // width) for line in self.document.lines)
        self.styles.height = min(7, max(3, lines + 2))


class CodeView(Static):
    def __init__(self, code: str, language: str = "sql", *, classes: str = ""):
        super().__init__(classes="code-view " + classes)
        self.code = plain(code, 30000)
        self.language = language
        self.syntax_theme_name = "monokai"
        self.syntax = Syntax(self.code, self.language, theme=self.syntax_theme_name, word_wrap=True)

    def render(self):
        return self.syntax

    def on_mount(self) -> None:
        self.apply_theme(self.app.current_theme)

    def apply_theme(self, theme) -> None:
        self.syntax_theme_name = "monokai" if theme.dark else "friendly"
        self.syntax = Syntax(
            self.code, self.language, theme=self.syntax_theme_name, word_wrap=True,
            background_color=theme.panel or theme.surface or theme.background,
            padding=(0, 1),
        )
        self.refresh(layout=True)


class ResultTable(Static):
    """A compact, wrapping table shares the conversation's single scrollbar."""

    def __init__(self, table_view):
        super().__init__(classes="result-table")
        self.table_view = table_view

    def render(self):
        table = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, padding=(0, 1))
        for column in self.table_view.columns:
            table.add_column(Text(plain(column, 120)), header_style="bold", overflow="fold")
        for row in self.table_view.rows[:8]:
            table.add_row(*[Text(plain(value, 300)) for value in row])
        if self.table_view.total_rows > 8:
            table.caption = f"First 8 of {self.table_view.total_rows} returned rows; export includes the bounded full result."
        elif self.table_view.truncated:
            table.caption = "Query result reached its row cap; narrow the request."
        return table


class AnswerCard(Vertical):
    def __init__(self, answer: Answer):
        from pl_capital.presentation import build_answer_view

        super().__init__(classes="answer-card")
        self.answer = answer
        self.view = build_answer_view(answer)

    def compose(self) -> ComposeResult:
        yield Static(plain(self.view.headline, 400), classes="answer-headline", markup=False)
        if self.view.table:
            if "sectors" in self.answer.result:
                with Vertical(classes="exposure-card"):
                    yield ResultTable(self.view.table)
                    result = self.answer.result
                    yield Static(
                        f"Equity weight {result.get('equity_weight_total', '—')} · "
                        f"Bond weight {result.get('bond_weight_total', '—')} · "
                        f"Recorded total {result.get('all_recorded_weights_total', '—')}\n"
                        f"{result.get('equity_holding_count', 0)} stock holdings · "
                        f"{result.get('bond_exclusion_count', 0)} bond holdings excluded",
                        classes="exposure-totals", markup=False,
                    )
            else:
                yield ResultTable(self.view.table)
        if self.view.message:
            yield Markdown(plain(self.view.message, 1800), classes="answer-body", open_links=False)
        yield Static("How this was calculated", classes="explanation-title", markup=False)
        for step in self.view.steps[:5]:
            yield Static("• " + plain(step, 700), classes="explanation-step", markup=False)
        yield Static(plain(self.view.provenance, 900), classes="provenance", markup=False)
        for warning in self.view.warnings:
            yield Static("Note: " + plain(warning, 700), classes="answer-warning", markup=False)
        sql = self._eligible_sql()
        with Horizontal(classes="answer-actions"):
            yield Button("Copy SQL", classes="copy-sql", disabled=not sql,
                         tooltip="Copy exact executed SQL." if sql else "No safe executed SQL is available.")
            yield Button("Export answer", classes="export-answer")
            yield Button("Save SQL", classes="save-sql")
        if not sql:
            yield Static("Copy SQL requires safe, successfully executed SQL.", classes="sql-unavailable", markup=False)
        yield Static("", classes="action-feedback", markup=False)
        with Collapsible(title="Execution details", collapsed=True, classes="execution-trace"):
            for section in self.view.sections:
                with Collapsible(title=plain(section.title, 100), collapsed=True, classes="evidence-section"):
                    for line in section.lines:
                        yield Static(plain(line, 1500), classes="trace-detail", markup=False)
                    if section.code:
                        yield CodeView(section.code, section.language,
                                       classes="executed-sql" if section.code == getattr(self.answer, "executed_sql", None) else "")
            with Collapsible(title="Raw diagnostics / JSON (redacted, bounded)", collapsed=True, classes="raw-diagnostics"):
                from pl_capital.presentation import diagnostic_payload

                yield CodeView(safe_json(diagnostic_payload(self.answer,
                    secret=getattr(self.app.agent.settings, "api_key", ""))), "json", classes="raw-json")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"copy-sql": self.copy_sql, "export-answer": self.export_answer, "save-sql": self.save_sql}
        for name, callback in actions.items():
            if event.button.has_class(name):
                event.stop()
                self.app.run_worker(callback(), name=name, group="answer-actions")
                return

    def _eligible_sql(self) -> str | None:
        return eligible_sql(self.answer, getattr(self.app.agent.settings, "api_key", ""))

    def _feedback(self, message: str) -> None:
        feedback = self.query_one(".action-feedback", Static)
        feedback.update(plain(message, 3000))
        feedback.display = True

    def show_sql(self) -> None:
        if not self.query(".executed-sql"):
            return
        parent = self.query_one(".executed-sql").parent
        while parent is not None and parent is not self:
            if isinstance(parent, Collapsible):
                parent.collapsed = False
            parent = parent.parent

    async def copy_sql(self) -> None:
        if not self._eligible_sql():
            self._feedback("No safe executed SQL is available for this answer.")
            return
        try:
            outcome = await asyncio.to_thread(
                self.app.clipboard_service.copy_sql, self.answer,
                terminal_copy=lambda sql: self.app.call_from_thread(self.app.copy_to_clipboard, sql),
            )
            self._feedback(outcome.message)
            if not outcome.confirmed:
                self.query_one(".save-sql", Button).display = True
                self.show_sql()
        except CapitalError as exc:
            self._feedback(str(exc))
        except Exception:
            self._feedback("Clipboard is unavailable. Use the displayed SQL or Save SQL.")
            self.query_one(".save-sql", Button).display = True
            self.show_sql()

    async def export_answer(self) -> None:
        try:
            path = await asyncio.to_thread(self.app.export_service.export_answer, self.answer)
            self._feedback(f"Answer exported to {path}")
        except CapitalError as exc:
            self._feedback(str(exc))
        except Exception:
            self._feedback("Answer export failed safely; check the configured cache directory.")

    async def save_sql(self) -> None:
        try:
            path = await asyncio.to_thread(self.app.export_service.save_sql, self.answer)
            self._feedback(f"Executed SQL saved to {path}")
        except CapitalError as exc:
            self._feedback(str(exc))
        except Exception:
            self._feedback("SQL export failed safely; check the configured cache directory.")
