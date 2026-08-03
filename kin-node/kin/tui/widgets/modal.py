"""Modal foundation widget and screen overlay for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Callable, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from kin.tui.motion import MODAL_ANIMATION_MAX_MS
from kin.tui.redaction import redact_ui_text
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ModalWidget(LifecycleWidgetMixin, Static):
    """Modal dialog inner content foundation widget.

    Receives semantic inputs and emits actions without owning business state (§14.5).
    Sanitizes title and body text against secret or local path leakage.
    """

    DEFAULT_CSS = """
    ModalWidget {
        width: 100%;
        height: auto;
        background: $surface-darken-1;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def _c(self, role: str, fallback: str) -> str:
        app = self._get_app_instance()
        if app is not None and getattr(app, "is_colorless_active", False):
            return ""
        if app is not None and hasattr(app, "theme_tokens"):
            try:
                return app.theme_tokens.get_role_color(role)
            except Exception:
                pass
        return fallback if app is None else ""

    def __init__(
        self,
        title: str = "Modal Dialog",
        body_text: str = "Confirm action?",
        confirm_label: str = "Confirm (y)",
        cancel_label: str = "Cancel (n)",
        on_confirm: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.body_text = body_text
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.max_animation_ms = MODAL_ANIMATION_MAX_MS

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[bold {accent}]{glyph} Loading Dialog...[/bold {accent}]"

        scrubbed_title = redact_ui_text(self.title)
        scrubbed_body = redact_ui_text(self.body_text)

        if state == WidgetLifecycleState.EMPTY:
            return f"[bold]{scrubbed_title}[/bold]\n[dim]No dialogue actions required.[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Action disabled"
            return f"[dim][bold]{scrubbed_title}[/bold] (DISABLED)[/dim]\n[{warn}]Reason: {reason}[/{warn}]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} Modal Error: Action failed. Press [Retry].[/bold {err}]"

        if state == WidgetLifecycleState.NARROW:
            return f"[bold]{scrubbed_title}[/bold] | {scrubbed_body[:20]}"

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        return (
            f"[bold {err}]{scrubbed_title}[/bold {err}]{focus_mark}\n"
            f"{scrubbed_body}\n\n"
            f"[bold {accent}][{self.confirm_label}][/bold {accent}]  [dim][{self.cancel_label}][/dim]"
        )


class ModalScreenWidget(ModalScreen[bool]):
    """Foundation ModalScreen overlay wrapping ModalWidget (§14.5).

    Guarantees keyboard handlers (y/n/escape) and action buttons operate consistently across all modal screens.
    """

    DEFAULT_CSS = """
    ModalScreenWidget {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #modal-container {
        width: 56;
        height: auto;
        min-height: 10;
        background: $surface-darken-1;
        border: thick $primary;
        padding: 1 2;
    }
    #modal-buttons {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    """

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def __init__(
        self,
        title: str = "Modal Dialog",
        body_text: str = "Confirm action?",
        confirm_label: str = "Confirm (y)",
        cancel_label: str = "Cancel (n)",
        variant: str = "error",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.body_text = body_text
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.variant = variant

    def compose(self) -> ComposeResult:
        err = self._c("state.error", "#f7768e")
        with Vertical(id="modal-container"):
            yield Static(f"[bold {err}]{self.title}[/bold {err}]", id="modal-header")
            yield Static(self.body_text, id="modal-body")
            with Horizontal(id="modal-buttons"):
                yield Button(self.confirm_label, id="btn-confirm", variant=self.variant)
                yield Button(self.cancel_label, id="btn-cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key in ("y", "Y"):
            self.dismiss(True)
        elif event.key in ("n", "N", "escape"):
            self.dismiss(False)
