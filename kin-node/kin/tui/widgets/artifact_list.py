"""ArtifactList domain widget for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from datetime import datetime
from typing import List, Optional, Union

from textual.events import Key
from textual.widgets import Static

from kin.tui.state import ArtifactView
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ArtifactListWidget(LifecycleWidgetMixin, Static):
    """ArtifactList domain widget for vault artifacts with 64-char SHA-256 digest truncation (§14.5)."""

    can_focus = True

    DEFAULT_CSS = """
    ArtifactListWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    ArtifactListWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        artifacts: Optional[List[ArtifactView]] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.artifacts: List[ArtifactView] = artifacts or []
        self.selected_index: int = 0

    @staticmethod
    def format_digest(digest: str) -> str:
        """Format 64-character SHA-256 hex digest into first-8...last-8 format (§14.5)."""
        if len(digest) >= 16:
            return f"{digest[:8]}...{digest[-8:]}"
        return digest

    def cursor_down(self) -> None:
        if self.artifacts:
            self.selected_index = min(self.selected_index + 1, len(self.artifacts) - 1)
            self.refresh()

    def get_selected_artifact(self) -> Optional[ArtifactView]:
        """Return currently selected ArtifactView item in vault list (§14.5)."""
        if self.artifacts and 0 <= self.selected_index < len(self.artifacts):
            return self.artifacts[self.selected_index]
        return None

    def cursor_up(self) -> None:
        if self.artifacts:
            self.selected_index = max(self.selected_index - 1, 0)
            self.refresh()

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED:
            return

        if event.key in ("down", "j"):
            self.cursor_down()
            event.stop()
        elif event.key in ("up", "k"):
            self.cursor_up()
            event.stop()

    def _c(self, role: str, fallback: str) -> str:
        """Resolve a theme color by role, falling back when app is unavailable."""
        try:
            return self.app.theme_tokens.get_role_color(role)
        except Exception:
            return fallback

    def render(self) -> str:
        err = self._c("state.error", "#f7768e")
        warn = self._c("state.waiting", "#e0af68")
        accent = self._c("accent.primary", "#bb9af7")
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Scanning Artifact Vault...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "ArtifactList disabled"
            return f"[dim]ArtifactList (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.EMPTY or not self.artifacts:
            return "[dim]ArtifactList: Vault contains no artifacts.[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold {err}]{glyph} ArtifactList Error: Vault index corrupted. Press [Retry].[/bold {err}]"

        lines = ["[bold]Vault Artifacts:[/bold]"]
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        for idx, art in enumerate(self.artifacts):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "
            meta = art.metadata
            digest_str = self.format_digest(meta.sha256)
            prev_badge = "[previewable]" if art.preview_available else "[raw]"

            if state == WidgetLifecycleState.NARROW:
                line = f"{prefix}{meta.artifact_id[:12]} ({art.display_size})"
            else:
                line = (
                    f"{prefix}[bold]{meta.artifact_id}[/bold] [dim]({art.display_size})[/dim] "
                    f"{prev_badge} digest=[{warn}]{digest_str}[/{warn}]"
                )

            if is_selected:
                lines.append(f"[bold {accent}]{line}[/bold {accent}]")
            else:
                lines.append(line)

        lines[0] += focus_mark
        return "\n".join(lines)
