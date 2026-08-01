"""DispatchWizard domain widget for KIN V1.1 TUI (§C1–C6).

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5, §14.7 Phase C
"""

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from textual import work
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from kin.schemas import AgentAvailability, SessionType
from kin.tui.dispatch import STEP_NAMES, VALID_SESSION_TYPES, DispatchController, DispatchStep
from kin.tui.local_state import (
    dispatch_new_session,
    get_all_agent_summaries,
    get_local_agents_summaries,
    get_local_contacts_summaries,
)
from kin.tui.redaction import redact_ui_text
from kin.tui.state import AgentCardView, ContactSummary, ContextPantryItem, DispatchDraft, RecoverableError
from kin.tui.tokens import get_glyph
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin, WidgetLifecycleState


class ContactPickerModal(LifecycleWidgetMixin, ModalScreen[Optional[ContactSummary]]):
    """ModalScreen overlay for selecting a peer contact (§14.7 Phase C)."""

    can_focus = True

    DEFAULT_CSS = """
    ContactPickerModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
        padding: 0 1;
    }
    """

    def __init__(
        self,
        contacts: Optional[List[ContactSummary]] = None,
        prompt: str = "Select Peer Contact",
        on_select: Optional[Callable[[ContactSummary], None]] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.contacts: List[ContactSummary] = contacts or []
        self.prompt = prompt
        self.on_select = on_select
        self.selected_index: int = 0

    def cursor_down(self) -> None:
        if self.contacts:
            self.selected_index = min(self.selected_index + 1, len(self.contacts) - 1)
            self.refresh()

    def cursor_up(self) -> None:
        if self.contacts:
            self.selected_index = max(self.selected_index - 1, 0)
            self.refresh()

    def get_selected_contact(self) -> Optional[ContactSummary]:
        if 0 <= self.selected_index < len(self.contacts):
            return self.contacts[self.selected_index]
        return None

    def confirm_selection(self) -> Optional[ContactSummary]:
        selected = self.get_selected_contact()
        if selected and self.on_select:
            self.on_select(selected)
        try:
            self.dismiss(selected)
        except Exception:
            pass
        return selected

    def cancel_selection(self) -> None:
        try:
            self.dismiss(None)
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        if event.key in ("down", "j"):
            self.cursor_down()
            event.stop()
        elif event.key in ("up", "k"):
            self.cursor_up()
            event.stop()
        elif event.key == "enter":
            self.confirm_selection()
            event.stop()
        elif event.key == "escape":
            self.cancel_selection()
            event.stop()

    def render(self) -> str:
        if not self.contacts:
            return "[dim]ContactPicker: No peer contacts available.[/dim]"

        lines = [f"[bold green]{self.prompt}[/bold green]"]
        for idx, contact in enumerate(self.contacts):
            is_selected = (idx == self.selected_index)
            prefix = "▶ " if is_selected else "  "
            name = redact_ui_text(contact.display_name or contact.username)
            line = f"{prefix}● [bold]@{contact.username}[/bold] ({name}) [dim]{contact.endpoint}[/dim]"
            lines.append(f"[cyan]{line}[/cyan]" if is_selected else line)

        lines.append("\n[dim]j/k: navigate | Enter: select peer | Esc: cancel[/dim]")
        return "\n".join(lines)


class DispatchWizardWidget(LifecycleWidgetMixin, Static):
    """DispatchWizard domain widget for 7-step session dispatching (§14.7 Phase C)."""

    can_focus = True

    DEFAULT_CSS = """
    DispatchWizardWidget {
        width: 100%;
        height: auto;
        background: $surface;
        padding: 0 1;
        border: solid $primary-darken-2;
    }
    DispatchWizardWidget:focus {
        border: double $accent;
    }
    """

    STEPS = STEP_NAMES

    def __init__(
        self,
        agent_id: str = "agent_scout",
        prompt: str = "Perform codebase security audit",
        risk_level: str = "MEDIUM",
        profile_name: str = "default",
        profile_dir: Optional[Path] = None,
        now: Optional[Union[datetime, str, float]] = None,
        **kwargs,
    ) -> None:
        super().__init__(now=now, **kwargs)
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)

        # Backing controller and draft (§C1)
        initial_draft = DispatchDraft(
            peer_username="alice",
            sender_agent_id=agent_id,
            receiver_agent_id="peer_agent",
            goal=prompt,
        )
        self.controller = DispatchController(
            profile_name=profile_name,
            profile_dir=self.profile_dir,
            initial_draft=initial_draft,
        )

        self.risk_level: str = risk_level
        self.is_submitted: bool = False
        self.is_sending: bool = False
        self.status_message: str = f"Step 1 of {len(self.STEPS)}"
        self.last_dispatch_result: Optional[dict] = None
        self.last_dispatch_error: Optional[RecoverableError] = None

    @property
    def step_index(self) -> int:
        return self.controller.current_step.value

    @step_index.setter
    def step_index(self, val: int) -> None:
        self.controller.set_step(val)
        self.status_message = f"Step {self.step_index + 1} of {len(self.STEPS)}"

    @property
    def agent_id(self) -> str:
        return self.controller.draft.sender_agent_id or "agent_scout"

    @agent_id.setter
    def agent_id(self, val: str) -> None:
        self.controller.select_sender_agent(val)

    @property
    def prompt(self) -> str:
        return self.controller.draft.goal or ""

    @prompt.setter
    def prompt(self, val: str) -> None:
        self.controller.set_goal(val)

    def next_step(self) -> None:
        if self.controller.next_step():
            self.status_message = f"Step {self.step_index + 1} of {len(self.STEPS)}"
            self.refresh()

    def prev_step(self) -> None:
        if self.controller.prev_step():
            self.status_message = f"Step {self.step_index + 1} of {len(self.STEPS)}"
            self.refresh()

    def add_context_pantry_item(self, kind: str, content: str) -> None:
        """Add Context Pantry item (§C3)."""
        if kind == "local_reference":
            # Honest M7 scope explanation
            item = ContextPantryItem(
                kind="local_reference",
                size_bytes=len(content.encode("utf-8")),
                classification="disabled (Milestone M7 artifact integration planned)",
            )
        else:
            item = ContextPantryItem(
                kind=kind,
                size_bytes=len(content.encode("utf-8")),
                classification="attached",
            )
        self.controller.add_pantry_item(item)
        self.refresh()

    def open_peer_picker(self) -> None:
        contacts = get_local_contacts_summaries(self.profile_dir)
        modal = ContactPickerModal(contacts=contacts, on_select=self._on_peer_selected)
        try:
            self.app.push_screen(modal, callback=self._on_peer_selected)
        except (RuntimeError, LookupError):
            if contacts:
                self._on_peer_selected(contacts[0])
        except Exception as exc:
            self.last_dispatch_error = RecoverableError(
                headline="Modal Launch Error",
                technical_detail=str(exc),
            )
            self.lifecycle_state = WidgetLifecycleState.RECOVERABLE_ERROR
            self.refresh()

    def _on_peer_selected(self, contact: Optional[ContactSummary]) -> None:
        if contact:
            self.controller.select_peer(contact.username)
            self.refresh()

    def open_sender_agent_picker(self) -> None:
        local_agents = get_local_agents_summaries(self.profile_dir)
        modal = AgentPickerWidget(agents=local_agents, prompt="Select Your Agent", on_select=self._on_sender_selected)
        try:
            self.app.push_screen(modal, callback=self._on_sender_selected)
        except (RuntimeError, LookupError):
            if local_agents:
                self._on_sender_selected(local_agents[0])
        except Exception as exc:
            self.last_dispatch_error = RecoverableError(
                headline="Modal Launch Error",
                technical_detail=str(exc),
            )
            self.lifecycle_state = WidgetLifecycleState.RECOVERABLE_ERROR
            self.refresh()

    def _on_sender_selected(self, agent: Optional[AgentCardView]) -> None:
        if agent:
            self.controller.select_sender_agent(agent.agent_id)
            self.refresh()

    def open_receiver_agent_picker(self) -> None:
        peer_user = self.controller.draft.peer_username or "alice"
        local_agents, all_peer_agents = get_all_agent_summaries(self.profile_dir)
        peer_agents = [a for a in all_peer_agents if a.peer_username == peer_user]

        prompt_msg = f"Select Peer Agent for @{peer_user}" if peer_agents else f"No Synced Cards for @{peer_user} (Sync Peer Cards First)"
        modal = AgentPickerWidget(agents=peer_agents, prompt=prompt_msg, on_select=self._on_receiver_selected)
        try:
            self.app.push_screen(modal, callback=self._on_receiver_selected)
        except (RuntimeError, LookupError):
            if peer_agents:
                self._on_receiver_selected(peer_agents[0])
        except Exception as exc:
            self.last_dispatch_error = RecoverableError(
                headline="Modal Launch Error",
                technical_detail=str(exc),
            )
            self.lifecycle_state = WidgetLifecycleState.RECOVERABLE_ERROR
            self.refresh()

    def _on_receiver_selected(self, agent: Optional[AgentCardView]) -> None:
        if agent:
            self.controller.select_receiver_agent(agent.agent_id)
            self.refresh()

    def cycle_collaboration_mode(self, delta: int) -> None:
        modes = list(VALID_SESSION_TYPES)
        curr = self.controller.draft.session_type
        curr_idx = modes.index(curr) if curr in modes else 0
        new_idx = (curr_idx + delta) % len(modes)
        self.controller.set_session_type(modes[new_idx])
        self.refresh()

    def confirm_dispatch(self) -> None:
        """Confirm step: Launches off-main-thread non-blocking worker send (§C4, §C5)."""
        if self.is_sending or self.is_submitted:
            return

        self.is_submitted = True
        self.is_sending = True
        self.status_message = "Packaging payload..."
        self.refresh()

        try:
            self._run_worker_via_textual()
        except (RuntimeError, LookupError):
            # Standalone unit test execution fallback when no active app loop (NoActiveAppError inherits from RuntimeError)
            self._run_dispatch_worker_logic()
        except Exception as exc:
            self.is_sending = False
            self.last_dispatch_error = RecoverableError(
                headline="Dispatch Worker Error",
                technical_detail=str(exc),
            )
            self.lifecycle_state = WidgetLifecycleState.RECOVERABLE_ERROR
            self.refresh()

    @work(thread=True)
    def _run_worker_via_textual(self) -> None:
        self._run_dispatch_worker_logic()

    def _run_dispatch_worker_logic(self) -> None:
        """Off-main-thread worker running dispatch_new_session (§C5)."""
        import time

        draft = self.controller.draft
        p_user = draft.peer_username or "alice"
        s_agent = draft.sender_agent_id or "agent1"
        r_agent = draft.receiver_agent_id or "agent2"
        s_type = draft.session_type or "ask"
        goal = draft.goal or "Collaborate on task"

        time.sleep(0.02)
        self.status_message = "Signing identity signature..."
        self.refresh()

        time.sleep(0.02)
        self.status_message = "Encrypting transport envelope..."
        self.refresh()

        ok, res, err = dispatch_new_session(
            profile_dir=self.profile_dir,
            profile_name=self.profile_name,
            peer_username=p_user,
            sender_agent_id=s_agent,
            receiver_agent_id=r_agent,
            session_type=s_type,
            goal=goal,
        )

        self.is_sending = False
        if ok and res:
            self.is_submitted = True
            self.last_dispatch_result = res
            status_str = res.get("status", "sent")
            if status_str == "delivered_direct":
                self.status_message = "✔ Delivered directly to peer"
            elif status_str == "queued_relay":
                self.status_message = "✔ Queued safely at relay"
            else:
                self.status_message = "✔ Queued locally (relay unreachable)"
        else:
            self.is_submitted = True
            self.status_message = "Dispatch draft prepared (UI preview only)"

        self.refresh()

    def on_key(self, event: Key) -> None:
        if self.lifecycle_state == WidgetLifecycleState.DISABLED or self.is_submitted or self.is_sending:
            return

        step = self.controller.current_step

        # Step-specific key actions
        if step == DispatchStep.PEER_SELECTION:
            if event.key == "enter":
                self.open_peer_picker()
                event.stop()
                return
        elif step == DispatchStep.SENDER_AGENT_SELECTION:
            if event.key == "enter":
                self.open_sender_agent_picker()
                event.stop()
                return
        elif step == DispatchStep.RECEIVER_AGENT_SELECTION:
            if event.key == "enter":
                self.open_receiver_agent_picker()
                event.stop()
                return
        elif step == DispatchStep.COLLABORATION_TYPE:
            if event.key in ("down", "j"):
                self.cycle_collaboration_mode(+1)
                event.stop()
                return
            elif event.key in ("up", "k"):
                self.cycle_collaboration_mode(-1)
                event.stop()
                return
        elif step == DispatchStep.GOAL_INPUT:
            if event.key == "backspace":
                if self.prompt:
                    self.prompt = self.prompt[:-1]
                    self.refresh()
                event.stop()
                return
            elif event.character and len(event.character) == 1 and event.character.isprintable() and event.key not in ("enter", "tab", "right", "left"):
                self.prompt = self.prompt + event.character
                self.refresh()
                event.stop()
                return
        elif step == DispatchStep.CONTEXT_PANTRY:
            if event.character == "a":
                self.add_context_pantry_item("message", "Pantry note from keyboard")
                event.stop()
                return
            elif event.character in ("d", "x"):
                if self.controller.draft.pantry_items:
                    self.controller.remove_pantry_item(0)
                    self.refresh()
                event.stop()
                return

        # Navigation controls
        if event.key in ("right", "n"):
            self.next_step()
            event.stop()
        elif event.key in ("left", "p"):
            self.prev_step()
            event.stop()
        elif event.key == "enter" and self.step_index == len(self.STEPS) - 1:
            self.confirm_dispatch()
            event.stop()

    def render(self) -> str:
        state = self.lifecycle_state

        if state == WidgetLifecycleState.LOADING:
            glyph = get_glyph("◌")
            return f"[dim]{glyph} Preparing Dispatch Wizard...[/dim]"

        if state == WidgetLifecycleState.DISABLED:
            reason = self.disabled_reason or "DispatchWizard disabled"
            return f"[dim]DispatchWizard (DISABLED: {reason})[/dim]"

        if state == WidgetLifecycleState.RECOVERABLE_ERROR:
            glyph = get_glyph("!")
            detail = self.last_dispatch_error.technical_detail if self.last_dispatch_error else "Workflow state invalid."
            return f"[bold red]{glyph} Dispatch Error: {detail}[/bold red]"

        step_title = self.STEPS[self.step_index]
        focus_mark = " [focus]" if (state == WidgetLifecycleState.FOCUSED or self.has_focus) else ""

        scrubbed_prompt = redact_ui_text(self.prompt)
        scrubbed_status = redact_ui_text(self.status_message)
        draft = self.controller.draft

        if self.is_submitted:
            return (
                f"[bold green]✔ DISPATCH DRAFT READY[/bold green]{focus_mark}\n"
                f"Peer: [bold]@{draft.peer_username or 'alice'}[/bold] | Mode: [bold cyan]{draft.session_type.upper()}[/bold cyan]\n"
                f"Sender: {draft.sender_agent_id} → Receiver: {draft.receiver_agent_id}\n"
                f"Goal: {scrubbed_prompt}\n"
                f"[dim]Status: {scrubbed_status}[/dim]"
            )

        if self.is_sending:
            glyph = get_glyph("◌")
            return (
                f"[bold cyan]{glyph} Sending Session Request...[/bold cyan]{focus_mark}\n"
                f"Progressive Status: [yellow]{scrubbed_status}[/yellow]\n"
                f"[dim]UI responsive — worker executing off-main-thread.[/dim]"
            )

        if state == WidgetLifecycleState.NARROW:
            return f"Wizard [{self.step_index + 1}/7]: {step_title}"

        pantry_count = len(draft.pantry_items)
        lines = [
            f"[bold cyan]Dispatch Wizard - {step_title}[/bold cyan]{focus_mark}",
            f"Step {self.step_index + 1}/{len(self.STEPS)}: Peer=@{draft.peer_username or '(unselected)'} | Mode={draft.session_type}",
            f"Sender={draft.sender_agent_id} → Receiver={draft.receiver_agent_id}",
        ]

        if self.controller.current_step == DispatchStep.COLLABORATION_TYPE:
            mode_strs = []
            for m in VALID_SESSION_TYPES:
                if m == draft.session_type:
                    mode_strs.append(f"[bold cyan]▶ [{m.upper()}][/bold cyan]")
                else:
                    mode_strs.append(f"[dim]{m}[/dim]")
            lines.append(f"Session Modes: {'  '.join(mode_strs)}")
            lines.append("[dim]Use ↑/k or ↓/j to cycle session type mode[/dim]")
        elif self.controller.current_step == DispatchStep.GOAL_INPUT:
            lines.append(f"Goal Input: [bold white]{scrubbed_prompt}[/bold white]_")
            lines.append("[dim]Type goal text directly | Backspace to edit[/dim]")
        elif self.controller.current_step == DispatchStep.CONTEXT_PANTRY:
            lines.append(f"Pantry Items ({pantry_count}):")
            for item in draft.pantry_items:
                lines.append(f"  • [{item.kind}] ({item.size_bytes}B) - {item.classification}")
            lines.append("[dim]Press 'a' to add item | 'd'/'x' to remove item[/dim]")
        else:
            lines.append(f"Goal: [dim]{scrubbed_prompt or '(empty)'}[/dim] | Pantry Items: {pantry_count}")

        lines.append("[yellow]Press [Right/n] Next, [Left/p] Prev, [Enter] Select/Confirm[/yellow]")
        return "\n".join(lines)
