"""M8 four-breakpoint reference snapshots for every primary workflow surface."""

from datetime import datetime, timezone

import pytest
from textual.app import App, ComposeResult

from kin.schemas import AgentAvailability
from kin.tui.first_flight import FirstFlightController
from kin.tui.fixtures import (
    make_agent_card_view_fixture,
    make_approval_view_fixture,
    make_session_summary_fixture,
)
from kin.tui.persistence import UiStatePreferences
from kin.tui.state import HealthSnapshot, NeedsYouItem, PrivateNoteView
from kin.tui.tokens import resolve_theme
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.agents_screen import AgentsScreenWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.dispatch_wizard import DispatchWizardWidget
from kin.tui.widgets.first_flight_wizard import FirstFlightWizardWidget
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.inbox_screen import InboxScreenWidget
from kin.tui.widgets.network_screen import NetworkScreenWidget
from kin.tui.widgets.session_arena import SessionArenaWidget


BREAKPOINTS = [(160, 44), (120, 36), (90, 28), (80, 24)]
SURFACES = ["first_flight", "home", "agents", "network", "dispatch", "picker", "inbox", "approval", "notes"]
OVERLAYS = ["settings", "toast", "spinner", "guide", "help", "palette"]


class PrimarySurfaceSnapshotApp(App):
    def __init__(self, widget, theme_name="kin-graphite", ascii_fallback=False, **kwargs):
        super().__init__(**kwargs)
        self.snapshot_widget = widget
        self.theme_tokens = resolve_theme(theme_name).theme
        self.is_ascii_fallback_active = ascii_fallback
        self.is_colorless_active = ascii_fallback

    def compose(self) -> ComposeResult:
        yield self.snapshot_widget


def _surface(name, tmp_path):
    ready = make_agent_card_view_fixture(AgentAvailability.READY)
    approval = make_approval_view_fixture(now="2026-07-26T12:00:00Z")
    if name == "first_flight":
        controller = FirstFlightController("snapshot-owner", tmp_path / "first-flight")
        return FirstFlightWizardWidget(controller, UiStatePreferences())
    if name == "home":
        return HomeScreenWidget(
            profile_dir=tmp_path,
            agents=[ready],
            sessions=[make_session_summary_fixture("active")],
            approvals=[approval],
            health=HealthSnapshot(
                keychain_ok=True,
                identity_ok=True,
                relay_reachable=False,
                node_reachable=True,
                pending_inbox_count=1,
            ),
        )
    if name == "agents":
        return AgentsScreenWidget(profile_dir=tmp_path, local_agents=[ready], peer_agents=[], contacts=[])
    if name == "network":
        return NetworkScreenWidget(profile_dir=tmp_path, contacts=[])
    if name == "dispatch":
        return DispatchWizardWidget(profile_dir=tmp_path, profile_name="snapshot-owner")
    if name == "picker":
        return AgentPickerWidget(agents=[ready], prompt="Select the local agent for this collaboration")
    if name == "inbox":
        return InboxScreenWidget(
            profile_dir=tmp_path,
            needs_you_items=[
                NeedsYouItem(
                    item_id="needs-1",
                    session_id="sess-test-001",
                    kind="clarification",
                    human_readable_reason="Bob needs a bounded clarification",
                    urgency="medium",
                    created_at="2026-07-26T12:00:00Z",
                )
            ],
            approvals=[approval],
            now="2026-07-26T12:00:00Z",
        )
    if name == "notes":
        arena = SessionArenaWidget(
            session_summary=make_session_summary_fixture("active"),
            events=[],
            artifacts=[],
            approvals=[],
            profile_dir=tmp_path,
        )
        arena.private_notes = [
            PrivateNoteView(
                event_id="note-owner-1",
                session_id="sess-test-001",
                actor_username="alice",
                note_text="Compare the final evidence before deliberate promotion.",
                created_at="2026-07-26T12:10:00Z",
                event_order=1,
            )
        ]
        arena.active_lane = "notes"
        return arena
    return ApprovalCardWidget(approval, now="2026-07-26T12:00:00Z")


@pytest.mark.parametrize("terminal_size", BREAKPOINTS, ids=lambda size: f"{size[0]}x{size[1]}")
@pytest.mark.parametrize("surface", SURFACES)
def test_primary_surface_four_breakpoint_reference(
    surface,
    terminal_size,
    tmp_path,
    snap_compare,
    build_tui_app,
):
    app = build_tui_app(PrimarySurfaceSnapshotApp, widget=_surface(surface, tmp_path))
    assert snap_compare(app, terminal_size=terminal_size)


@pytest.mark.parametrize("mode", ["default", "high_contrast", "ascii"])
@pytest.mark.parametrize("surface", SURFACES)
def test_primary_surface_default_high_contrast_ascii_reference(
    surface,
    mode,
    tmp_path,
    snap_compare,
    build_tui_app,
):
    app = build_tui_app(
        PrimarySurfaceSnapshotApp,
        widget=_surface(surface, tmp_path),
        theme_name="high-contrast" if mode == "high_contrast" else "kin-graphite",
        ascii_fallback=mode == "ascii",
    )
    app.is_ascii_fallback_active = mode == "ascii"
    app.is_colorless_active = mode == "ascii"
    assert snap_compare(app, terminal_size=(120, 36))


@pytest.mark.parametrize("terminal_size", BREAKPOINTS, ids=lambda size: f"{size[0]}x{size[1]}")
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_production_overlay_four_breakpoint_reference(
    overlay,
    terminal_size,
    snap_compare,
    build_tui_app,
):
    app = build_tui_app(profile_name=f"snapshot-{overlay}")

    async def open_overlay(pilot):
        if overlay == "settings":
            pilot.app.action_open_settings()
        elif overlay == "toast":
            pilot.app.show_toast("Peer session queued safely at relay", severity="warning", duration_ms=10_000)
        elif overlay == "spinner":
            pilot.app.activity_spinner.update_clock("2026-08-05T12:00:00+00:00")
            pilot.app.activity_spinner.set_reduced_motion(True)
            pilot.app.start_activity("Signing and encrypting reviewed dispatch")
        elif overlay == "guide":
            pilot.app.action_open_guide()
        elif overlay == "help":
            pilot.app.action_help()
        else:
            pilot.app.action_command_palette()
        await pilot.pause()

    assert snap_compare(app, terminal_size=terminal_size, run_before=open_overlay)
