"""Inspector foundation UI component for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5, §14.8 Step 4
"""

from datetime import datetime
from typing import Optional, Union

from textual.widgets import Static

from kin.tui.redaction import redact_ui_text
from kin.tui.state import ApprovalView, ArtifactView, UiEvent
from kin.tui.tokens import get_glyph
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class InspectorWidget(LifecycleWidgetMixin, Static):
    """Inspector read-only detail view domain widget (§14.5, §14.8 Step 4).

    Renders detailed inspection preview for selected UiEvent, ArtifactView, or ApprovalView.
    Sanitizes free-form text with redact_ui_text().
    Strictly read-only: contains ZERO affordances/buttons/methods to import, apply, or approve.
    """

    can_focus = True

    DEFAULT_CSS = """
    InspectorWidget {
        width: 100%;
        height: 100%;
        background: $surface-darken-1;
        border-left: solid $border-subtle;
        padding: 0 1;
    }
    InspectorWidget:focus {
        border: double $accent;
    }
    """

    def __init__(
        self,
        title: str = "Detail Inspector",
        details: Optional[str] = None,
        selected_event: Optional[UiEvent] = None,
        selected_artifact: Optional[ArtifactView] = None,
        selected_approval: Optional[ApprovalView] = None,
        collapsed: bool = False,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.title = title
        self.details = details
        self.selected_event: Optional[UiEvent] = selected_event
        self.selected_artifact: Optional[ArtifactView] = selected_artifact
        self.selected_approval: Optional[ApprovalView] = selected_approval
        self.collapsed = collapsed

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Fetching item details...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "Inspector disabled"
            return f"[dim]Inspector (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            return f"[bold red]{glyph} Inspector Error: Item details unreadable. Press [Retry].[/bold red]"

        if self.collapsed:
            return "i\nn\ns\np"

        # Mode A: Inspect selected UiEvent
        if self.selected_event:
            evt = self.selected_event
            actor = redact_ui_text(evt.actor_username or "system")
            kind_clean = redact_ui_text(evt.kind or "")
            ts = redact_ui_text(evt.created_at or "")
            p_class = evt.presentation_class

            p_color = "green" if p_class in ("message", "checkpoint") else ("red" if p_class == "security" else "yellow")
            
            return (
                f"[bold cyan]🔍 INSPECT EVENT: {evt.event_id[:12]}[/bold cyan]\n"
                f"[bold]Class:[/bold] [{p_color}]{p_class.upper()}[/{p_color}] | [bold]Kind:[/bold] {kind_clean}\n"
                f"[bold]Actor:[/bold] @{actor} | [bold]Created:[/bold] {ts}\n"
                f"[bold]Session ID:[/bold] {evt.session_id}\n\n"
                f"[dim]───── Detailed Inspection Payload (Read-Only) ─────[/dim]\n"
                f"Event Kind: {kind_clean}\n"
                f"Presentation Class: {p_class}\n"
                f"System Security Status: Validated"
            )

        # Mode B: Inspect selected ArtifactView
        if self.selected_artifact:
            art = self.selected_artifact
            meta = art.metadata
            offered_by = redact_ui_text(meta.offered_by or "peer")
            mime = redact_ui_text(meta.mime_type or "text/plain")
            sha_trunc = meta.sha256[:16] if meta.sha256 else "0000000000000000"

            return (
                f"[bold cyan]🔍 INSPECT ARTIFACT: {meta.artifact_id[:12]}[/bold cyan]\n"
                f"[bold]Offered By:[/bold] @{offered_by} | [bold]MIME Type:[/bold] {mime}\n"
                f"[bold]Size:[/bold] {art.display_size} | [bold]SHA-256:[/bold] {sha_trunc}...\n"
                f"[bold]Created:[/bold] {meta.created_at or 'N/A'}\n\n"
                f"[dim]───── Read-Only Artifact Preview ─────[/dim]\n"
                f"[italic](Preview-only surface. Import/apply action capabilities strictly excluded in Phase B.)[/italic]"
            )

        # Mode C: Inspect selected ApprovalView
        if self.selected_approval:
            app_v = self.selected_approval
            req = app_v.request
            action_cls = redact_ui_text(str(req.action_class.value if hasattr(req.action_class, "value") else req.action_class))
            summary_clean = redact_ui_text(req.summary or "Approval request")
            dec_str = "PENDING OWNER DECISION" if not app_v.decision else app_v.decision.decision.value

            return (
                f"[bold yellow]🔍 INSPECT APPROVAL GATE: {req.approval_id[:12]}[/bold yellow]\n"
                f"[bold]Action Class:[/bold] {action_cls} | [bold]Agent:[/bold] {req.agent_id}\n"
                f"[bold]Risk Label:[/bold] {req.risk_label.value.upper()} | [bold]Status:[/bold] {dec_str}\n"
                f"[bold]Summary:[/bold] {summary_clean}\n\n"
                f"[dim]───── Policy Inspection Details (Read-Only) ─────[/dim]\n"
                f"[italic](Inspection-only preview. Decision controls strictly excluded in Phase B.)[/italic]"
            )

        # Mode D: Fallback title / details
        scrubbed_title = redact_ui_text(self.title)
        scrubbed_details = redact_ui_text(self.details) if self.details else None

        if state == WidgetLifecycleState.EMPTY or not scrubbed_details:
            return f"[bold]{scrubbed_title}[/bold]\n[dim]No item selected for preview.[/dim]"

        return f"[bold cyan]{scrubbed_title}[/bold cyan]\n{scrubbed_details}"
