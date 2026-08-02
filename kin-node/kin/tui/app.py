"""Application shell for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §3, §4, §5, §14.4
"""

import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key, Resize
from textual.widgets import Input, Static

from kin.tui.errors import tui_error_boundary
from kin.tui.help import HelpOverlayScreen
from kin.tui.keymap import DEFAULT_KEYMAP, KeyBindingSpec, build_textual_bindings
from kin.tui.layout import Breakpoint, classify_breakpoint
from kin.tui.palette import CommandItem, CommandPaletteModal, QuickSwitcherModal
from kin.tui.persistence import (
    UiStatePreferences,
    get_profile_dir,
    load_ui_preferences,
    save_ui_preferences,
)
from kin.tui.shell import ConfirmationModal, Inspector, MainCanvas, Sidebar, StatusBar, WorkspaceTabBar
from kin.tui.tokens import resolve_theme
from kin.tui.widgets import WidgetLifecycleState
from kin.tui.widgets.compose_modal import ComposeMessageModal
from kin.tui.widgets.session_arena import SessionArenaWidget
from kin.tui.local_state import send_human_message_to_session_action
from kin.tui.workspace import WorkspaceTabManager


def is_interactive_tty() -> bool:
    """Check if standard input and output streams are attached to an interactive TTY."""
    return bool(getattr(sys.stdin, "isatty", lambda: False)() and getattr(sys.stdout, "isatty", lambda: False)())


class KinApp(App[None]):
    """KIN V1.1 TUI Application Shell for Milestone T2."""

    TITLE = "KIN — Personal Agent Network"
    SUB_TITLE = "V1.1 Terminal UI"

    CSS = """
    #middle-pane {
        width: 100%;
        height: 1fr;
    }
    """

    # BINDINGS are programmatically driven directly by DEFAULT_KEYMAP from keymap.py (§14.4)
    BINDINGS = build_textual_bindings()

    def __init__(self, theme_name: str = "kin-graphite", profile_name: str = "default", profile_dir: Optional[Path] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        resolution = resolve_theme(theme_name)
        self.theme_tokens = resolution.theme
        self.requested_theme = resolution.requested_name
        self.is_theme_fallback = resolution.is_fallback
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)

        self.tab_manager = WorkspaceTabManager()

        self.tab_bar = WorkspaceTabBar()
        self.sidebar = Sidebar(profile_dir=self.profile_dir, profile_name=self.profile_name)
        self.canvas = MainCanvas()
        self.inspector = Inspector()
        self.status_bar = StatusBar(profile_name=profile_name)

        self.current_breakpoint: Breakpoint = "wide"
        self.has_shown_resize_hint: bool = False
        self.prefs: UiStatePreferences = UiStatePreferences()

        # Command Palette candidate index (§5.4)
        self.command_index: List[CommandItem] = [
            CommandItem("dispatch", "Dispatch a collaboration", "Actions", "d", recent=True),
            CommandItem("open_agents", "Open Agents workspace", "Navigation", "a", recent=True),
            CommandItem("open_network", "Open Network workspace", "Navigation", "n"),
            CommandItem("open_inbox", "Open Inbox / Needs You", "Navigation", "i", contextual=True),
            CommandItem("open_approvals", "Open Approvals queue", "Navigation", "p", contextual=True),
            CommandItem("help", "Contextual help", "System", "?"),
            CommandItem("guide", "Open kin guide", "System"),
            CommandItem("theme_graphite", "Change theme: KIN Graphite", "Settings"),
            CommandItem("cancel_archive", "Cancel / Archive active work", "Actions", "x", consequential=True),
        ]

    def compose(self) -> ComposeResult:
        """Compose the five persistent stable regions (§3.1)."""
        yield self.tab_bar
        with Horizontal(id="middle-pane"):
            yield self.sidebar
            yield self.canvas
            yield self.inspector
        yield self.status_bar

    def on_mount(self) -> None:
        """Load UI preferences on mount and apply saved geometry/preferences."""
        prefs, status_msg = load_ui_preferences(self.profile_name)
        self.prefs = prefs

        self.sidebar.set_width(self.prefs.sidebar_width)
        self.sidebar.set_collapsed(self.prefs.sidebar_collapsed)
        self.sidebar.section_collapse = dict(self.prefs.sidebar_section_collapse)

        self.inspector.set_width(self.prefs.inspector_width)
        self.inspector.set_visible(self.prefs.inspector_visible)

        self.sync_tab_bar()

        if status_msg:
            self.status_bar.status_message = status_msg
            self.status_bar.refresh()

    def sync_tab_bar(self) -> None:
        """Synchronize WorkspaceTabBar UI with WorkspaceTabManager state."""
        self.tab_bar.tabs = [t.title for t in self.tab_manager.tabs]
        active = self.tab_manager.get_active_tab()
        self.tab_bar.active_tab = active.title
        self.tab_bar.refresh()

        session_id = active.tab_id
        if session_id.startswith("tab:"):
            session_id = session_id[4:]
        elif session_id.startswith("view:"):
            session_id = session_id[5:]
        elif session_id.startswith("open:"):
            session_id = session_id[5:]

        self.canvas.set_active_tab_kind(
            active.kind,
            session_id=session_id,
            profile_dir=self.profile_dir,
            profile_name=self.profile_name,
        )

    def on_resize(self, event: Resize) -> None:
        """Handle terminal geometry changes and classify breakpoint tiers (§3.2)."""
        bp = classify_breakpoint(event.size.width, event.size.height)
        self.current_breakpoint = bp

        if bp == "minimal":
            if not self.has_shown_resize_hint:
                self.status_bar.status_message = "Resize terminal to at least 90x28 for full experience."
                self.status_bar.refresh()
                self.has_shown_resize_hint = True
        elif bp == "compact":
            self.sidebar.set_collapsed(True)
            self.inspector.set_visible(False)
        else:  # wide or standard
            self.sidebar.set_collapsed(self.prefs.sidebar_collapsed)
            if bp == "wide":
                self.inspector.set_visible(self.prefs.inspector_visible)
            else:
                self.inspector.set_visible(False)

    # ═══════════════════════════════════════════════════════════════════
    # Esc Priority Chain (§4, §14.4)
    # ═══════════════════════════════════════════════════════════════════
    def action_action_handle_escape(self) -> None:
        """Exact 3-stage Esc priority chain:

        Stage 1: Clear active search/filter if active.
        Stage 2: Close open drawer/modal screen if active.
        Stage 3: Return focus to main canvas workspace.
        """
        # Stage 1: Clear active search/filter query if present in sidebar or focused input
        if self.sidebar.filter_query:
            self.sidebar.filter_query = ""
            self.sidebar.refresh()
            self.status_bar.status_message = "Cleared sidebar filter."
            self.status_bar.refresh()
            return

        focused = self.focused
        if isinstance(focused, Input) and focused.value:
            focused.value = ""
            return

        # Stage 2: Close open modal/screen if active
        if len(self.screen_stack) > 1:
            self.pop_screen()
            return

        # Stage 3: Return focus to main canvas input
        cmd_input = self.query_one("#command-input", Input)
        cmd_input.focus()
        self.status_bar.status_message = "Returned focus to main canvas."
        self.status_bar.refresh()

    # ═══════════════════════════════════════════════════════════════════
    # Command Palette, Quick Switcher, & Help Overlays
    # ═══════════════════════════════════════════════════════════════════
    def action_action_command_palette(self) -> None:
        """Open Command Palette modal overlay (Ctrl+K)."""
        def handle_selected(item: Optional[CommandItem]) -> None:
            if item:
                if item.command_id.startswith("colon:"):
                    self.execute_colon_command(item.title)
                elif item.consequential:
                    self.gate_consequential_action(item.title, "selected target")
                else:
                    self.status_bar.status_message = f"Executed command: {item.title}"
                    self.status_bar.refresh()

        self.push_screen(CommandPaletteModal(self.command_index), handle_selected)

    def execute_colon_command(self, colon_cmd_str: str) -> None:
        """Execute validated colon command."""
        parts = colon_cmd_str[1:].split(maxsplit=1)
        cmd_name = parts[0].lower() if parts else ""
        arg_str = parts[1] if len(parts) > 1 else ""

        if cmd_name == "theme":
            res = resolve_theme(arg_str)
            self.theme_tokens = res.theme
            self.prefs.theme = res.requested_name
            save_ui_preferences(self.prefs, self.profile_name)
            self.status_bar.status_message = f"Theme updated to '{res.requested_name}'."
            self.status_bar.refresh()
        elif cmd_name == "open":
            self.tab_manager.open_tab(f"open:{arg_str}", arg_str.title(), "search")
            self.sync_tab_bar()
        elif cmd_name == "quit":
            self.exit(0)

    def action_action_quick_switcher(self) -> None:
        """Open Quick Switcher modal overlay (Ctrl+P) (§A3)."""
        from kin.tui.local_state import get_all_agent_summaries, get_local_contacts_summaries

        candidates: List[Tuple[str, str, str]] = []

        # 1. Real open workspace tabs
        for tab in self.tab_manager.tabs:
            candidates.append((f"tab_{tab.kind}", f"{tab.title} Workspace", "Workspace"))

        p_dir = getattr(self, "profile_dir", None) or (Path.home() / ".kin" / "profiles" / self.profile_name)

        # 2. Real agents
        if p_dir.exists():
            local_agents, peer_agents = get_all_agent_summaries(p_dir, self.profile_name)
            for a in local_agents + peer_agents:
                candidates.append((f"agent_{a.agent_id}", f"{a.name} ({a.availability})", "Agent"))

        # 3. Real contacts
        if p_dir.exists():
            contacts = get_local_contacts_summaries(p_dir, self.profile_name)
            for c in contacts:
                status_lbl = "verified" if c.verified_at else "unverified"
                candidates.append((f"peer_{c.username}", f"{c.display_name or c.username} ({status_lbl})", "Contact"))

        def handle_selected(target_id: Optional[str]) -> None:
            if target_id:
                if target_id.startswith("tab_"):
                    k = target_id.replace("tab_", "")
                    self.tab_manager.open_tab(k, k.title(), k if k in ("agents", "network", "inbox", "dispatch") else "home")
                    self.sync_tab_bar()
                else:
                    self.status_bar.status_message = f"Quick switched to '{target_id}'."
                    self.status_bar.refresh()

        self.push_screen(QuickSwitcherModal(candidates), handle_selected)

    def action_action_toggle_help(self) -> None:
        """Toggle Contextual Help overlay screen (?)."""
        self.push_screen(HelpOverlayScreen())

    # ═══════════════════════════════════════════════════════════════════
    # Tab Lifecycle Navigation (§4.1, §4.2)
    # ═══════════════════════════════════════════════════════════════════
    def action_action_open_dispatch(self) -> None:
        ok, msg = self.tab_manager.open_tab("dispatch:draft", "Dispatch", "dispatch")
        self.sync_tab_bar()
        if msg:
            self.status_bar.status_message = msg
            self.status_bar.refresh()

    def action_action_open_agents(self) -> None:
        ok, msg = self.tab_manager.open_tab("agents", "Agents", "agents", singleton=True)
        self.sync_tab_bar()
        if msg:
            self.status_bar.status_message = msg
            self.status_bar.refresh()

    def action_action_open_network(self) -> None:
        ok, msg = self.tab_manager.open_tab("network", "Network", "network", singleton=True)
        self.sync_tab_bar()
        if msg:
            self.status_bar.status_message = msg
            self.status_bar.refresh()

    def action_action_open_inbox(self) -> None:
        ok, msg = self.tab_manager.open_tab("inbox", "Inbox", "inbox", singleton=True)
        self.sync_tab_bar()
        if msg:
            self.status_bar.status_message = msg
            self.status_bar.refresh()

    def action_action_open_approvals(self) -> None:
        ok, msg = self.tab_manager.open_tab("inbox", "Inbox", "inbox", singleton=True)
        self.sync_tab_bar()

    def action_action_help(self) -> None:
        self.push_screen(HelpOverlayScreen())

    def action_open_guide(self) -> None:
        from kin.tui.guide import GuideOverlayScreen
        self.push_screen(GuideOverlayScreen())

    def action_action_next_tab(self) -> None:
        self.tab_manager.cycle_tab(+1)
        self.sync_tab_bar()

    def action_action_prev_tab(self) -> None:
        self.tab_manager.cycle_tab(-1)
        self.sync_tab_bar()

    def action_action_close_tab(self) -> None:
        ok, msg = self.tab_manager.close_tab()
        self.sync_tab_bar()
        if msg:
            self.status_bar.status_message = msg
            self.status_bar.refresh()

    def action_action_reopen_tab(self) -> None:
        ok, msg = self.tab_manager.reopen_last_tab()
        self.sync_tab_bar()
        if msg:
            self.status_bar.status_message = msg
            self.status_bar.refresh()

    def action_action_save_draft(self) -> None:
        active = self.tab_manager.get_active_tab()
        if active.kind == "dispatch":
            active.dirty = False
            self.status_bar.status_message = "Dispatch draft saved locally."
            self.status_bar.refresh()

    def jump_tab(self, idx: int) -> None:
        if self.tab_manager.jump_to_tab_index(idx):
            self.sync_tab_bar()

    def action_action_jump_tab_1(self) -> None: self.jump_tab(1)
    def action_action_jump_tab_2(self) -> None: self.jump_tab(2)
    def action_action_jump_tab_3(self) -> None: self.jump_tab(3)
    def action_action_jump_tab_4(self) -> None: self.jump_tab(4)
    def action_action_jump_tab_5(self) -> None: self.jump_tab(5)
    def action_action_jump_tab_6(self) -> None: self.jump_tab(6)
    def action_action_jump_tab_7(self) -> None: self.jump_tab(7)
    def action_action_jump_tab_8(self) -> None: self.jump_tab(8)
    def action_action_jump_tab_9(self) -> None: self.jump_tab(9)

    def action_focus_prev(self) -> None: self.action_focus_previous()
    def action_action_focus_prev(self) -> None: self.action_focus_previous()

    def action_action_replay_item(self) -> None:
        self.status_bar.status_message = "Replay not yet available."
        self.status_bar.refresh()

    def action_action_fork_item(self) -> None:
        self.status_bar.status_message = "Fork not yet available."
        self.status_bar.refresh()

    def action_action_open_actions(self) -> None:
        self.status_bar.status_message = "Actions menu not yet available."
        self.status_bar.refresh()

    def action_action_smart_quit(self) -> None:
        """Smart Quit (§5.1): Quit only from Home; otherwise return Home cleanly."""
        active = self.tab_manager.get_active_tab()
        if active.kind == "home":
            self.exit(0)
        else:
            if active.dirty:
                self.gate_consequential_action("Discard & Return Home", active.title, on_confirm=lambda: self.tab_manager.open_tab("home", "Home", "home"))
            else:
                self.tab_manager.open_tab("home", "Home", "home")
                self.sync_tab_bar()
                self.status_bar.status_message = "Returned to Home workspace."
                self.status_bar.refresh()

    # ═══════════════════════════════════════════════════════════════════
    # Arena Keybinding Action Handlers (§5.3, §14.8 Phase D)
    # ═══════════════════════════════════════════════════════════════════
    def _get_active_arena_widget(self) -> Optional[SessionArenaWidget]:
        active_tab = self.tab_manager.get_active_tab()
        if active_tab.kind != "session":
            return None
        try:
            return self.canvas.query_one(SessionArenaWidget)
        except Exception:
            return self.canvas.get_session_arena_widget()

    def action_action_lane_focus(self) -> None:
        arena = self._get_active_arena_widget()
        if arena:
            arena.toggle_focus_mode()
        else:
            self.status_bar.status_message = "Focus mode requires an active Session Arena tab."
            self.status_bar.refresh()

    def action_action_lane_transcript(self) -> None:
        arena = self._get_active_arena_widget()
        if arena:
            arena.switch_lane("transcript")
        else:
            self.status_bar.status_message = "Transcript lane requires an active Session Arena tab."
            self.status_bar.refresh()

    def action_action_lane_activity(self) -> None:
        arena = self._get_active_arena_widget()
        if arena:
            arena.switch_lane("activity")
        else:
            self.status_bar.status_message = "Activity lane requires an active Session Arena tab."
            self.status_bar.refresh()

    def action_action_lane_decisions(self) -> None:
        arena = self._get_active_arena_widget()
        if arena:
            arena.switch_lane("decisions")
        else:
            self.status_bar.status_message = "Decisions lane requires an active Session Arena tab."
            self.status_bar.refresh()

    def action_action_lane_needs_you(self) -> None:
        arena = self._get_active_arena_widget()
        if arena:
            arena.open_needs_you_lane()
        else:
            self.status_bar.status_message = "Needs-you lane requires an active Session Arena tab."
            self.status_bar.refresh()

    def action_action_compose_message(self) -> None:
        arena = self._get_active_arena_widget()
        if not arena:
            self.status_bar.status_message = "Compose message requires an active Session Arena tab."
            self.status_bar.refresh()
            return

        session_id = arena.session_id
        peer_username = ""
        if arena.session_summary:
            peer_username = (
                arena.session_summary.receiver_username
                if arena.session_summary.initiator_username == self.profile_name
                else arena.session_summary.initiator_username
            )

        def handle_composed_message(msg_text: Optional[str]) -> None:
            if not msg_text:
                self.status_bar.status_message = "Cancelled compose message."
                self.status_bar.refresh()
                return

            ok, result_dict, err = send_human_message_to_session_action(
                profile_name=self.profile_name,
                session_id=session_id,
                message_text=msg_text,
                profile_dir=self.profile_dir,
            )
            if ok:
                self.status_bar.status_message = f"Message sent to session {session_id}."
                arena.load_arena_data()
            elif err:
                self.status_bar.status_message = f"Failed to send message: {err.user_message}"
            else:
                self.status_bar.status_message = "Failed to send message."
            self.status_bar.refresh()

        self.push_screen(ComposeMessageModal(session_id=session_id, peer_username=peer_username), handle_composed_message)

    def action_action_session_state_menu(self) -> None:
        arena = self._get_active_arena_widget()
        if arena:
            arena.open_session_state_menu()
        else:
            self.status_bar.status_message = "Session state menu requires an active Session Arena tab."
            self.status_bar.refresh()

    # ═══════════════════════════════════════════════════════════════════
    # Sidebar Tree Interaction (§4.3)
    # ═══════════════════════════════════════════════════════════════════
    def action_action_cursor_down(self) -> None:
        self.sidebar.move_selection(+1)

    def action_action_cursor_up(self) -> None:
        self.sidebar.move_selection(-1)

    def action_action_cursor_top(self) -> None:
        self.sidebar.move_to_boundary(first=True)

    def action_action_cursor_bottom(self) -> None:
        self.sidebar.move_to_boundary(first=False)

    def action_action_focus_filter(self) -> None:
        """Focus SearchField widget in SidebarTree (§14.5)."""
        if hasattr(self.sidebar, "search_field"):
            self.sidebar.search_field.set_query("")
            self.sidebar.search_field.set_lifecycle_state(WidgetLifecycleState.FOCUSED)
            try:
                self.set_focus(self.sidebar.search_field)
            except Exception:
                pass
        elif hasattr(self.sidebar, "filter_query"):
            self.sidebar.filter_query = ""
        self.sidebar.refresh()

    def action_action_activate_selection(self) -> None:
        node = self.sidebar.get_selected_node()
        if not node:
            return
        if node.kind == "section":
            updated_collapse = self.sidebar.toggle_section_collapse(node.section)
            self.prefs.sidebar_section_collapse = updated_collapse
            save_ui_preferences(self.prefs, self.profile_name)
        else:
            tab_id = node.target_tab_id or f"view:{node.node_id}"
            kind = "home" if node.node_id == "space_home" else ("inbox" if "inbox" in tab_id else "session")
            self.tab_manager.open_tab(tab_id, node.title, kind)
            self.sync_tab_bar()

    def action_action_preview_selection(self) -> None:
        node = self.sidebar.get_selected_node()
        if node:
            self.inspector.preview_item(node)
            self.status_bar.status_message = f"Previewing '{node.title}' in Inspector."
            self.status_bar.refresh()

    def action_action_open_in_new_tab(self) -> None:
        node = self.sidebar.get_selected_node()
        if node and node.kind == "item":
            self.tab_manager.open_tab(f"tab:{node.node_id}", node.title, "session")
            self.sync_tab_bar()

    # ═══════════════════════════════════════════════════════════════════
    # Consequential Action Gate (§5.3, §14.4)
    # ═══════════════════════════════════════════════════════════════════
    def action_action_consequential_action(self) -> None:
        node = self.sidebar.get_selected_node()
        target = node.title if node else "active session"
        self.gate_consequential_action("Cancel / Archive", target)

    def gate_consequential_action(self, action_name: str, target_name: str, on_confirm: Optional[Callable[[], None]] = None) -> None:
        """Gate any consequential action behind confirmation modal (§5.3)."""
        def handle_result(confirmed: bool) -> None:
            if confirmed:
                if on_confirm:
                    on_confirm()
                self.status_bar.status_message = f"Confirmed and executed '{action_name}' on '{target_name}'."
            else:
                self.status_bar.status_message = f"Cancelled '{action_name}'."
            self.status_bar.refresh()

        self.push_screen(ConfirmationModal(action_name, target_name), handle_result)

    # Geometry actions
    def action_decrease_sidebar_width(self) -> None:
        new_width = self.prefs.sidebar_width - 2
        self.sidebar.set_width(new_width)
        self.prefs.sidebar_width = self.sidebar.sidebar_width
        save_ui_preferences(self.prefs, self.profile_name)

    def action_increase_sidebar_width(self) -> None:
        new_width = self.prefs.sidebar_width + 2
        self.sidebar.set_width(new_width)
        self.prefs.sidebar_width = self.sidebar.sidebar_width
        save_ui_preferences(self.prefs, self.profile_name)

    def action_decrease_inspector_width(self) -> None:
        new_width = self.prefs.inspector_width - 2
        self.inspector.set_width(new_width)
        self.prefs.inspector_width = self.inspector.inspector_width
        save_ui_preferences(self.prefs, self.profile_name)

    def action_increase_inspector_width(self) -> None:
        new_width = self.prefs.inspector_width + 2
        self.inspector.set_width(new_width)
        self.prefs.inspector_width = self.inspector.inspector_width
        save_ui_preferences(self.prefs, self.profile_name)

    def action_toggle_sidebar(self) -> None:
        new_collapsed = not self.sidebar.collapsed
        self.sidebar.set_collapsed(new_collapsed)
        self.prefs.sidebar_collapsed = new_collapsed
        save_ui_preferences(self.prefs, self.profile_name)

    def action_toggle_inspector(self) -> None:
        new_visible = not self.inspector.visible_state
        self.inspector.set_visible(new_visible)
        self.prefs.inspector_visible = new_visible
        save_ui_preferences(self.prefs, self.profile_name)


def run_tui_app(theme_name: str = "kin-graphite", profile_name: str = "default") -> int:
    """Launcher entry point for KinApp."""
    if not is_interactive_tty():
        print("KIN TUI requires an interactive terminal; run a subcommand instead.")
        return 0

    profile_dir = get_profile_dir(profile_name)

    with tui_error_boundary(profile_dir=profile_dir):
        app = KinApp(theme_name=theme_name, profile_name=profile_name)
        app.run()

    return 0
