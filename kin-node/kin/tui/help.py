"""Contextual Help Overlay Generator for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.1, §5.4, §14.4
"""

from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Static

from kin.tui.keymap import DEFAULT_KEYMAP, KeyBindingSpec
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


def generate_help_markdown(bindings: Optional[List[KeyBindingSpec]] = None) -> str:
    """Generate Markdown contextual help dynamically from keymap.py registry (§14.4).

    Guarantees contextual help never drifts from active keymap registry.
    """
    target = bindings if bindings is not None else DEFAULT_KEYMAP

    sections = {"global": "Global Commands", "collection": "Collection & Navigation", "arena": "Session Arena"}

    lines = ["# KIN V1.1 Terminal UI — Keyboard Reference", ""]

    for sec_key, sec_title in sections.items():
        sec_bindings = [b for b in target if b.section == sec_key]
        if not sec_bindings:
            continue

        lines.append(f"## {sec_title}")
        lines.append("")
        lines.append("| Key | Action / Description | Priority | Text-Yield |")
        lines.append("|---|---|---|---|")

        for b in sec_bindings:
            p_str = "Yes" if b.priority else "No"
            y_str = "Yields" if b.suppressed_when_text_focused else "Active"
            key_disp = f"`{b.key}`"
            lines.append(f"| {key_disp} | {b.label} | {p_str} | {y_str} |")

        lines.append("")

    return "\n".join(lines)


class HelpOverlayScreen(LifecycleWidgetMixin, ModalScreen[None]):
    """Contextual Help Overlay Screen (?) generated from keymap registry (§5.1)."""

    DEFAULT_CSS = """
    HelpOverlayScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #help-container {
        width: 84;
        height: 26;
        background: $surface-darken-1;
        border: thick $primary-lighten-1;
        padding: 1 2;
    }
    #help-scroll {
        height: 1fr;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_help", "Close Help"),
        ("question_mark", "dismiss_help", "Close Help"),
    ]

    def compose(self) -> ComposeResult:
        accent = self._c("accent.primary", "#bb9af7")
        md_text = generate_help_markdown()
        with Vertical(id="help-container"):
            yield Static(f"[bold {accent}]KIN Keyboard Reference & Help (?)[/bold {accent}]", id="help-header")
            with ScrollableContainer(id="help-scroll"):
                yield Static(md_text, id="help-content")
            yield Static("[dim]Press ESC or ? to close[/dim]", id="help-footer")

    def action_dismiss_help(self) -> None:
        self.dismiss(None)
