"""Shared approval confirmation modals for KIN V1.1 TUI (§3.1, §14.8 Phase D).

Extracted shared confirmation dialogs used by both InboxScreenWidget and SessionArenaWidget:
- DenyReasonModal: captures mandatory non-empty reason for DENY.
- EditConstraintsModal: captures flat JSON constraints object for EDIT_CONSTRAINTS.
- ApproveConfirmModal: generic confirmation modal gating APPROVE_ONCE and ALWAYS_ALLOW_BOUNDED.
"""

import json
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class DenyReasonModal(ModalScreen[Optional[str]]):
    """Modal dialog for DENY action requiring non-empty reason input (§3.1)."""

    DEFAULT_CSS = """
    DenyReasonModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #deny-container {
        width: 60;
        height: auto;
        background: $surface-darken-1;
        border: thick $error;
        padding: 1 2;
    }
    #deny-reason-input {
        margin: 1 0;
    }
    #deny-error-label {
        color: $error;
        height: 1;
    }
    """

    def __init__(self, approval_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.approval_id = approval_id

    def compose(self) -> ComposeResult:
        with Vertical(id="deny-container"):
            yield Static(f"[bold red]DENY APPROVAL REQUEST [{self.approval_id[:8]}][/bold red]")
            yield Static("Enter a mandatory reason for denying this request:")
            yield Input(placeholder="Reason for denial (required)...", id="deny-reason-input")
            yield Static("", id="deny-error-label")
            with Horizontal():
                yield Button("Confirm Deny (y)", id="btn-confirm", variant="error")
                yield Button("Cancel (n)", id="btn-cancel", variant="default")

    def submit_reason(self) -> None:
        inp = self.query_one("#deny-reason-input", Input)
        err = self.query_one("#deny-error-label", Static)
        reason = inp.value.strip()
        if not reason:
            err.update("[bold red]Denial reason is required and cannot be empty.[/bold red]")
            inp.focus()
            return
        self.dismiss(reason)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.submit_reason()
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.submit_reason()
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()


class EditConstraintsModal(ModalScreen[Optional[dict]]):
    """Modal dialog for EDIT_CONSTRAINTS capturing a flat JSON object (§3.1)."""

    DEFAULT_CSS = """
    EditConstraintsModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #constraints-container {
        width: 64;
        height: auto;
        background: $surface-darken-1;
        border: thick $accent;
        padding: 1 2;
    }
    #constraints-json-input {
        margin: 1 0;
    }
    #json-error-label {
        color: $error;
        height: 1;
    }
    """

    def __init__(self, approval_id: str, initial_json: str = "{}", **kwargs) -> None:
        super().__init__(**kwargs)
        self.approval_id = approval_id
        self.initial_json = initial_json

    def compose(self) -> ComposeResult:
        with Vertical(id="constraints-container"):
            yield Static(f"[bold cyan]EDIT CONSTRAINTS [{self.approval_id[:8]}][/bold cyan]")
            yield Static('Enter flat JSON constraints (e.g. {"max_turn_limit": 5}):')
            yield Input(value=self.initial_json, placeholder='{"key": "value"}', id="constraints-json-input")
            yield Static("", id="json-error-label")
            with Horizontal():
                yield Button("Apply Constraints (y)", id="btn-confirm", variant="primary")
                yield Button("Cancel (n)", id="btn-cancel", variant="default")

    def submit_constraints(self) -> None:
        inp = self.query_one("#constraints-json-input", Input)
        err = self.query_one("#json-error-label", Static)
        val = inp.value.strip()
        if not val:
            err.update("[bold red]Constraints JSON cannot be empty.[/bold red]")
            return
        try:
            parsed = json.loads(val)
            if not isinstance(parsed, dict):
                err.update("[bold red]Constraints must be a JSON object ({...}).[/bold red]")
                return
            self.dismiss(parsed)
        except Exception as exc:
            err.update(f"[bold red]Invalid JSON: {exc}[/bold red]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.submit_constraints()
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.submit_constraints()
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()


class ApproveConfirmModal(ModalScreen[bool]):
    """Generic confirmation modal gating Approve Once / Always Allow Bounded (§3.1)."""

    DEFAULT_CSS = """
    ApproveConfirmModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #approve-container {
        width: 64;
        height: auto;
        background: $surface-darken-1;
        border: thick $success;
        padding: 1 2;
    }
    """

    def __init__(self, title: str, description: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.modal_title = title
        self.modal_description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="approve-container"):
            yield Static(f"[bold green]{self.modal_title}[/bold green]")
            yield Static(self.modal_description)
            with Horizontal():
                yield Button("Confirm (y)", id="btn-confirm", variant="success")
                yield Button("Cancel (n)", id="btn-cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_key(self, event: Key) -> None:
        if event.key == "y":
            self.dismiss(True)
            event.stop()
        elif event.key in ("n", "escape"):
            self.dismiss(False)
            event.stop()
