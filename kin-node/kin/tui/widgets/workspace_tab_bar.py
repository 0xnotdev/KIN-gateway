"""WorkspaceTabBar foundation UI component for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from typing import Any, Optional

from textual.widgets import Static

from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class WorkspaceTabBarWidget(LifecycleWidgetMixin, Static):
    """WorkspaceTabBar rendered UI static component.

    Extends LifecycleWidgetMixin to support all 7 standard lifecycle states while reading
    domain tab data from WorkspaceTabManager (§14.5).
    """

    DEFAULT_CSS = """
    WorkspaceTabBarWidget {
        width: 100%;
        height: 1;
        background: $surface-darken-1;
        padding: 0 1;
    }
    """

    def __init__(self, tab_manager: Optional[Any] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tab_manager = tab_manager

    def render(self) -> str:
        state = self.lifecycle_state
        err = self._c("state.error", "#f7768e")
        text_inv = self._c("text.inverse", "#1a1b26")
        accent_hl = self._c("accent.highlight", "#7aa2f7")

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Restoring tab session...[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.tab_manager or not self.tab_manager.tabs:
            return "[dim][ Home ][/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Tab switching disabled"
            return f"[dim]TabBar (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} TabBar Error: Session state lost. Press [Retry].[/bold {err}]"

        tabs = self.tab_manager.tabs
        active_idx = self.tab_manager.active_index

        if state == WidgetLifecycleState.NARROW:
            active_tab = tabs[active_idx] if tabs else None
            title = active_tab.title if active_tab else "Home"
            return f"Tab {active_idx + 1}/{len(tabs)}: {title}"

        tab_parts = []
        for idx, tab in enumerate(tabs):
            badge_str = f" ({tab.badge})" if tab.badge else ""
            dirty_str = "*" if tab.dirty else ""
            label = f"{tab.title}{dirty_str}{badge_str}"

            if idx == active_idx:
                tab_parts.append(f"[bold {text_inv} on {accent_hl}] {idx + 1}:{label} [/bold {text_inv} on {accent_hl}]")
            else:
                tab_parts.append(f"[dim] {idx + 1}:{label} [/dim]")

        focus_mark = " [focus]" if state == WidgetLifecycleState.FOCUSED else ""
        return " ".join(tab_parts) + focus_mark
