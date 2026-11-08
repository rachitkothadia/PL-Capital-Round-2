from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Static

DARK_THEME = Theme(
    name="capital-dark", primary="#69c8ba", secondary="#99b8dd", accent="#b7a9e3",
    foreground="#edf2f8", background="#101821", surface="#172330", panel="#1d2d3d",
    success="#90cda7", warning="#e9bf78", error="#f29a9a", dark=True, text_alpha=1,
    variables={"border-blurred": "#3d5065", "border": "#69c8ba",
               "footer-background": "#1d2d3d", "footer-key-foreground": "#9ce3d6",
               "footer-description-foreground": "#edf2f8"},
)
LIGHT_THEME = Theme(
    name="capital-light", primary="#086f65", secondary="#315d85", accent="#6c429d",
    foreground="#1c2938", background="#f4f7fb", surface="#ffffff", panel="#e5edf5",
    success="#226a3e", warning="#885400", error="#ac3039", dark=False, text_alpha=1,
    variables={"border-blurred": "#adbccc", "border": "#086f65",
               "footer-background": "#e5edf5", "footer-key-foreground": "#075e56",
               "footer-description-foreground": "#1c2938"},
)


class ThemeChooser(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Close", priority=True)]

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Static("Choose a theme", classes="dialog-title", markup=False)
            yield Static("The full interface and code highlighting change immediately.", markup=False)
            with Horizontal(classes="theme-options"):
                yield Button("Dark", id="theme-dark", variant="primary")
                yield Button("Light", id="theme-light")
            yield Static("Tab to choose · Enter to apply · Escape to close", classes="muted", markup=False)

    def on_mount(self) -> None:
        self.query_one("#theme-dark", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss("light" if event.button.id == "theme-light" else "dark")

    def action_cancel(self) -> None:
        self.dismiss(None)
