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

from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


class DenyReasonModal(LifecycleWidgetMixin, ModalScreen[Optional[str]]):
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
        err = self._c("state.error", "#f7768e")
        with Vertical(id="deny-container"):
            yield Static(f"[bold {err}]DENY APPROVAL REQUEST [{self.approval_id[:8]}][/bold {err}]")
            yield Static("Enter a mandatory reason for denying this request:")
            yield Input(placeholder="Reason for denial (required)...", id="deny-reason-input")
            yield Static("", id="deny-error-label")
            with Horizontal():
                yield Button("Confirm Deny (y)", id="btn-confirm", variant="error")
                yield Button("Cancel (n)", id="btn-cancel", variant="default")

    def submit_reason(self) -> None:
        err_color = self._c("state.error", "#f7768e")
        inp = self.query_one("#deny-reason-input", Input)
        err = self.query_one("#deny-error-label", Static)
        reason = inp.value.strip()
        if not reason:
            err.update(f"[bold {err_color}]Denial reason is required and cannot be empty.[/bold {err_color}]")
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


class EditConstraintsModal(LifecycleWidgetMixin, ModalScreen[Optional[dict]]):
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
        accent = self._c("accent.primary", "#bb9af7")
        with Vertical(id="constraints-container"):
            yield Static(f"[bold {accent}]EDIT CONSTRAINTS [{self.approval_id[:8]}][/bold {accent}]")
            yield Static('Enter flat JSON constraints (e.g. {"max_turn_limit": 5}):')
            yield Input(value=self.initial_json, placeholder='{"key": "value"}', id="constraints-json-input")
            yield Static("", id="json-error-label")
            with Horizontal():
                yield Button("Apply Constraints (y)", id="btn-confirm", variant="primary")
                yield Button("Cancel (n)", id="btn-cancel", variant="default")

    def submit_constraints(self) -> None:
        err_color = self._c("state.error", "#f7768e")
        inp = self.query_one("#constraints-json-input", Input)
        err = self.query_one("#json-error-label", Static)
        val = inp.value.strip()
        if not val:
            err.update(f"[bold {err_color}]Constraints JSON cannot be empty.[/bold {err_color}]")
            return
        try:
            parsed = json.loads(val)
            if not isinstance(parsed, dict):
                err.update(f"[bold {err_color}]Constraints must be a JSON object ({{...}}).[/bold {err_color}]")
                return
            self.dismiss(parsed)
        except Exception as exc:
            err.update(f"[bold {err_color}]Invalid JSON: {exc}[/bold {err_color}]")

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


class ApproveConfirmModal(LifecycleWidgetMixin, ModalScreen[bool]):
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
        ok = self._c("state.live", "#73daca")
        with Vertical(id="approve-container"):
            yield Static(f"[bold {ok}]{self.modal_title}[/bold {ok}]")
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


class PatchApplyConfirmModal(LifecycleWidgetMixin, ModalScreen[bool]):
    """Confirmation modal for workspace patch application showing structured unified diff before confirming (§5.3, §14.8)."""

    DEFAULT_CSS = """
    PatchApplyConfirmModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #patch-container {
        width: 80;
        height: auto;
        max-height: 28;
        background: $surface-darken-1;
        border: thick $warning;
        padding: 1 2;
    }
    #diff-preview-box {
        width: 100%;
        height: 12;
        border: solid $primary-darken-2;
        padding: 0 1;
        margin: 1 0;
        overflow-y: scroll;
    }
    """

    def __init__(self, artifact_id: str, relative_target_path: str, unified_diff: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.artifact_id = artifact_id
        self.relative_target_path = relative_target_path
        self.unified_diff = unified_diff

    def compose(self) -> ComposeResult:
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        ok = self._c("state.live", "#73daca")
        err = self._c("state.error", "#f7768e")
        with Vertical(id="patch-container"):
            yield Static(f"[bold {warn}]CONFIRM WORKSPACE PATCH APPLY [{self.artifact_id[:8]}][/bold {warn}]")
            yield Static(f"Target File: [bold {accent}]{self.relative_target_path}[/bold {accent}]")
            
            # Format diff lines with syntax highlighting
            diff_lines = []
            for line in self.unified_diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    diff_lines.append(f"[{ok}]{line}[/{ok}]")
                elif line.startswith("-") and not line.startswith("---"):
                    diff_lines.append(f"[{err}]{line}[/{err}]")
                elif line.startswith("@"):
                    diff_lines.append(f"[{accent}]{line}[/{accent}]")
                else:
                    diff_lines.append(f"[dim]{line}[/dim]")
            
            diff_text = "\n".join(diff_lines) if diff_lines else "[dim]No diff changes.[/dim]"
            yield Static(diff_text, id="diff-preview-box")
            yield Static("[bold]Apply this patch to the workspace target file on disk?[/bold]")
            with Horizontal():
                yield Button("Apply Patch (y)", id="btn-confirm", variant="warning")
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
