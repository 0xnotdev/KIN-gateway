"""Compose message modal dialog for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md line 227 ("m: Compose a human message or clarification"),
line 232 ("review before send flow").
"""

from typing import Optional
from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ComposeMessageModal(ModalScreen[Optional[str]]):
    """Modal dialog for composing and reviewing human messages/clarifications before sending (§14.8 Step 5/6)."""

    DEFAULT_CSS = """
    ComposeMessageModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #compose-dialog {
        grid-size: 2 4;
        grid-gutter: 1 2;
        grid-rows: auto auto auto 3;
        padding: 1 2;
        width: 74;
        height: 22;
        border: thick $accent;
        background: $surface;
    }
    #compose-title {
        column-span: 2;
        content-align: center middle;
        text-style: bold;
    }
    #compose-input {
        column-span: 2;
    }
    #compose-preview {
        column-span: 2;
        color: $text-muted;
    }
    """

    def __init__(self, session_id: str, is_clarification: bool = False):
        super().__init__()
        self.session_id = session_id
        self.is_clarification = is_clarification
        self.composed_text = ""
        self.review_step = False

    def compose(self) -> ComposeResult:
        title = "Compose Clarification Response" if self.is_clarification else f"Compose Message for Session '{self.session_id}'"
        with Grid(id="compose-dialog"):
            yield Label(title, id="compose-title")
            yield Input(placeholder="Type your message here...", id="compose-input")
            yield Static("Enter message text above then click Review & Send.", id="compose-preview")
            yield Button("Review & Send", variant="primary", id="btn-review")
            yield Button("Cancel", variant="default", id="btn-cancel")

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def on_input_changed(self, event: Input.Changed) -> None:
        accent = self._c("accent.primary", "#bb9af7")
        self.composed_text = event.value
        preview = self.query_one("#compose-preview", Static)
        if self.review_step:
            preview.update(f"[bold {accent}]REVIEW BEFORE SENDING:[/bold {accent}]\n\"{self.composed_text}\"")
        else:
            preview.update(f"Message preview ({len(self.composed_text)} chars): \"{self.composed_text[:45]}\"")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        warn = self._c("state.waiting", "#e0af68")
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-review":
            if not self.composed_text.strip():
                return
            if not self.review_step:
                self.review_step = True
                preview = self.query_one("#compose-preview", Static)
                preview.update(f"[bold {warn}]REVIEW BEFORE SENDING TO SESSION:[/bold {warn}]\n\"{self.composed_text}\"")
                btn_review = self.query_one("#btn-review", Button)
                btn_review.label = "Confirm & Transmit"
            else:
                self.dismiss(self.composed_text.strip())
