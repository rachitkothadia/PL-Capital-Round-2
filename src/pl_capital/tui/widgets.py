import json
import os
import re
import tempfile

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Collapsible, Markdown, Static, TextArea

from pl_capital.models import Answer


def plain(value: object, limit: int = 2000) -> str:
    """Treat dataset/model strings as text, including terminal control sequences."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value))
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


def cell(value: object) -> str:
    if value is None:
        return "—"
    return plain(value, 120).replace("|", "\\|").replace("\n", " ")


def result_markdown(answer: Answer) -> str:
    text = plain(answer.error or answer.message)
    result = answer.result
    if result.get("columns"):
        columns = result["columns"]
        lines = [" | ".join(cell(c) for c in columns), " | ".join("---" for _ in columns)]
        lines += [" | ".join(cell(v) for v in row) for row in result.get("rows", [])[:100]]
        text += "\n\n" + "\n".join(lines)
        count = result.get("row_count", len(result.get("rows", [])))
        text += f"\n\n{count} returned row(s) · historical snapshot"
        if len(result.get("rows", [])) > 100:
            text += "\n\nShowing first 100 rows; use CLI --json for the complete bounded result."
    if answer.warnings:
        text += "\n\n" + "\n\n".join(f"**Note:** {plain(w)}" for w in answer.warnings)
    return text


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


class AnswerCard(Vertical):
    def __init__(self, answer: Answer, *, trace_expanded: bool = False):
        super().__init__(classes="answer-card")
        self.answer = answer
        self.trace_expanded = trace_expanded

    def compose(self) -> ComposeResult:
        label = "ANALYSIS" if not self.answer.error else "ACTION NEEDED"
        yield Static(label, classes="role-label", markup=False)
        yield Markdown(result_markdown(self.answer), classes="answer-body", open_links=False)
        if "sectors" in self.answer.result:
            yield ExposureCard(self.answer.result)
        with Collapsible(title="Execution trace / How this answer was computed",
                         collapsed=not self.trace_expanded, classes="execution-trace"):
            if not self.answer.trace:
                yield Static("No operational events were recorded for this response.", markup=False)
            for index, event in enumerate(self.answer.trace, start=1):
                yield Static(f"{index:02d}  {plain(event.stage, 80)}  ·  {event.elapsed_ms:.1f} ms",
                             classes="trace-heading", markup=False)
                yield Static(plain(event.detail, 3000), classes="trace-detail", markup=False)
                if event.data:
                    yield Static(Syntax(safe_json(event.data), "json", theme="monokai", word_wrap=True),
                                 classes="trace-data")
            if self.answer.sql:
                yield Static("EXECUTED SQL", classes="trace-heading", markup=False)
                yield Static(Syntax(plain(self.answer.sql, 30000), "sql", theme="monokai", word_wrap=True),
                             classes="executed-sql")
                yield Static("Bound parameters (credentials redacted)", classes="trace-heading", markup=False)
                yield Static(Syntax(safe_json(self.answer.parameters), "json", theme="monokai", word_wrap=True))
                sources = ", ".join(self.answer.result.get("source_tables", [])) or "See execution events"
                yield Static(f"Source tables: {plain(sources, 1000)}\nReturned rows: "
                             f"{self.answer.result.get('row_count', 0)} · Overall {self.answer.elapsed_ms:.1f} ms",
                             classes="trace-detail", markup=False)
                yield Button("Copy SQL + export", classes="copy-sql", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not event.button.has_class("copy-sql") or not self.answer.sql:
            return
        event.stop()
        sql = plain(self.answer.sql, 30000)
        try:
            cache = self.app.agent.settings.cache_dir
            cache.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix="query-", suffix=".sql", dir=cache)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(sql + "\n")
                os.replace(name, cache / "last-query.sql")
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            self.app.copy_to_clipboard(sql)
            self.app.notify("SQL exported to cache/last-query.sql; clipboard requested. Terminal support varies.")
        except OSError:
            self.app.notify("SQL remains visible in the expanded trace; export unavailable.", severity="warning")


class ExposureCard(Vertical):
    def __init__(self, result: dict):
        super().__init__(classes="exposure-card")
        self.result = result

    def compose(self) -> ComposeResult:
        data = self.result
        yield Static("SECTOR EXPOSURE  /  " + plain(data.get("portfolio_name", ""), 160),
                     classes="exposure-heading", markup=False)
        yield Static("Stock holdings only · recorded current_weight fractions", markup=False)
        for sector in data.get("sectors", []):
            whole = sector["whole_portfolio_pct"]
            normalized = sector["equity_normalized_pct"]
            filled = round(max(0, min(100, whole)) / 5)
            bar = "#" * filled + "." * (20 - filled)
            yield Static(
                f"{plain(sector['sector'], 80)}\n"
                f"Whole portfolio   {whole:7.2f}%  [{bar}]\n"
                f"Equity normalized {normalized:7.2f}%  (stock denominator)",
                classes="sector-row", markup=False,
            )
        if not data.get("sectors"):
            yield Static("No equity holdings to break down. No normalization applied.", markup=False)
        yield Static(
            f"Equity weight total: {plain(data.get('equity_weight_total'), 80)}\n"
            f"Bond weight total: {plain(data.get('bond_weight_total'), 80)}\n"
            f"All recorded weights: {plain(data.get('all_recorded_weights_total'), 80)}\n"
            f"{data.get('equity_holding_count', 0)} stock holdings · "
            f"{data.get('bond_exclusion_count', 0)} bond holdings excluded",
            classes="exposure-totals", markup=False,
        )
        yield Static("Whole = sector stock weight × 100\n"
                     "Normalized = sector stock weight / equity weight total × 100",
                     classes="exposure-formula", markup=False)
