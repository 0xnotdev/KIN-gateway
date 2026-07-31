"""Command Palette, Quick Switcher, and Colon Command Security Parser for KIN V1.1 TUI.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.1, §5.4, §14.4
"""

from dataclasses import dataclass, field
import re
from typing import Callable, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


@dataclass
class CommandItem:
    """Command item entry in the Command Palette index."""

    command_id: str
    title: str
    category: str = "General"
    shortcut: str = ""
    recent: bool = False
    contextual: bool = False
    consequential: bool = False
    handler_name: str = ""


def rank_command_palette(query: str, items: List[CommandItem]) -> List[CommandItem]:
    """Rank command palette items using strict 4-tier ranking algorithm (§5.4, §14.4).

    Ranking Priority:
      Tier 1: Exact command match (title or command_id equals query exactly, case-insensitive)
      Tier 2: Recent action match (query substring in title/id AND recent is True)
      Tier 3: Contextual relevance match (query substring in title/id AND contextual is True)
      Tier 4: Fuzzy / Substring match (query substring in title/id)
    """
    clean_q = query.strip().lower()
    if not clean_q:
        # Default order: recent first, then contextual, then general
        return sorted(items, key=lambda x: (not x.recent, not x.contextual, x.title))

    tier1: List[CommandItem] = []
    tier2: List[CommandItem] = []
    tier3: List[CommandItem] = []
    tier4: List[CommandItem] = []

    for item in items:
        t_low = item.title.lower()
        id_low = item.command_id.lower()

        # Exact match check
        if clean_q == t_low or clean_q == id_low:
            tier1.append(item)
        elif clean_q in t_low or clean_q in id_low:
            if item.recent:
                tier2.append(item)
            elif item.contextual:
                tier3.append(item)
            else:
                tier4.append(item)

    return tier1 + tier2 + tier3 + tier4


# Whitelist of allowed colon commands (§5.4)
ALLOWED_COLON_COMMANDS = {"theme", "open", "quit", "help", "clear", "guide"}
SHELL_INJECTION_PATTERN = re.compile(r"[:\s]!|exec\(|eval\(|import\s|system\(|passthru\(|popen\(", re.IGNORECASE)


def parse_colon_command(raw_input: str) -> Tuple[bool, Optional[str], Optional[str], str]:
    """Parse and validate colon-commands (e.g. ':theme kin-graphite') (§5.4, §14.4).

    Returns:
      (is_valid, cmd_name, arg_str, feedback_message)

    Strictly rejects shell-like commands or unrecognized verbs.
    """
    clean = raw_input.strip()
    if not clean.startswith(":"):
        return False, None, None, "Not a colon command."

    # Check for shell execution attempt
    if SHELL_INJECTION_PATTERN.search(clean) or "!" in clean:
        return False, None, None, "Security Error: Arbitrary shell execution is strictly prohibited."

    parts = clean[1:].strip().split(maxsplit=1)
    if not parts:
        return False, None, None, "Empty colon command."

    cmd_name = parts[0].lower()
    arg_str = parts[1].strip() if len(parts) > 1 else ""

    if cmd_name not in ALLOWED_COLON_COMMANDS:
        return (
            False,
            None,
            None,
            f"Security Error: Unrecognized colon command ':{cmd_name}'. Allowed: {', '.join(sorted(ALLOWED_COLON_COMMANDS))}.",
        )

    return True, cmd_name, arg_str, f"Parsed colon command :{cmd_name}"


class CommandPaletteModal(ModalScreen[Optional[CommandItem]]):
    """Command Palette Modal Overlay (Ctrl+K) per §5.4."""

    DEFAULT_CSS = """
    CommandPaletteModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    #palette-container {
        width: 70;
        height: 20;
        background: $surface-darken-1;
        border: thick $primary;
        padding: 1;
    }
    #palette-input {
        dock: top;
        margin-bottom: 1;
    }
    #palette-options {
        height: 1fr;
    }
    """

    def __init__(self, items: List[CommandItem], **kwargs) -> None:
        super().__init__(**kwargs)
        self.all_items = items
        self.current_ranked = items

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-container"):
            yield Static("[bold cyan]Command Palette (Ctrl+K)[/bold cyan]", id="palette-title")
            yield Input(placeholder="Type a command or :colon command...", id="palette-input")
            yield OptionList(id="palette-options")

    def on_mount(self) -> None:
        self.update_options("")
        self.query_one("#palette-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        val = event.value
        if val.startswith(":"):
            # Colon command feedback mode
            is_valid, cmd_name, arg_str, msg = parse_colon_command(val)
            opt_list = self.query_one("#palette-options", OptionList)
            opt_list.clear_options()
            opt_list.add_option(Option(f"[yellow]{msg}[/yellow]", id="colon_feedback"))
        else:
            self.update_options(val)

    def update_options(self, query: str) -> None:
        ranked = rank_command_palette(query, self.all_items)
        self.current_ranked = ranked
        opt_list = self.query_one("#palette-options", OptionList)
        opt_list.clear_options()
        for idx, item in enumerate(ranked):
            sec = f" [{item.category}]" if item.category else ""
            sc = f" ({item.shortcut})" if item.shortcut else ""
            label = f"{item.title}{sec}{sc}"
            opt_list.add_option(Option(label, id=f"opt_{idx}"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if val.startswith(":"):
            is_valid, cmd_name, arg_str, msg = parse_colon_command(val)
            if is_valid:
                # Return dummy command item for colon command execution
                cmd_item = CommandItem(
                    command_id=f"colon:{cmd_name}",
                    title=f":{cmd_name} {arg_str}".strip(),
                    category="ColonCommand",
                )
                self.dismiss(cmd_item)
            else:
                self.notify(msg, severity="error")
        else:
            opt_list = self.query_one("#palette-options", OptionList)
            sel_idx = opt_list.highlighted
            if sel_idx is not None and 0 <= sel_idx < len(self.current_ranked):
                self.dismiss(self.current_ranked[sel_idx])
            else:
                self.dismiss(None)


class QuickSwitcherModal(ModalScreen[Optional[str]]):
    """Quick Switcher Modal Overlay (Ctrl+P) per §5.1, §5.4."""

    DEFAULT_CSS = """
    QuickSwitcherModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    #switcher-container {
        width: 64;
        height: 18;
        background: $surface-darken-1;
        border: thick $accent;
        padding: 1;
    }
    #switcher-input {
        dock: top;
        margin-bottom: 1;
    }
    """

    def __init__(self, items: List[Tuple[str, str, str]], **kwargs) -> None:
        super().__init__(**kwargs)
        # items: List of (id, title, category)
        self.all_items = items
        self.filtered_items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="switcher-container"):
            yield Static("[bold green]Quick Switcher (Ctrl+P)[/bold green]", id="switcher-title")
            yield Input(placeholder="Switch open workspace, session, agent...", id="switcher-input")
            yield OptionList(id="switcher-options")

    def on_mount(self) -> None:
        self.update_options("")
        self.query_one("#switcher-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_options(event.value)

    def update_options(self, query: str) -> None:
        clean_q = query.strip().lower()
        if not clean_q:
            self.filtered_items = self.all_items
        else:
            self.filtered_items = [
                item for item in self.all_items if clean_q in item[1].lower() or clean_q in item[0].lower()
            ]

        opt_list = self.query_one("#switcher-options", OptionList)
        opt_list.clear_options()
        for idx, (item_id, title, category) in enumerate(self.filtered_items):
            opt_list.add_option(Option(f"{title} [dim]({category})[/dim]", id=f"sw_{idx}"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self.query_one("#switcher-options", OptionList)
        sel_idx = opt_list.highlighted
        if sel_idx is not None and 0 <= sel_idx < len(self.filtered_items):
            self.dismiss(self.filtered_items[sel_idx][0])
        else:
            self.dismiss(None)
