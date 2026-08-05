"""Owner-only private-note authoring modal for Session Arena."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


class PrivateNoteAuthoringModal(LifecycleWidgetMixin, ModalScreen[Optional[str]]):
    """Collect a local scratch note and dismiss with its exact text."""

    DEFAULT_CSS = """
    PrivateNoteAuthoringModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #private-note-container {
        width: 70;
        height: auto;
        background: $surface-darken-1;
        border: thick $accent;
        padding: 1 2;
    }
    #private-note-input {
        margin: 1 0;
    }
    #private-note-error {
        color: $error;
        height: 1;
    }
    """

    def __init__(self, session_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session_id = session_id

    def compose(self) -> ComposeResult:
        accent = self._c("accent.primary", "#bb9af7")
        with Vertical(id="private-note-container"):
            yield Static(
                f"[bold {accent}]PRIVATE NOTE — LOCAL ONLY[/bold {accent}]",
                id="private-note-title",
            )
            yield Static(
                f"Session: {self.session_id}\nThis note is encrypted locally and is not signed or sent."
            )
            yield Input(
                placeholder="Write a private note...",
                id="private-note-input",
            )
            yield Static("", id="private-note-error")
            with Horizontal():
                yield Button("Save Locally", id="btn-save-note", variant="primary")
                yield Button("Cancel", id="btn-cancel-note", variant="default")

    def _save(self) -> None:
        value = self.query_one("#private-note-input", Input).value
        if not value.strip():
            err = self._c("state.error", "#f7768e")
            self.query_one("#private-note-error", Static).update(
                f"[bold {err}]Private note cannot be empty.[/bold {err}]"
            )
            return
        self.dismiss(value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save-note":
            self._save()
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self._save()
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()
