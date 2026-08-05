"""Small checkpoint/decision authoring modal for the Session Arena."""

from __future__ import annotations

from typing import Literal, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


class SessionRecordModal(LifecycleWidgetMixin, ModalScreen[Optional[str]]):
    """Collect one reviewed checkpoint label or owner decision summary."""

    DEFAULT_CSS = """
    SessionRecordModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #session-record-container {
        width: 70;
        height: auto;
        background: $surface-darken-1;
        border: thick $accent;
        padding: 1 2;
    }
    #session-record-input { margin: 1 0; }
    #session-record-error { color: $error; height: 1; }
    """

    def __init__(
        self,
        session_id: str,
        record_kind: Literal["checkpoint", "decision"],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session_id = session_id
        self.record_kind = record_kind

    def compose(self) -> ComposeResult:
        title = "CHECKPOINT" if self.record_kind == "checkpoint" else "OWNER DECISION"
        prompt = (
            "Name the reviewed state to preserve."
            if self.record_kind == "checkpoint"
            else "State the decision that should remain in ordered session history."
        )
        with Vertical(id="session-record-container"):
            yield Static(f"[bold]{title}[/bold]\nSession: {self.session_id}\n{prompt}")
            yield Input(placeholder=prompt, id="session-record-input")
            yield Static("", id="session-record-error")
            with Horizontal():
                yield Button("Record", id="btn-record", variant="primary")
                yield Button("Cancel", id="btn-cancel-record")

    def _record(self) -> None:
        value = self.query_one("#session-record-input", Input).value.strip()
        if not value:
            self.query_one("#session-record-error", Static).update(
                f"{self.record_kind.title()} text cannot be empty."
            )
            return
        self.dismiss(value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-record":
            self._record()
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self._record()
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()
