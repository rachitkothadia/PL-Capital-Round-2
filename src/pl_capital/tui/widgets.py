import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Markdown, Static, TextArea

from pl_capital.models import Answer


def plain(value: object, limit: int = 2000) -> str:
    """Treat dataset/model strings as text, including terminal control sequences."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value))[:limit]


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
    if "sectors" in result:
        text += "\n\n| Sector | Whole portfolio | Equity normalized |\n|---|---:|---:|"
        for sector in result["sectors"]:
            whole = sector["whole_portfolio_pct"]
            norm = sector["equity_normalized_pct"]
            text += f"\n| {cell(sector['sector'])} | {whole:.2f}% | {norm:.2f}% |"
        text += (
            f"\n\nStock weight: {cell(result.get('equity_weight_total'))} · "
            f"Bond weight: {cell(result.get('bond_weight_total'))} · "
            f"Recorded total: {cell(result.get('all_recorded_weights_total'))}"
            f"\n\n{result.get('equity_holding_count', 0)} stock holdings · "
            f"{result.get('bond_exclusion_count', 0)} bond holdings excluded"
        )
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
    def __init__(self, answer: Answer):
        super().__init__(classes="answer-card")
        self.answer = answer

    def compose(self) -> ComposeResult:
        label = "ANALYSIS" if not self.answer.error else "ACTION NEEDED"
        yield Static(label, classes="role-label", markup=False)
        yield Markdown(result_markdown(self.answer), classes="answer-body", open_links=False)
