"""First Flight Wizard Widget for KIN V1.1 TUI.

Composes T3 foundation widgets (Panel, ProgressBar, StatusLine, Modal, Toast)
to render the resumable First Flight onboarding experience.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.6
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static
from textual.events import Key

from kin.tui.first_flight import FirstFlightController
from kin.tui.persistence import UiStatePreferences
from kin.tui.state import RecoverableError
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.modal import ModalWidget
from kin.tui.widgets.panel import PanelWidget
from kin.tui.widgets.status_line import StatusLineWidget
from kin.tui.widgets.toast import ToastWidget


class FirstFlightWizardWidget(LifecycleWidgetMixin, Static):
    """Resumable First Flight Onboarding Wizard (§14.6)."""

    DEFAULT_CSS = """
    FirstFlightWizardWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    """
    can_focus = True

    STEP_NAMES = {
        "identity": "1. Initialize Identity",
        "agent": "2. Connect Agent",
        "relay": "3. Verify Relay Reachability",
        "pairing": "4. Pair Trusted Contact",
        "demo": "5. Two-Profile Demo",
        "guided_dispatch": "6. Guided Dispatch Preview",
        "complete": "Setup Completed!",
    }

    STEP_INDEXES = {
        "identity": 1,
        "agent": 2,
        "relay": 3,
        "pairing": 4,
        "demo": 5,
        "guided_dispatch": 6,
        "complete": 6,
    }

    def __init__(
        self,
        controller: FirstFlightController,
        prefs: UiStatePreferences,
        on_complete: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.controller = controller
        self.prefs = prefs
        self.on_complete_callback = on_complete

        # Initial step resolution driven by real durable state + progress preferences
        self.current_step = self.controller.determine_start_step(self.prefs)
        self.recoverable_error: Optional[RecoverableError] = None
        self.active_phrase: Optional[str] = None
        self.verification_indices: List[int] = []
        self.toast_message: Optional[str] = None

    def advance_step(self, next_step: str) -> None:
        """Advance wizard to specified step and clear errors."""
        self.current_step = next_step
        self.recoverable_error = None
        self.refresh()

    def _prompt(self, title: str, fields, callback, body: str = "") -> None:
        from kin.tui.widgets.first_flight_modal import FirstFlightFieldsModal

        self.app.push_screen(FirstFlightFieldsModal(title, fields, body), callback)

    def _create_identity(self) -> None:
        self.active_phrase, self.verification_indices = self.controller.prepare_identity_creation()
        words = self.active_phrase.split()
        fields = [
            ("username", "Permanent username", False, self.controller.profile_name),
            ("word1", f"Recovery word #{self.verification_indices[0] + 1}", True, ""),
            ("word2", f"Recovery word #{self.verification_indices[1] + 1}", True, ""),
        ]

        def confirmed(values: Optional[dict[str, str]]) -> None:
            if values is None or self.active_phrase is None:
                return
            error = self.controller.confirm_identity_creation(
                values["username"],
                self.active_phrase,
                self.verification_indices,
                [values["word1"], values["word2"]],
            )
            if error:
                self.set_error(error)
                return
            self.active_phrase = None
            self.advance_step("agent")

        self.refresh()
        self._prompt(
            "Confirm recovery phrase",
            fields,
            confirmed,
            "Write the displayed phrase down offline. Enter the requested words; KIN never stores the phrase in UI state.",
        )

    def _restore_identity(self) -> None:
        def restored(values: Optional[dict[str, str]]) -> None:
            if values is None:
                return
            error = self.controller.restore_identity_from_mnemonic(values["username"], values["phrase"])
            if error:
                self.set_error(error)
            else:
                self.advance_step("agent")

        self._prompt(
            "Restore identity",
            [
                ("username", "Registered username", False, self.controller.profile_name),
                ("phrase", "12-word recovery phrase", True, ""),
            ],
            restored,
            "The recovery phrase is accepted only in this protected input and is not persisted in UI state.",
        )

    def _import_agent(self) -> None:
        def imported(values: Optional[dict[str, str]]) -> None:
            if values is None:
                return
            error = self.controller.connect_agent_card(Path(values["path"]).expanduser())
            if error:
                self.set_error(error)
            else:
                self.advance_step("relay")

        self._prompt("Connect local agent card", [("path", "Agent card YAML path", False, "")], imported)

    def _pair_contact(self) -> None:
        def looked_up(values: Optional[dict[str, str]]) -> None:
            if values is None:
                return
            prepared, fingerprint, error = self.controller.prepare_contact_pairing(values["username"])
            if error or prepared is None or fingerprint is None:
                self.set_error(error)  # type: ignore[arg-type]
                return

            def verified(proof: Optional[dict[str, str]]) -> None:
                if proof is None:
                    return
                confirm_error = self.controller.confirm_contact_pairing(
                    prepared, fingerprint, proof["fingerprint"]
                )
                if confirm_error:
                    self.set_error(confirm_error)
                else:
                    self.advance_step("demo")

            self._prompt(
                "Verify contact fingerprint",
                [("fingerprint", "Type the complete fingerprint", False, "")],
                verified,
                f"Compare this over a separate trusted channel:\n\n{fingerprint}\n\nTrust is recorded only after an exact match.",
            )

        self._prompt("Find trusted contact", [("username", "Contact username", False, "")], looked_up)

    def on_key(self, event: Key) -> None:
        key = event.key.lower()
        if self.recoverable_error is not None:
            self.clear_error()
            self.current_step = self.controller.determine_start_step(self.prefs)
            event.stop()
            return
        if self.current_step == "identity" and key == "c":
            self._create_identity()
        elif self.current_step == "identity" and key == "r":
            self._restore_identity()
        elif self.current_step == "agent" and key == "i":
            self._import_agent()
        elif self.current_step == "agent" and key == "n":
            if self.controller.check_durable_state()["has_agents"]:
                self.advance_step("relay")
            else:
                self.toast_message = "Connect at least one valid local agent card before continuing."
                self.refresh()
        elif self.current_step == "relay" and key == "v":
            ok, error = self.controller.check_relay_reachability()
            if ok:
                self.prefs = self.controller.mark_progress("relay_checked", True)
                self.advance_step("pairing")
            elif error:
                self.set_error(error)
        elif self.current_step == "relay" and key == "s":
            self.controller.mark_progress("relay_skipped", True)
            self.prefs = self.controller.mark_progress("relay_checked", True)
            self.advance_step("pairing")
        elif self.current_step == "pairing" and key == "p":
            self._pair_contact()
        elif self.current_step == "pairing" and key == "s":
            self.prefs = self.controller.mark_progress("pairing_skipped", True)
            self.advance_step("demo")
        elif self.current_step == "demo" and key == "d":
            from kin.tui.widgets.first_flight_modal import FirstFlightDemoScreen

            def demo_closed(completed: bool) -> None:
                if completed:
                    self.prefs = self.controller.mark_progress("demo_completed", True)
                    self.advance_step("guided_dispatch")

            self.app.push_screen(FirstFlightDemoScreen(), demo_closed)
        elif self.current_step == "demo" and key == "s":
            self.prefs = self.controller.mark_progress("demo_skipped", True)
            self.advance_step("guided_dispatch")
        elif self.current_step == "guided_dispatch" and key == "f":
            self.prefs = self.controller.mark_progress("guided_dispatch_shown", True)
            self.advance_step("complete")
        elif self.current_step == "complete" and key == "enter" and self.on_complete_callback:
            self.on_complete_callback()
        else:
            return
        event.stop()

    def set_error(self, error: RecoverableError) -> None:
        """Set recoverable error state (§14.6)."""
        self.recoverable_error = error
        self.set_lifecycle_state(WidgetLifecycleState.RECOVERABLE_ERROR)
        self.refresh()

    def clear_error(self) -> None:
        """Clear error and resume normal state."""
        self.recoverable_error = None
        self.set_lifecycle_state(WidgetLifecycleState.NORMAL)
        self.refresh()

    def render(self) -> RenderableType:

        # 1. Handle RECOVERABLE_ERROR rendering
        if self.lifecycle_state == WidgetLifecycleState.RECOVERABLE_ERROR and self.recoverable_error:
            err = self.recoverable_error
            modal = ModalWidget(
                title=f"Error: {err.what_happened}",
                body_text=f"Impact: {err.impact}\nPreserved: {err.preserved}\n\nNext Action: {err.next_action}",
            )
            return modal.render()

        # 2. Compute progress percentage
        step_idx = self.STEP_INDEXES.get(self.current_step, 6)
        pct = (step_idx / 6.0) * 100.0

        step_title = self.STEP_NAMES.get(self.current_step, "First Flight Onboarding")
        content = Text()
        content.append(f"=== KIN V1.1 FIRST FLIGHT WIZARD ===\n\n", style="bold cyan")
        content.append(f"Step {step_idx} of 6: {step_title}\n\n", style="bold yellow")

        # 3. Step Specific Body Content
        if self.current_step == "identity":
            content.append("Create a new identity or restore an existing identity from a 12-word recovery phrase.\n\n")
            if self.active_phrase:
                content.append(f"Generated 12-Word Phrase:\n{self.active_phrase}\n\n", style="bold green")
                content.append(f"Verification required for words #{self.verification_indices[0]+1} and #{self.verification_indices[1]+1}.\n")
            else:
                content.append("Press [C] to Create New Identity or [R] to Restore Identity.\n")

        elif self.current_step == "agent":
            durable = self.controller.check_durable_state()
            content.append("Connect at least one local Agent Card to your profile.\n")
            content.append(f"Currently registered agent cards: {durable['agent_count']}\n\n")
            content.append("Press [I] to Import Agent Card YAML file or [N] to Next step.\n")

        elif self.current_step == "relay":
            content.append(f"Configured Relay URL: {self.controller.relay_url}\n")
            content.append("Verifying relay reachability for peer discovery and network messaging...\n\n")
            content.append("Press [V] to Verify reachability or [S] to Skip relay check.\n")

        elif self.current_step == "pairing":
            content.append("Pair with a trusted contact out-of-band by verifying public key fingerprints.\n\n")
            content.append("Press [P] to Pair Contact or [S] to Skip pairing.\n")

        elif self.current_step == "demo":
            content.append("Run the Two-Profile Demo (Alice & Bob) to test local multi-agent communication.\n\n")
            content.append("Press [D] to Run Demo or [S] to Skip demo.\n")

        elif self.current_step == "guided_dispatch":
            content.append("Guided Dispatch Preview:\n")
            content.append("Press d from Home to dispatch multi-step tasks across peer agents safely.\n")
            content.append("All dispatch prompts pass through local approval policy checks.\n\n")
            content.append("Press [F] to Finish First Flight!\n")

        elif self.current_step == "complete":
            content.append("Congratulations! Your KIN V1.1 node is fully configured and ready.\n\n", style="bold green")
            content.append("Press [Enter] to enter the main app workspace.\n")

        if self.toast_message:
            content.append(f"\nSTATUS: {self.toast_message}\n", style="bold yellow")

        # 4. Progress label & Panel Chrome
        content.append(f"\nProgress: {pct:.0f}%\n", style="bold")
        panel = PanelWidget(
            title=f"First Flight — {step_title}",
            content=str(content),
            footer="[C]reate [R]estore [I]mport [V]erify [P]air [D]emo [S]kip [N]ext",
        )
        return panel.render()
