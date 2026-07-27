"""Workspace Tab Manager for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §4.1, §4.2, §14.4
"""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple


TabKind = Literal["home", "agents", "network", "inbox", "dispatch", "session", "search", "launcher"]


@dataclass
class WorkspaceTab:
    """Represents a single workspace tab state."""

    tab_id: str
    title: str
    kind: TabKind
    singleton: bool = False
    closeable: bool = True
    dirty: bool = False
    badge: Optional[str] = None
    glyph: str = "○"


class WorkspaceTabManager:
    """Manages workspace tab lifecycle, ordering, singleton rules, and reopen stack."""

    def __init__(self) -> None:
        # Home is always tab index 0 and non-closeable (§4.1)
        self.home_tab = WorkspaceTab(
            tab_id="home", title="Home", kind="home", singleton=True, closeable=False, glyph="●"
        )
        self.tabs: List[WorkspaceTab] = [self.home_tab]
        self.active_tab_id: str = "home"
        self.closed_tabs_stack: List[WorkspaceTab] = []

    def get_tab(self, tab_id: str) -> Optional[WorkspaceTab]:
        for t in self.tabs:
            if t.tab_id == tab_id:
                return t
        return None

    def get_active_tab(self) -> WorkspaceTab:
        active = self.get_tab(self.active_tab_id)
        return active if active else self.home_tab

    def open_tab(
        self,
        tab_id: str,
        title: str,
        kind: TabKind,
        singleton: bool = False,
        closeable: bool = True,
        badge: Optional[str] = None,
        glyph: str = "○",
    ) -> Tuple[bool, Optional[str]]:
        """Open or activate a workspace tab (§4.1, §14.4).

        Returns:
          (success, status_or_warning_message)
        """
        existing = self.get_tab(tab_id)
        if existing:
            self.active_tab_id = existing.tab_id
            return True, f"Focused existing singleton {existing.title} tab."

        # Check singleton rules for kinds: agents, network, inbox
        if singleton or kind in ("agents", "network", "inbox"):
            for t in self.tabs:
                if t.kind == kind:
                    self.active_tab_id = t.tab_id
                    return True, f"Focused existing singleton {t.title} tab."

        # Check dispatch draft rules: one reusable draft tab
        if kind == "dispatch":
            for t in self.tabs:
                if t.kind == "dispatch":
                    if t.dirty:
                        return False, "Unsaved changes in active Dispatch draft!"
                    self.active_tab_id = t.tab_id
                    return True, "Focused existing Dispatch draft tab."

        # Create new tab in stable order
        new_tab = WorkspaceTab(
            tab_id=tab_id,
            title=title,
            kind=kind,
            singleton=singleton,
            closeable=closeable,
            badge=badge,
            glyph=glyph,
        )
        self.tabs.append(new_tab)
        self.active_tab_id = new_tab.tab_id
        return True, None

    def close_tab(self, tab_id: Optional[str] = None, force: bool = False) -> Tuple[bool, Optional[str]]:
        """Close a closeable workspace tab (§4.1).

        Home tab can NEVER be closed (Ctrl+W on Home is a no-op).
        """
        target_id = tab_id or self.active_tab_id
        target = self.get_tab(target_id)

        if not target:
            return False, "Tab not found."

        if not target.closeable or target.kind == "home":
            # No-op on home tab per §4.1
            return False, "Home tab cannot be closed."

        if target.dirty and not force:
            return False, f"Cannot close tab '{target.title}': unsaved draft changes!"

        # Remove tab while maintaining relative ordering
        idx = self.tabs.index(target)
        self.tabs.remove(target)

        # Push onto closed tabs stack if non-sensitive (all fixture tabs are non-sensitive at T2)
        self.closed_tabs_stack.append(target)

        # Update active tab to nearest neighbor or home
        if self.active_tab_id == target_id:
            new_idx = max(0, idx - 1)
            self.active_tab_id = self.tabs[new_idx].tab_id

        return True, f"Closed tab '{target.title}'."

    def reopen_last_tab(self) -> Tuple[bool, Optional[str]]:
        """Reopen last closed non-sensitive workspace tab (Ctrl+Shift+T, §4.2)."""
        if not self.closed_tabs_stack:
            return False, "No closed tabs to reopen."

        reopened = self.closed_tabs_stack.pop()
        # Re-add to tabs list
        self.tabs.append(reopened)
        self.active_tab_id = reopened.tab_id
        return True, f"Reopened tab '{reopened.title}'."

    def cycle_tab(self, direction: int = 1) -> None:
        """Cycle active workspace tab forward (+1) or backward (-1) (Ctrl+Tab / Ctrl+Shift+Tab)."""
        if len(self.tabs) <= 1:
            return
        curr_idx = 0
        for i, t in enumerate(self.tabs):
            if t.tab_id == self.active_tab_id:
                curr_idx = i
                break
        next_idx = (curr_idx + direction) % len(self.tabs)
        self.active_tab_id = self.tabs[next_idx].tab_id

    def jump_to_tab_index(self, index: int) -> bool:
        """Jump to visible tab at 1-based index (Alt+1..9)."""
        if 1 <= index <= len(self.tabs):
            self.active_tab_id = self.tabs[index - 1].tab_id
            return True
        return False

    def update_tab_badge(self, tab_id: str, badge: Optional[str]) -> bool:
        """Update tab badge in-place without reordering tabs or stealing focus (§4.2)."""
        t = self.get_tab(tab_id)
        if t:
            t.badge = badge
            return True
        return False
