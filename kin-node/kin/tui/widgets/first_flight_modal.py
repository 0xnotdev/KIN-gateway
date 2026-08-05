"""Interactive, resumable First Flight host for a newly installed KIN node."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kin.tui.first_flight import FirstFlightController
from kin.tui.persistence import UiStatePreferences
from kin.tui.widgets.first_flight_wizard import FirstFlightWizardWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


class FirstFlightFieldsModal(LifecycleWidgetMixin, ModalScreen[Optional[dict[str, str]]]):
    """Small transient prompt whose values are never written to UI preferences."""

    DEFAULT_CSS = """
    FirstFlightFieldsModal { align: center middle; background: rgba(0, 0, 0, 0.75); }
    #first-flight-fields { width: 76; height: auto; padding: 1 2; border: thick $accent; background: $surface; }
    .first-flight-input { margin: 0 0 1 0; }
    """

    def __init__(self, title: str, fields: list[tuple[str, str, bool, str]], body: str = "") -> None:
        super().__init__()
        self.prompt_title = title
        self.fields = fields
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="first-flight-fields"):
            yield Static(f"[bold]{self.prompt_title}[/bold]\n{self.body}")
            for field_id, label, secret, value in self.fields:
                yield Static(label)
                yield Input(value=value, password=secret, id=f"ff-{field_id}", classes="first-flight-input")
            yield Static("", id="ff-error")
            with Horizontal():
                yield Button("Continue", id="ff-continue", variant="primary")
                yield Button("Cancel", id="ff-cancel")

    def on_mount(self) -> None:
        first = self.query(Input).first()
        if first:
            first.focus()

    def submit(self) -> None:
        values = {
            field_id: self.query_one(f"#ff-{field_id}", Input).value.strip()
            for field_id, _, _, _ in self.fields
        }
        if any(not value for value in values.values()):
            self.query_one("#ff-error", Static).update("Every field is required.")
            return
        self.dismiss(values)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.submit() if event.button.id == "ff-continue" else self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.submit()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()


class FirstFlightScreen(ModalScreen[bool]):
    """Full-screen onboarding surface; completion returns to the normal workspace."""

    DEFAULT_CSS = """
    FirstFlightScreen { background: $background; }
    #first-flight-host { width: 100%; height: 100%; padding: 1 2; }
    """

    def __init__(self, controller: FirstFlightController, prefs: UiStatePreferences) -> None:
        super().__init__()
        self.wizard = FirstFlightWizardWidget(controller, prefs, on_complete=self._finish)

    def compose(self) -> ComposeResult:
        with Vertical(id="first-flight-host"):
            yield self.wizard

    def on_mount(self) -> None:
        self.wizard.focus()

    def _finish(self) -> None:
        self.dismiss(True)


class FirstFlightDemoScreen(ModalScreen[bool]):
    """Read-only Alice/Bob fixture walkthrough with the same visible state vocabulary."""

    DEFAULT_CSS = """
    FirstFlightDemoScreen { align: center middle; background: $background; }
    #ff-demo { width: 76; height: auto; padding: 1 2; border: thick $accent; background: $surface; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="ff-demo"):
            yield Static(
                "[bold]TWO-PROFILE SAFETY DEMO[/bold]\n\n"
                "1. Alice selects Alice Agent and Bob Agent explicitly.\n"
                "2. Alice reviews the goal and peer-visible context, then signs Dispatch.\n"
                "3. Bob sees NEEDS YOU and accepts on Bob's own node.\n"
                "4. A requested local write is shown only to its local owner.\n"
                "5. Direct loss becomes QUEUED; relay resume deduplicates the envelope.\n"
                "6. Outcome, replay, artifact hash, and redacted export remain inspectable.\n\n"
                "This is fixture data. It does not create identities, contacts, traffic, or approvals."
            )
            with Horizontal():
                yield Button("Demo understood (Enter)", id="ff-demo-complete", variant="primary")
                yield Button("Back (Esc)", id="ff-demo-back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ff-demo-complete")

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.dismiss(True)
            event.stop()
        elif event.key == "escape":
            self.dismiss(False)
            event.stop()
