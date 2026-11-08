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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, DataTable, Markdown, Static, TextArea

from pl_capital.clipboard import eligible_sql
from pl_capital.errors import CapitalError
from pl_capital.models import Answer


def plain(value: object, limit: int = 2000) -> str:
    """Treat dataset/model strings as text, including terminal control sequences."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", str(value))
    return re.sub(r"(?:gsk_|gh[pousr]_|sk-proj-|AIza|AQ\.)[A-Za-z0-9_-]{20,}", "[credential redacted]", text)[:limit]


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


COMPACT_HEADINGS = {
    "portfolio_name": "Portfolio", "currency": "CCY", "date": "Date",
    "previous_nav": "Prev NAV", "prev_nav": "Prev NAV", "current_nav": "NAV", "nav": "NAV",
    "nav_change": "Δ NAV", "nav_difference": "Δ NAV", "nav_change_pct": "NAV %",
    "previous_sharpe_ratio": "Prev Sharpe", "prev_sharpe_ratio": "Prev Sharpe",
    "sharpe_ratio": "Sharpe", "sharpe_ratio_change": "Δ Sharpe", "sharpe_change": "Δ Sharpe",
    "previous_beta": "Prev β", "prev_beta": "Prev β", "beta_change": "Δ β", "beta": "β",
    "previous_var": "Prev VaR", "prev_var": "Prev VaR", "var_change": "Δ VaR", "var": "VaR",
    "pre_portfolio_value": "Before", "post_portfolio_value": "After", "portfolio_pnl": "P&L",
    "portfolio_return_pct": "Return", "equity_return_pct": "Equity return", "top_loss_sector": "Worst sector",
}


def _cell_text(value: object) -> str:
    # Keep the full display value for record detail; the grid uses a single line.
    return plain(value, max(3000, len(str(value))))


class ResultTable(DataTable):
    """All bounded rows, fixed-height cells and native horizontal navigation.

    `source_result` is read only. Stable row keys retain the returned ordering and
    map selection back to the exact record, regardless of horizontal scrolling.
    """

    def __init__(self, table_view, source_result=None, *, currency=None, fullscreen=False):
        super().__init__(classes="result-table", cursor_type="row", zebra_stripes=True,
                         show_row_labels=False, header_height=1)
        from pl_capital.presentation import format_cell

        self.table_view = table_view
        self.source_result = source_result or {}
        self.fullscreen = fullscreen
        self.column_names = list(getattr(table_view, "full_columns", None) or
                                 self.source_result.get("columns") or table_view.columns)
        full_rows = getattr(table_view, "full_rows", None)
        if full_rows:
            self.display_rows = full_rows
        elif "columns" in self.source_result:
            self.display_rows = [[format_cell(value, column, currency=currency)
                for column, value in zip(self.column_names, row, strict=True)]
                for row in self.source_result.get("rows", [])]
        else:
            self.display_rows = table_view.rows
        self.headings = [COMPACT_HEADINGS.get(name.lower().replace(" ", "_"),
                         str(name).replace("_", " ")) for name in self.column_names]
        self.styles.height = "1fr" if fullscreen else min(11, max(3, len(self.display_rows) + 2))
        self.tooltip = "←/→ scroll columns · ↑/↓ select record · Enter opens all fields · Tab leaves the table"

    @property
    def legend(self) -> str:
        return " · ".join(f"{heading} = {name}" for heading, name in
                          zip(self.headings, self.column_names, strict=True) if heading != name)

    def on_mount(self) -> None:
        for index, (heading, name) in enumerate(zip(self.headings, self.column_names, strict=True)):
            values = [cell_len(_cell_text(row[index]).replace("\n", " "))
                      for row in self.display_rows if index < len(row)]
            identifier = index == 0 and any(word in name.lower() for word in ("name", "portfolio", "sector", "id"))
            width = min(38 if identifier else 44, max(10, cell_len(heading), max(values, default=0)))
            self.add_column(Text(_cell_text(heading), no_wrap=True), width=width, key=str(index))
        self.fixed_columns = int(bool(self.column_names) and any(
            word in self.column_names[0].lower() for word in ("name", "portfolio", "sector", "id")))
        for index, row in enumerate(self.display_rows):
            cells = []
            for _column, value in zip(self.column_names, row, strict=True):
                text = _cell_text(value).replace("\n", " ").replace("\t", " ")
                # Values are already formatted by the presentation layer.
                numeric = bool(re.match(r"^[+−-]?\$?[+−-]?[\d,.]+(?:%| pp)?$", text))
                cells.append(Text(text, no_wrap=True, overflow="ellipsis", justify="right" if numeric else "left"))
            self.add_row(*cells, key=str(index), height=1)

    def render(self):
        """Readable noninteractive representation; Textual draws via render_lines."""
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, padding=(0, 1))
        for heading in self.headings:
            table.add_column(Text(_cell_text(heading)), no_wrap=True)
        for row in self.display_rows:
            table.add_row(*[Text(_cell_text(value), no_wrap=True) for value in row])
        return table

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.app.push_screen(RecordDetailScreen(self, int(event.row_key.value)))


class RecordDetailScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Close", priority=True)]

    def __init__(self, table: ResultTable, index: int):
        super().__init__()
        self.table = table
        self.index = index

    def compose(self) -> ComposeResult:
        with Vertical(classes="table-dialog record-dialog"):
            yield Static(f"Record {self.index + 1} of {len(self.table.display_rows)} · full fields",
                         classes="dialog-title", markup=False)
            with VerticalScroll(classes="record-fields"):
                for name, value in zip(self.table.column_names, self.table.display_rows[self.index], strict=True):
                    yield Static(f"{_cell_text(name)}\n{_cell_text(value)}", classes="record-field", markup=False)
                portfolio_name = str(self.table.display_rows[self.index][0])
                for portfolio in self.table.source_result.get("portfolios", []):
                    if portfolio.get("portfolio_name") != portfolio_name:
                        continue
                    for sector in portfolio.get("sectors", []):
                        yield Static("\n".join(f"{_cell_text(key)}: {_cell_text(value)}" for key, value in sector.items()),
                                     classes="record-field", markup=False)
            yield Button("Close · Esc", classes="close-table")

    def on_mount(self) -> None:
        self.query_one(".record-fields", VerticalScroll).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()


class FullTableScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Close", priority=True)]

    def __init__(self, table_view, result, currency=None):
        super().__init__()
        self.table_view, self.result, self.currency = table_view, result, currency

    def compose(self) -> ComposeResult:
        with Vertical(classes="table-dialog"):
            yield Static("Full Table · ←/→ columns · ↑/↓ records · Enter full record · Esc close",
                         classes="table-instructions", markup=False)
            grid = ResultTable(self.table_view, self.result, currency=self.currency, fullscreen=True)
            yield grid
            with Collapsible(title="Column legend / units", collapsed=True):
                yield Static(grid.legend, markup=False)
            yield Button("Close · Esc", classes="close-table")

    def on_mount(self) -> None:
        self.query_one(ResultTable).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()


class AnswerCard(Vertical):
    def __init__(self, answer: Answer):
        from pl_capital.presentation import build_answer_view

        super().__init__(classes="answer-card")
        self.answer = answer
        self.view = build_answer_view(answer)

    def compose(self) -> ComposeResult:
        status = getattr(self.answer, "status", "tool_error" if self.answer.error else "success")
        yield Static(status.replace("_", " ").upper(), classes="answer-status", markup=False)
        yield Static(_cell_text(self.view.headline), classes="answer-headline", markup=False)
        if self.view.table:
            if "sectors" in self.answer.result:
                with Vertical(classes="exposure-card"):
                    yield from self._result_widgets()
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
                yield from self._result_widgets()
        if self.view.message:
            yield Markdown(_cell_text(self.view.message), classes="answer-body", open_links=False)
        yield Static(getattr(self.view, "explanation_title", "How this was calculated"),
                     classes="explanation-title", markup=False)
        for step in self.view.steps[:5]:
            yield Static("• " + _cell_text(step), classes="explanation-step", markup=False)
        if next_step := getattr(self.view, "next_step", ""):
            yield Static("Next step: " + _cell_text(next_step), classes="answer-next-step", markup=False)
        yield Static(plain(self.view.provenance, 900), classes="provenance", markup=False)
        for warning in self.view.warnings:
            yield Static("Note: " + plain(warning, 700), classes="answer-warning", markup=False)
        sql = self._eligible_sql()
        with Horizontal(classes="answer-actions"):
            if self.is_scenario:
                yield Button("Copy Calculation", classes="copy-calculation",
                             disabled=status != "success", tooltip="Copy the recorded formulas, assumptions and results.")
            else:
                yield Button("Copy SQL", classes="copy-sql", disabled=not sql,
                             tooltip="Copy exact executed SQL." if sql else "No safe executed SQL is available.")
            yield Button("Export answer", classes="export-answer")
            yield Button("Save SQL", classes="save-sql")
        if not sql and not self.is_scenario:
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

    @property
    def is_scenario(self) -> bool:
        return self.answer.tool == "scenario_analysis"

    def _result_widgets(self) -> ComposeResult:
        grid = ResultTable(self.view.table, self.answer.result, currency=self.answer.currency)
        yield grid
        yield Static(f"{len(grid.display_rows)} returned records · {len(grid.column_names)} columns · "
                     "←/→ columns · ↑/↓ records · Enter full record",
                     classes="table-instructions", markup=False)
        yield Button("Full Table", classes="full-table")
        with Collapsible(title="Column legend / units", collapsed=True, classes="column-legend"):
            yield Static(grid.legend, markup=False)
        if self.view.table.truncated:
            yield Static("The query reached its row cap. Narrow the request for a complete result.",
                         classes="answer-warning", markup=False)

    def open_full_table(self) -> None:
        if self.view.table:
            self.app.push_screen(FullTableScreen(self.view.table, self.answer.result, self.answer.currency))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("full-table"):
            event.stop()
            self.open_full_table()
            return
        actions = {"copy-sql": self.copy_sql, "copy-calculation": self.copy_calculation,
                   "export-answer": self.export_answer, "save-sql": self.save_sql}
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
        if self.is_scenario:
            await self.copy_calculation()
            return
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

    async def copy_calculation(self) -> None:
        if not self.is_scenario or getattr(self.answer, "status", "success") != "success":
            self._feedback("No successful scenario calculation is available to copy.")
            return
        try:
            outcome = await asyncio.to_thread(
                self.app.clipboard_service.copy_calculation, self.answer,
                terminal_copy=lambda text: self.app.call_from_thread(self.app.copy_to_clipboard, text),
            )
            self._feedback(outcome.message)
            if not outcome.confirmed:
                self.query_one(".execution-trace", Collapsible).collapsed = False
        except CapitalError as exc:
            self._feedback(str(exc))
        except Exception:
            self._feedback("Clipboard is unavailable. Export the answer for the complete calculation.")

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
