"""Motion-timing limits and behavioral guarantees for T7 build step 3."""

from datetime import datetime, timedelta, timezone
import inspect

import pytest

from kin.tui.app import KinApp
from kin.tui.guide import GuideOverlayScreen
from kin.tui.help import HelpOverlayScreen
from kin.tui.motion import (
    EVENT_PULSE_DURATION_MS,
    EXPAND_TRANSITION_MS,
    EXPAND_TRANSITION_MS_MAX,
    EXPAND_TRANSITION_MS_MIN,
    FOCUS_TRANSITION_MS_MAX,
    FOCUS_TRANSITION_MS_MIN,
    MODAL_TRANSITION_MS,
    MODAL_TRANSITION_MS_MAX,
    MODAL_ANIMATION_MAX_MS,
    SPINNER_FPS,
    SPINNER_FPS_MAX,
    SPINNER_FPS_MIN,
    SPINNER_FRAME_INTERVAL_SECONDS,
    TOAST_AMBER_PULSE_INTERVAL_MS,
    TOAST_DURATION_SEC,
    TOAST_DURATION_SEC_MAX,
    TOAST_DURATION_SEC_MIN,
    TOAST_MAX_AMBER_PULSES,
)
from kin.tui.palette import CommandPaletteModal, QuickSwitcherModal
from kin.tui.shell import ConfirmationModal, Sidebar
from kin.tui.state import UiEvent
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.approval_modals import (
    ApproveConfirmModal,
    DenyReasonModal,
    EditConstraintsModal,
    PatchApplyConfirmModal,
)
from kin.tui.widgets.compose_modal import ComposeMessageModal
from kin.tui.widgets.dispatch_wizard import ContactPickerModal
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.modal import ModalScreenWidget, ModalWidget
from kin.tui.widgets.session_state_modal import SessionStateMenuModal
from kin.tui.widgets.settings_screen import SettingsModal
from kin.tui.widgets.sidebar_tree import SidebarTreeWidget
from kin.tui.widgets.spinner import SpinnerWidget
from kin.tui.widgets.toast import ToastWidget


class _PausedTimer:
    def __init__(self) -> None:
        self.pause_count = 0

    def pause(self) -> None:
        self.pause_count += 1


def test_central_motion_limits_match_specification() -> None:
    assert (FOCUS_TRANSITION_MS_MIN, FOCUS_TRANSITION_MS_MAX) == (80, 120)
    assert EVENT_PULSE_DURATION_MS == 120
    assert (EXPAND_TRANSITION_MS_MIN, EXPAND_TRANSITION_MS_MAX) == (120, 180)
    assert EXPAND_TRANSITION_MS_MIN <= EXPAND_TRANSITION_MS <= EXPAND_TRANSITION_MS_MAX
    assert MODAL_TRANSITION_MS == 0 <= MODAL_TRANSITION_MS_MAX == 120
    assert MODAL_ANIMATION_MAX_MS == MODAL_TRANSITION_MS_MAX
    assert SPINNER_FPS_MIN <= SPINNER_FPS <= SPINNER_FPS_MAX
    assert (SPINNER_FPS_MIN, SPINNER_FPS_MAX) == (8, 12)
    assert SPINNER_FRAME_INTERVAL_SECONDS == 1.0 / SPINNER_FPS
    assert (TOAST_DURATION_SEC_MIN, TOAST_DURATION_SEC_MAX) == (3, 6)
    assert TOAST_DURATION_SEC_MIN <= TOAST_DURATION_SEC <= TOAST_DURATION_SEC_MAX
    assert TOAST_MAX_AMBER_PULSES == 2


def test_event_pulse_remains_time_based_for_the_full_120_ms_window() -> None:
    event = UiEvent(
        event_id="evt-live-pulse",
        session_id="session-motion",
        kind="message",
        created_at="2026-08-05T12:00:00Z",
        actor_username="agent",
        presentation_class="message",
        content="Live result",
    )
    appended_at = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    timeline = ExchangeTimelineWidget(events=[event])
    timeline.live_appended_at_map[event.event_id] = appended_at
    group = timeline.get_coalesced_groups()[0]

    # Rendering frequency does not consume the pulse; elapsed time alone controls it.
    for _ in range(3):
        rendered = timeline._render_group_card(
            group,
            is_selected=False,
            now_dt=appended_at + timedelta(milliseconds=119),
        )
        assert "[TAIL PULSE]" in rendered

    expired = timeline._render_group_card(
        group,
        is_selected=False,
        now_dt=appended_at + timedelta(milliseconds=120),
    )
    assert "[TAIL PULSE]" not in expired


def test_spinner_uses_10_fps_and_renders_elapsed_time() -> None:
    clock_value = [100.0]
    spinner = SpinnerWidget(
        label="Loading data",
        now=datetime(2026, 8, 5, 8, 45, tzinfo=timezone.utc),
        elapsed_clock=lambda: clock_value[0],
    )
    clock_value[0] = 165.0

    assert spinner.fps == 10
    assert spinner.frame_interval_seconds == 0.1
    rendered = spinner.render()
    assert "started 08:45:00" in rendered
    assert "elapsed 01:05" in rendered


def test_toast_duration_is_clamped_to_three_through_six_seconds() -> None:
    assert ToastWidget(duration_ms=100).duration_seconds == TOAST_DURATION_SEC_MIN
    assert ToastWidget(duration_ms=4500).duration_seconds == 4.5
    assert ToastWidget(duration_ms=99_000).duration_seconds == TOAST_DURATION_SEC_MAX


def test_warning_toast_never_exceeds_two_amber_pulses() -> None:
    toast = ToastWidget(message="Approval needed", severity="warning")
    timer = _PausedTimer()
    toast._amber_pulse_timer = timer
    toast.amber_pulse_count = 1
    toast._amber_pulse_active = True
    toast.refresh = lambda **kwargs: None

    toast._advance_amber_pulse()  # first pulse off
    toast._advance_amber_pulse()  # second pulse on
    toast._advance_amber_pulse()  # second pulse off and timer paused
    toast._advance_amber_pulse()  # defensive re-entry remains capped

    assert toast.amber_pulse_count == TOAST_MAX_AMBER_PULSES
    assert timer.pause_count >= 1


def test_all_modal_screen_classes_are_instant_and_have_no_css_transition() -> None:
    modal_classes = (
        ModalScreenWidget,
        ConfirmationModal,
        ApproveConfirmModal,
        DenyReasonModal,
        EditConstraintsModal,
        PatchApplyConfirmModal,
        ComposeMessageModal,
        SessionStateMenuModal,
        GuideOverlayScreen,
        HelpOverlayScreen,
        CommandPaletteModal,
        QuickSwitcherModal,
        AgentPickerWidget,
        ContactPickerModal,
        SettingsModal,
    )
    assert MODAL_TRANSITION_MS == 0
    for modal_class in modal_classes:
        assert "transition:" not in getattr(modal_class, "DEFAULT_CSS", "")
        assert ".animate(" not in inspect.getsource(modal_class)

    widget = ModalWidget()
    assert widget.transition_duration_ms == 0
    assert widget.max_animation_ms == MODAL_TRANSITION_MS_MAX


@pytest.mark.asyncio
async def test_expand_collapse_paths_schedule_150_ms_local_transitions(
    tmp_path, monkeypatch
) -> None:
    app = KinApp(profile_name="motion-expand", profile_dir=tmp_path)
    async with app.run_test(size=(120, 36)):
        sidebar = app.sidebar
        delays = []
        callbacks = []
        refresh_kwargs = []
        app_refreshes = 0

        def capture_timer(delay, callback, *args, **kwargs):
            delays.append(delay)
            callbacks.append(callback)
            return _PausedTimer()

        def capture_sidebar_refresh(*args, **kwargs):
            refresh_kwargs.append(kwargs)

        def capture_app_refresh(*args, **kwargs):
            nonlocal app_refreshes
            app_refreshes += 1

        monkeypatch.setattr(sidebar, "set_timer", capture_timer)
        monkeypatch.setattr(sidebar, "refresh", capture_sidebar_refresh)
        monkeypatch.setattr(app, "refresh", capture_app_refresh)

        sidebar.toggle_section_collapse("SPACES")
        assert delays == [EXPAND_TRANSITION_MS / 1000.0]
        assert sidebar._transitioning_section == "SPACES"
        callbacks[0]()
        assert sidebar._transitioning_section is None
        assert refresh_kwargs == [{"layout": False}, {"layout": False}]
        assert app_refreshes == 0

        foundation_tree = SidebarTreeWidget()
        await app.mount(foundation_tree)
        foundation_delays = []
        foundation_callbacks = []

        def capture_foundation_timer(delay, callback, *args, **kwargs):
            foundation_delays.append(delay)
            foundation_callbacks.append(callback)
            return _PausedTimer()

        monkeypatch.setattr(foundation_tree, "set_timer", capture_foundation_timer)
        foundation_tree.toggle_collapse()
        assert foundation_delays == [EXPAND_TRANSITION_MS / 1000.0]
        assert foundation_tree._transitioning_section == "workspaces"
        foundation_callbacks[0]()
        assert foundation_tree._transitioning_section is None

        style_animations = []

        def capture_style_animation(styles, attribute, value, *, duration, **kwargs):
            style_animations.append((attribute, value, duration))

        monkeypatch.setattr(type(sidebar.styles), "animate", capture_style_animation)
        sidebar.set_collapsed(True, with_transition=True)
        assert style_animations == [("width", 4, EXPAND_TRANSITION_MS / 1000.0)]

        assert foundation_tree.expand_transition_duration_ms == EXPAND_TRANSITION_MS
        assert sidebar.expand_transition_duration_ms == EXPAND_TRANSITION_MS


@pytest.mark.asyncio
async def test_keystrokes_win_while_spinner_and_toast_timers_are_active(
    tmp_path,
) -> None:
    app = KinApp(profile_name="motion-keys", profile_dir=tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        spinner = SpinnerWidget(label="Working")
        toast = ToastWidget(message="Check policy", severity="warning")
        await app.mount(spinner, toast)
        await pilot.pause()

        assert spinner._frame_timer is not None
        assert toast._dismiss_timer is not None
        assert toast._amber_pulse_timer is not None

        app.set_focus(None)
        await pilot.press("d")
        assert app.canvas.active_tab_kind == "dispatch"


@pytest.mark.asyncio
async def test_ordinary_timer_updates_refresh_only_the_owning_widgets(
    tmp_path, monkeypatch
) -> None:
    app = KinApp(profile_name="motion-reflow", profile_dir=tmp_path)
    async with app.run_test(size=(120, 36)):
        spinner = SpinnerWidget(label="Working")
        toast = ToastWidget(message="Check policy", severity="warning")
        await app.mount(spinner, toast)

        app_refreshes = 0
        spinner_refreshes = []
        toast_refreshes = []

        def capture_app_refresh(*args, **kwargs):
            nonlocal app_refreshes
            app_refreshes += 1

        monkeypatch.setattr(app, "refresh", capture_app_refresh)
        monkeypatch.setattr(
            spinner, "refresh", lambda *args, **kwargs: spinner_refreshes.append(kwargs)
        )
        monkeypatch.setattr(
            toast, "refresh", lambda *args, **kwargs: toast_refreshes.append(kwargs)
        )

        spinner.advance_frame()
        toast._advance_amber_pulse()

        assert spinner_refreshes == [{"layout": False}]
        assert toast_refreshes == [{"layout": False}]
        assert app_refreshes == 0


@pytest.mark.asyncio
async def test_toast_without_callback_hides_without_layout_reflow_when_timer_fires(tmp_path) -> None:
    app = KinApp(profile_name="motion-toast", profile_dir=tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        toast = ToastWidget(message="Saved", duration_ms=3000)
        await app.mount(toast)
        assert toast.is_mounted

        assert toast.trigger_dismiss() is True
        assert toast.styles.visibility == "hidden"
        assert toast.is_mounted


def test_toast_amber_pulse_interval_reuses_central_120_ms_token() -> None:
    assert TOAST_AMBER_PULSE_INTERVAL_MS == EVENT_PULSE_DURATION_MS == 120


def test_sidebar_instance_uses_central_expand_duration() -> None:
    assert Sidebar().expand_transition_duration_ms == EXPAND_TRANSITION_MS
