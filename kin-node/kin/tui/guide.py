"""Authorable kin guide interactive screen and markdown renderer (§14.6 Phase D3, §5.9).

Provides six spec-mandated short-form documentation pages, interactive search,
and deterministic markdown output parity.
"""

from typing import List, NamedTuple

from rich.console import RenderableType
from rich.panel import Panel
from rich.table import Table
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


class GuidePage(NamedTuple):
    title: str
    body: str
    next_action: str


# Authoritative six named guide pages per §5.9 / §14.6 Phase D
GUIDE_PAGES: List[GuidePage] = [
    GuidePage(
        title="Start here",
        body="KIN is your personal, local-first agent network. Create an identity, pair trusted contacts, and dispatch work across autonomous agents.",
        next_action="Press `h` to view the Home dashboard or run `kin first-flight`.",
    ),
    GuidePage(
        title="Meet your agents",
        body="Agents perform local and remote tasks governed by strict capability boundaries. Inspect cards, manage availability, and connect new YAML agent definitions.",
        next_action="Press `a` to open the Agents workspace.",
    ),
    GuidePage(
        title="Send good work",
        body="Dispatch structured goals to local or peer agents. Define clear expectations, attach context, and track live session execution.",
        next_action="Press `d` to launch the Dispatch modal.",
    ),
    GuidePage(
        title="Watch and steer",
        body="Monitor active sessions in real time. Review intermediate artifacts, inspect audit logs, and pause or resume execution as needed.",
        next_action="Press `i` to open the Inbox / Needs You queue.",
    ),
    GuidePage(
        title="Work safely",
        body="Security is enforced via cryptographic identities and policy gates. High-risk actions require your explicit owner approval before execution.",
        next_action="Press `n` to review trusted contacts in Network.",
    ),
    GuidePage(
        title="Fix a problem",
        body="If an error occurs, KIN surfaces clear recoverable guidance. Check relay reachability, verify keychain storage, or inspect error details.",
        next_action="Press `?` to open the contextual Help Overlay.",
    ),
]


def render_guide_markdown() -> str:
    """Render GUIDE_PAGES as deterministic plain Markdown for non-TTY / --plain output."""
    lines: List[str] = ["# KIN Terminal UI Guide\n"]
    for page in GUIDE_PAGES:
        lines.append(f"## {page.title}\n")
        lines.append(f"{page.body}\n")
        lines.append(f"**Next Action:** {page.next_action}\n")
    return "\n".join(lines)


class GuideOverlayScreen(LifecycleWidgetMixin, ModalScreen[None]):
    """Interactive modal screen displaying searchable kin guide pages (§5.9)."""

    DEFAULT_CSS = """
    GuideOverlayScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #guide-container {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close Guide"),
        ("q", "dismiss", "Close Guide"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.search_query: str = ""

    def compose(self) -> ComposeResult:
        accent = self._c("accent.primary", "#bb9af7")
        with Container(id="guide-container"):
            yield Static(f"[bold {accent}]KIN USER GUIDE — SEARCHABLE OVERLAY[/bold {accent}]", id="guide-header")
            yield Input(placeholder="Search guide pages...", id="guide-search-input")
            yield Static(self.render_pages(), id="guide-content")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "guide-search-input":
            self.search_query = event.value
            content_widget = self.query_one("#guide-content", Static)
            content_widget.update(self.render_pages())

    def render_pages(self) -> RenderableType:
        query_val = getattr(self, "search_query", "")
        q = query_val.lower()
        filtered = [
            p for p in GUIDE_PAGES
            if not q or q in p.title.lower() or q in p.body.lower()
        ]

        if not filtered:
            return Panel(f"[dim]No guide pages matching '{query_val}'.[/dim]", title="Guide")

        table = Table.grid(expand=True)
        table.add_column()

        warn = self._c("state.waiting", "#e0af68")
        ok = self._c("state.live", "#73daca")
        for p in filtered:
            panel = Panel(
                f"{p.body}\n\n[bold {warn}]Next Action:[/bold {warn}] {p.next_action}",
                title=f"[bold {ok}]{p.title}[/bold {ok}]",
                border_style="cyan",
            )
            table.add_row(panel)

        return table
