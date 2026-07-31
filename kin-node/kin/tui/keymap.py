"""Central Keybinding Registry & Validator for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.1, §5.2, §5.3, §14.4
"""

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from textual.binding import Binding


class KeymapCollisionError(ValueError):
    """Raised when two keybindings collide without text-focus/context separation."""

    pass


@dataclass(frozen=True)
class KeyBindingSpec:
    """Dataclass defining a single registered keybinding and its metadata."""

    key: str
    action: str
    label: str
    priority: bool
    suppressed_when_text_focused: bool
    section: Literal["global", "collection", "arena"] = "global"
    consequential: bool = False
    justification: str = ""
    explicit_action: Optional[str] = None

    @property
    def target_action(self) -> str:
        """Exact Textual action string for KinApp binding dispatch without hardcoded exception tuples (§14.4)."""
        if self.explicit_action:
            return self.explicit_action
        if self.action.startswith("action_"):
            return self.action
        return f"action_{self.action}"


# Central authoritative list of all registered keybindings (§5.1 - §5.3, including T1 geometry controls)
DEFAULT_KEYMAP: List[KeyBindingSpec] = [
    # Global Bindings (§5.1)
    KeyBindingSpec(
        key="ctrl+c",
        action="quit",
        label="Quit Application",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global system interrupt signal.",
        explicit_action="quit",
    ),
    KeyBindingSpec(
        key="ctrl+k",
        action="command_palette",
        label="Command Palette",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global system shortcut; Ctrl modifier safely bypasses text fields.",
    ),
    KeyBindingSpec(
        key="ctrl+p",
        action="quick_switcher",
        label="Quick Switcher",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global navigation shortcut; Ctrl modifier safely bypasses text fields.",
    ),
    KeyBindingSpec(
        key="d",
        action="open_dispatch",
        label="Open Dispatch",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable letter 'd'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="a",
        action="open_agents",
        label="Open Agents",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable letter 'a'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="n",
        action="open_network",
        label="Open Network",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable letter 'n'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="i",
        action="open_inbox",
        label="Open Inbox / Toggle Inspector",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable letter 'i'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="p",
        action="open_approvals",
        label="Open Approvals",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable letter 'p'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="question_mark",  # ? in Textual
        action="toggle_help",
        label="Contextual Help",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable symbol '?'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="slash",  # / in Textual
        action="focus_filter",
        label="Filter Collection",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable symbol '/'; must yield to text input fields when focused.",
    ),
    KeyBindingSpec(
        key="escape",
        action="handle_escape",
        label="Clear / Close / Unfocus",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global escape key; priority required to trigger Esc priority chain.",
    ),
    KeyBindingSpec(
        key="tab",
        action="focus_next",
        label="Next Widget",
        priority=False,
        suppressed_when_text_focused=False,
        section="global",
        justification="Standard focus navigation key.",
    ),
    KeyBindingSpec(
        key="shift+tab",
        action="focus_prev",
        label="Previous Widget",
        priority=False,
        suppressed_when_text_focused=False,
        section="global",
        justification="Standard focus navigation key.",
    ),
    KeyBindingSpec(
        key="ctrl+tab",
        action="next_tab",
        label="Next Tab",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global tab cycle shortcut.",
    ),
    KeyBindingSpec(
        key="ctrl+shift+tab",
        action="prev_tab",
        label="Previous Tab",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global tab cycle shortcut.",
    ),
    KeyBindingSpec(
        key="ctrl+w",
        action="close_tab",
        label="Close Tab",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global workspace tab close shortcut.",
    ),
    KeyBindingSpec(
        key="ctrl+shift+t",
        action="reopen_tab",
        label="Reopen Closed Tab",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global tab reopen shortcut.",
    ),
    KeyBindingSpec(
        key="ctrl+s",
        action="save_draft",
        label="Save Local Draft",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Global draft save shortcut.",
    ),
    KeyBindingSpec(
        key="q",
        action="smart_quit",
        label="Smart Quit / Return Home",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable letter 'q'; must yield to text input fields when focused.",
    ),
    # T1 Shell Geometry Controls (§3.3, §5.1)
    KeyBindingSpec(
        key="alt+left_square_bracket",
        action="decrease_sidebar_width",
        label="Decrease Sidebar Width",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Alt+[ modifier shortcut for sidebar resize.",
        explicit_action="decrease_sidebar_width",
    ),
    KeyBindingSpec(
        key="alt+right_square_bracket",
        action="increase_sidebar_width",
        label="Increase Sidebar Width",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Alt+] modifier shortcut for sidebar resize.",
        explicit_action="increase_sidebar_width",
    ),
    KeyBindingSpec(
        key="alt+shift+left_square_bracket",
        action="decrease_inspector_width",
        label="Decrease Inspector Width",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Alt+{ modifier shortcut for inspector resize.",
        explicit_action="decrease_inspector_width",
    ),
    KeyBindingSpec(
        key="alt+shift+right_square_bracket",
        action="increase_inspector_width",
        label="Increase Inspector Width",
        priority=True,
        suppressed_when_text_focused=False,
        section="global",
        justification="Alt+} modifier shortcut for inspector resize.",
        explicit_action="increase_inspector_width",
    ),
    KeyBindingSpec(
        key="left_square_bracket",
        action="toggle_sidebar",
        label="Toggle Sidebar",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable symbol '['; must yield to text input fields when focused.",
        explicit_action="toggle_sidebar",
    ),
    KeyBindingSpec(
        key="right_square_bracket",
        action="toggle_inspector",
        label="Toggle Inspector",
        priority=False,
        suppressed_when_text_focused=True,
        section="global",
        justification="Printable symbol ']'; must yield to text input fields when focused.",
        explicit_action="toggle_inspector",
    ),
    # Alt+1..9 Jump to Tab N
    *[
        KeyBindingSpec(
            key=f"alt+{idx}",
            action=f"jump_tab_{idx}",
            label=f"Jump to Tab {idx}",
            priority=True,
            suppressed_when_text_focused=False,
            section="global",
            justification=f"Alt+{idx} tab jump shortcut.",
        )
        for idx in range(1, 10)
    ],
    # Collection & Timeline Bindings (§5.2)
    KeyBindingSpec(
        key="j",
        action="cursor_down",
        label="Move Selection Down",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Vim-style navigation key; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="k",
        action="cursor_up",
        label="Move Selection Up",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Vim-style navigation key; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="g",
        action="cursor_top",
        label="Move Selection to Top",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Vim-style navigation key; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="G",
        action="cursor_bottom",
        label="Move Selection to Bottom",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Vim-style navigation key; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="enter",
        action="activate_selection",
        label="Activate / Open Selection",
        priority=False,
        suppressed_when_text_focused=False,
        section="collection",
        justification="Standard activation key.",
    ),
    KeyBindingSpec(
        key="space",
        action="preview_selection",
        label="Preview Selection in Inspector",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Printable space character; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="o",
        action="open_in_new_tab",
        label="Open in New Tab",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Printable letter 'o'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="r",
        action="replay_item",
        label="Replay Session",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Printable letter 'r'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="f",
        action="fork_item",
        label="Fork Session",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Printable letter 'f'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="full_stop",  # . in Textual
        action="open_actions",
        label="Item Actions Menu",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        justification="Printable dot '.'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="x",
        action="consequential_action",
        label="Cancel / Archive Action",
        priority=False,
        suppressed_when_text_focused=True,
        section="collection",
        consequential=True,
        justification="Printable letter 'x'; yields to text input fields. Requires confirmation gate.",
    ),
    # Session Arena Bindings (§5.3)
    KeyBindingSpec(
        key="z",
        action="lane_focus",
        label="Focus / Cockpit Mode",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 'z'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="t",
        action="lane_transcript",
        label="Transcript Lane",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 't'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="e",
        action="lane_activity",
        label="Activity Lane",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 'e'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="c",
        action="lane_decisions",
        label="Decisions Lane",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 'c'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="u",
        action="lane_needs_you",
        label="Needs-you Lane",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 'u'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="m",
        action="compose_message",
        label="Compose Message",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 'm'; yields to text input fields.",
    ),
    KeyBindingSpec(
        key="s",
        action="session_state_menu",
        label="Session State Menu",
        priority=False,
        suppressed_when_text_focused=True,
        section="arena",
        justification="Printable letter 's'; yields to text input fields.",
    ),
]


def validate_keymap_registry(bindings: Optional[List[KeyBindingSpec]] = None) -> None:
    """Validate binding registry for collisions at startup/test time (§14.4).

    Enforces a FLAT namespace check across ALL bindings attached to the app.
    Raises KeymapCollisionError if two bindings share the exact same key.
    """
    target_bindings = bindings if bindings is not None else DEFAULT_KEYMAP
    seen: Dict[str, KeyBindingSpec] = {}

    for b in target_bindings:
        if b.key in seen:
            prev = seen[b.key]
            raise KeymapCollisionError(
                f"Keybinding collision detected on key '{b.key}': "
                f"action '{b.action}' in section '{b.section}' collides with action '{prev.action}' in section '{prev.section}'."
            )
        seen[b.key] = b


def build_textual_bindings(bindings: Optional[List[KeyBindingSpec]] = None) -> List[Binding]:
    """Programmatically convert DEFAULT_KEYMAP specs into Textual Binding objects (§14.4).

    Guarantees KinApp.BINDINGS is 100% driven directly by keymap.py definitions.
    """
    target = bindings if bindings is not None else DEFAULT_KEYMAP
    return [
        Binding(
            key=b.key,
            action=b.target_action,
            description=b.label,
            show=False,
            priority=b.priority,
        )
        for b in target
    ]


# Run validation on import to fail fast on startup
validate_keymap_registry(DEFAULT_KEYMAP)
