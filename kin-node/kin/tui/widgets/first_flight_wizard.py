"""First Flight Wizard Widget for KIN V1.1 TUI.

Composes T3 foundation widgets (Panel, ProgressBar, StatusLine, Modal, Toast)
to render the resumable First Flight onboarding experience.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.6
"""

from typing import Any, Callable, Dict, List, Optional
from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static

from kin.tui.first_flight import FirstFlightController
from kin.tui.persistence import UiStatePreferences
from kin.tui.state import RecoverableError
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState
from kin.tui.widgets.modal import ModalWidget
from kin.tui.widgets.panel import PanelWidget
from kin.tui.widgets.progress_bar import ProgressBarWidget
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
        if self.current_step == "complete" and self.on_complete_callback:
            self.on_complete_callback()

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
            content.append("In Milestone T5, you will dispatch multi-step tasks across peer agents safely.\n")
            content.append("All dispatch prompts pass through local approval policy checks.\n\n")
            content.append("Press [F] to Finish First Flight!\n")

        elif self.current_step == "complete":
            content.append("Congratulations! Your KIN V1.1 node is fully configured and ready.\n\n", style="bold green")
            content.append("Press [Enter] to enter the main app workspace.\n")

        # 4. Progress bar & Panel Chrome
        prog_bar = ProgressBarWidget(progress_percent=pct, label=f"{pct:.0f}%")
        panel = PanelWidget(
            title=f"First Flight — {step_title}",
            body_widget=content,
            subtitle="[C]reate [R]estore [I]mport [V]erify [P]air [D]emo [S]kip [N]ext",
        )
        return panel.render()
