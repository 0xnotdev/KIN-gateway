"""Session State Menu Modal for KIN V1.1 TUI (§5.3, §14.8 Phase D).

Provides state management dialog for active/paused sessions:
- Pause Session: pauses session via local_state.pause_session
- Resume Session: resumes session via local_state.resume_session
- Cancel Session: cancels session via local_state.cancel_session_command
- Hand Back Session: rendered present-but-disabled ("not yet available" pending backend transport support)
"""

from typing import Callable, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


class SessionStateMenuModal(LifecycleWidgetMixin, ModalScreen[Optional[str]]):
    """Modal dialog for session state transitions (pause/resume/cancel/hand back) (§5.3, §14.8 Phase D)."""

    DEFAULT_CSS = """
    SessionStateMenuModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #session-state-container {
        width: 64;
        height: auto;
        background: $surface-darken-1;
        border: thick $primary;
        padding: 1 2;
    }
    .state-btn {
        margin: 1 0;
    }
    """

    def __init__(self, session_id: str, current_status: str = "active", **kwargs) -> None:
        super().__init__(**kwargs)
        self.session_id = session_id
        self.current_status = current_status

    def compose(self) -> ComposeResult:
        accent = self._c("accent.primary", "#bb9af7")
        warn = self._c("state.waiting", "#e0af68")
        with Vertical(id="session-state-container"):
            yield Static(f"[bold {accent}]SESSION STATE MENU [{self.session_id[:12]}][/bold {accent}]")
            yield Static(f"Current Status: [bold {warn}]{self.current_status.upper()}[/bold {warn}]\n")

            if self.current_status == "active":
                yield Button("Pause Session (p)", id="btn-pause", variant="warning", classes="state-btn")
            elif self.current_status == "paused":
                yield Button("Resume Session (r)", id="btn-resume", variant="success", classes="state-btn")

            if self.current_status not in ("completed", "cancelled", "failed", "rejected"):
                yield Button("Cancel Session (c)", id="btn-cancel-session", variant="error", classes="state-btn")

            # Hand Back option: present-but-disabled per §14.8 Phase D
            yield Button("Hand Back Session (h) - [not yet available]", id="btn-handback", variant="default", disabled=True, classes="state-btn")

            with Horizontal():
                yield Button("Close (Esc)", id="btn-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-pause":
            self.dismiss("pause")
        elif btn_id == "btn-resume":
            self.dismiss("resume")
        elif btn_id == "btn-cancel-session":
            self.dismiss("cancel")
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "p" and self.current_status == "active":
            self.dismiss("pause")
            event.stop()
        elif event.key == "r" and self.current_status == "paused":
            self.dismiss("resume")
            event.stop()
        elif event.key == "c" and self.current_status not in ("completed", "cancelled", "failed", "rejected"):
            self.dismiss("cancel")
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()
