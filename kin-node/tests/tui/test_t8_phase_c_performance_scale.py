"""T8 Phase C performance and scale release gates."""

from __future__ import annotations

import asyncio
import gc
from pathlib import Path
import time
import tracemalloc
from typing import Any

import keyring
import pytest
from textual.app import App, ComposeResult

from kin.audit.writer import append_session_event
from kin.identity.storage import get_private_key_service, get_vault_key_service
from kin.tui.local_state import ensure_profile_db, get_session_events
from kin.tui.widgets.dispatch_wizard import DispatchWizardWidget
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.session_arena import SessionArenaWidget


pytestmark = pytest.mark.smoke

PROFILE_NAME = "phase_c_scale"
HOT_SESSION_ID = "sess-scale-hot"
VAULT_KEY = b"phase-c-scale-vault-key-32-byte!"
BASE_EVENT_COUNT = 10_000
TOTAL_PROFILE_EVENT_COUNT = 10_100


def _install_profile_keys() -> None:
    keyring.set_password(get_vault_key_service(PROFILE_NAME), "vault_key", VAULT_KEY.hex())
    keyring.set_password(get_private_key_service(PROFILE_NAME), "private_key", (b"p" * 32).hex())


def _agent_card_yaml(index: int) -> str:
    return "\n".join(
        (
            'schema_version: "1.1"',
            f"id: scale_agent_{index}",
            f"name: Scale Agent {index}",
            "description: Deterministic Phase C scale agent",
            "adapter:",
            "  type: embedded",
            "  provider: scale",
            "  model: deterministic",
            "capabilities:",
            "  tags: [performance]",
            "  accepts: [text/plain]",
            "  produces: [text/plain]",
            "boundaries:",
            "  network_access: deny",
            "  filesystem: none",
            "  shell: deny",
            "  max_runtime_seconds: 60",
            "  max_artifact_bytes: 1000000",
            "autonomy:",
            "  relay_information: always_ask",
            "  propose_actions: always_ask",
            "  execute_local_actions: always_ask",
            "",
        )
    )


@pytest.fixture(scope="module")
def phase_c_scale_profile(tmp_path_factory) -> dict[str, Any]:
    """Build one reusable profile whose events all use append_session_event()."""
    profile_dir = tmp_path_factory.mktemp("t8_phase_c") / PROFILE_NAME
    profile_dir.mkdir(parents=True, exist_ok=True)
    agents_dir = profile_dir / "agents"
    agents_dir.mkdir()
    for index in range(20):
        (agents_dir / f"scale_agent_{index}.yaml").write_text(
            _agent_card_yaml(index),
            encoding="utf-8",
        )

    conn = ensure_profile_db(profile_dir / "kin.db")
    now = "2026-08-05T06:00:00Z"
    conn.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
        ("alice", "11" * 32, "phase-c-test-key", "1.1"),
    )
    session_rows = []
    for index in range(100):
        session_id = HOT_SESSION_ID if index == 0 else f"sess-scale-{index:03d}"
        session_rows.append(
            (
                session_id,
                "ask" if index % 3 == 0 else ("research" if index % 3 == 1 else "build_pipeline"),
                "alice",
                "bob",
                "active",
                f"Phase C scale objective {index}",
                f"scale_agent_{index % 20}",
                "bob_agent",
                12,
                now,
                now,
            )
        )
    conn.executemany(
        """
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        session_rows,
    )
    conn.commit()

    kinds = (
        "task_request",
        "acceptance",
        "question",
        "answer",
        "finding",
        "artifact_offer",
        "approval_request",
        "status_event",
        "participant_changed",
        "activity",
    )
    actor_sequences = {"alice": 0, "bob": 0}
    seed_started = time.perf_counter()
    for index in range(BASE_EVENT_COUNT):
        actor = "alice" if index % 2 == 0 else "bob"
        actor_sequences[actor] += 1
        result = append_session_event(
            conn,
            VAULT_KEY,
            session_id=HOT_SESSION_ID,
            actor_username=actor,
            actor_agent_id="scale_agent_0" if actor == "alice" else "bob_agent",
            kind=kinds[index % len(kinds)],
            payload={
                "content": f"production event {index}",
                "provenance": f"{actor}:scale:{index}",
            },
            sequence=actor_sequences[actor],
        )
        assert result["status"] == "appended"

    for session_index in range(1, 11):
        session_id = f"sess-scale-{session_index:03d}"
        for event_index in range(10):
            result = append_session_event(
                conn,
                VAULT_KEY,
                session_id=session_id,
                actor_username="alice" if event_index % 2 == 0 else "bob",
                actor_agent_id=f"scale_agent_{session_index % 20}",
                kind="status_event" if event_index % 2 == 0 else "finding",
                payload={"content": f"session {session_index} event {event_index}"},
                sequence=(event_index // 2) + 1,
            )
            assert result["status"] == "appended"
    seed_seconds = time.perf_counter() - seed_started
    stored_count = conn.execute("SELECT COUNT(*) FROM session_events").fetchone()[0]
    conn.close()
    assert stored_count == TOTAL_PROFILE_EVENT_COUNT

    startup_profile_dir = profile_dir.parent / "startup_profile"
    startup_profile_dir.mkdir()
    startup_agents_dir = startup_profile_dir / "agents"
    startup_agents_dir.mkdir()
    for index in range(20):
        (startup_agents_dir / f"scale_agent_{index}.yaml").write_text(
            _agent_card_yaml(index),
            encoding="utf-8",
        )
    startup_conn = ensure_profile_db(startup_profile_dir / "kin.db")
    startup_conn.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
        ("alice", "11" * 32, "phase-c-test-key", "1.1"),
    )
    startup_conn.executemany(
        """
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, sender_agent_id, receiver_agent_id, turn_limit, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        session_rows,
    )
    startup_conn.commit()
    startup_conn.close()
    return {
        "profile_dir": profile_dir,
        "startup_profile_dir": startup_profile_dir,
        "seed_seconds": seed_seconds,
        "stored_count": stored_count,
    }


def test_production_seeded_10k_retention_cursor_and_timeline_window(
    phase_c_scale_profile,
) -> None:
    """10k events retain order/provenance and use bounded fetch/render windows."""
    _install_profile_keys()
    profile_dir = phase_c_scale_profile["profile_dir"]

    fetch_started = time.perf_counter()
    events = get_session_events(profile_dir, HOT_SESSION_ID, PROFILE_NAME)
    initial_fetch_seconds = time.perf_counter() - fetch_started
    assert len(events) == BASE_EVENT_COUNT
    assert [event.event_order for event in events] == list(range(BASE_EVENT_COUNT))
    assert events[0].actor_username == "alice"
    assert events[-1].actor_username == "bob"
    assert events[0].content == "production event 0"
    assert events[-1].content == f"production event {BASE_EVENT_COUNT - 1}"
    assert initial_fetch_seconds < 2.0

    render_started = time.perf_counter()
    timeline = ExchangeTimelineWidget(
        events=events,
        allowed_presentation_classes=ExchangeTimelineWidget.ALL_7_CLASSES,
        visible_group_window=100,
    )
    first_render = timeline.render()
    initial_render_seconds = time.perf_counter() - render_started
    groups = timeline.get_coalesced_groups()
    assert len(groups) == BASE_EVENT_COUNT
    assert timeline.get_visible_group_bounds() == (0, 100)
    assert "9900 later cards retained" in first_render
    assert initial_render_seconds < 0.1

    timeline.jump_to_tail()
    tail_start, tail_end = timeline.get_visible_group_bounds()
    assert tail_end == BASE_EVENT_COUNT
    assert tail_end - tail_start == 100
    assert timeline.get_selected_event().event_id == events[-1].event_id
    timeline.selected_index = 5_000
    middle_start, middle_end = timeline.get_visible_group_bounds()
    middle_orders = [
        groups[index].last_event.event_order for index in range(middle_start, middle_end)
    ]
    assert middle_orders == sorted(middle_orders)
    assert groups[timeline.selected_index].last_event.actor_username == events[5_000].actor_username

    seen_ids = {event.event_id for event in events}
    max_order = events[-1].event_order
    max_created = max(event.created_at for event in events)
    conn = ensure_profile_db(profile_dir / "kin.db")
    for index in range(35):
        result = append_session_event(
            conn,
            VAULT_KEY,
            session_id=HOT_SESSION_ID,
            actor_username="bob",
            actor_agent_id="bob_agent",
            kind="finding",
            payload={"content": f"incremental production event {index}"},
            sequence=5_001 + index,
        )
        assert result["status"] == "appended"
    conn.close()

    incremental_started = time.perf_counter()
    incremental = get_session_events(
        profile_dir,
        HOT_SESSION_ID,
        PROFILE_NAME,
        seen_event_ids=seen_ids,
        after_event_order=max_order,
        after_created_at=max_created,
    )
    incremental_seconds = time.perf_counter() - incremental_started
    assert len(incremental) == 35
    assert [event.event_order for event in incremental] == list(
        range(BASE_EVENT_COUNT, BASE_EVENT_COUNT + 35)
    )
    assert all(event.actor_username == "bob" for event in incremental)
    assert incremental_seconds < 0.1

    print(
        "PHASE C 10K: "
        f"profile_events={phase_c_scale_profile['stored_count']}, "
        f"append_seed_seconds={phase_c_scale_profile['seed_seconds']:.3f}, "
        f"initial_fetch_seconds={initial_fetch_seconds:.3f}, "
        f"timeline_render_seconds={initial_render_seconds:.3f}, "
        f"visible_groups=100/{len(groups)}, incremental_rows={len(incremental)}, "
        f"incremental_seconds={incremental_seconds:.4f}"
    )


@pytest.mark.asyncio
async def test_dashboard_interactive_under_two_seconds_three_runs(
    phase_c_scale_profile,
    build_tui_app,
    monkeypatch,
) -> None:
    """KinApp accepts Home input under two seconds with 100 sessions/20 agents."""
    profile_dir = phase_c_scale_profile["startup_profile_dir"]
    monkeypatch.setenv("KIN_RELAY_URL", "http://127.0.0.1:9")
    durations: list[float] = []

    for _ in range(3):
        _install_profile_keys()
        started = time.perf_counter()
        app = build_tui_app(profile_name=PROFILE_NAME, profile_dir=profile_dir)
        async with app.run_test(size=(120, 36)) as pilot:
            home = app.canvas.query_one(HomeScreenWidget)
            home.focus()
            await pilot.pause()
            assert home.has_focus is True
            assert len(home.sessions) == 100
            assert len(home.get_agents()) == 20
            durations.append(time.perf_counter() - started)

    assert all(duration < 2.0 for duration in durations), durations
    print(
        "PHASE C STARTUP: "
        f"runs_seconds={[round(duration, 4) for duration in durations]}, "
        f"max_seconds={max(durations):.4f}, sessions=100, agents=20"
    )


@pytest.mark.asyncio
async def test_31_eps_burst_preserves_dispatch_input_order_and_focus(
    tmp_path,
    build_tui_app,
) -> None:
    """A live Arena poll at 31+ events/sec cannot steal or corrupt Dispatch input."""
    profile_dir = tmp_path / PROFILE_NAME
    profile_dir.mkdir()
    conn = ensure_profile_db(profile_dir / "kin.db")
    now = "2026-08-05T06:00:00Z"
    conn.execute(
        """
        INSERT INTO sessions (
            session_id, type, initiator_username, receiver_username, status,
            objective, turn_limit, created_at, updated_at
        ) VALUES (?, 'ask', 'alice', 'bob', 'active', 'Burst focus proof', 12, ?, ?)
        """,
        ("sess-burst-focus", now, now),
    )
    conn.commit()
    conn.close()
    _install_profile_keys()

    class ConcurrentBurstApp(App):
        def __init__(self, **kwargs):
            super().__init__()
            self.arena = SessionArenaWidget(
                session_id="sess-burst-focus",
                profile_name=PROFILE_NAME,
                profile_dir=profile_dir,
            )
            self.wizard = DispatchWizardWidget(
                profile_name=PROFILE_NAME,
                profile_dir=profile_dir,
            )
            self.wizard.controller.select_peer("bob")
            self.wizard.controller.select_sender_agent("scale_agent_0")
            self.wizard.controller.select_receiver_agent("bob_agent")
            self.wizard.step_index = 4

        def compose(self) -> ComposeResult:
            yield self.arena
            yield self.wizard

    app = build_tui_app(ConcurrentBurstApp)
    typed_goal = (
        "keep every dispatch goal character ordered while the live event stream exceeds "
        "thirty one events per second"
    )
    burst_timing: dict[str, float] = {}
    burst_count = 48

    def append_burst() -> None:
        writer = ensure_profile_db(profile_dir / "kin.db")
        burst_timing["start"] = time.perf_counter()
        try:
            for index in range(burst_count):
                result = append_session_event(
                    writer,
                    VAULT_KEY,
                    session_id="sess-burst-focus",
                    actor_username="bob",
                    actor_agent_id="bob_agent",
                    kind="finding",
                    payload={"content": f"concurrent burst event {index}"},
                    sequence=index + 1,
                )
                assert result["status"] == "appended"
                target = burst_timing["start"] + ((index + 1) / 40.0)
                time.sleep(max(0.0, target - time.perf_counter()))
        finally:
            burst_timing["end"] = time.perf_counter()
            writer.close()

    async with app.run_test(size=(120, 36)) as pilot:
        app.set_focus(app.wizard)
        await pilot.pause()
        assert app.focused is app.wizard
        burst_task = asyncio.create_task(asyncio.to_thread(append_burst))
        typing_started = time.perf_counter()
        focus_was_preserved = True
        for character in typed_goal:
            await pilot.press(character)
            await pilot.pause(0.01)
            focus_was_preserved = focus_was_preserved and app.focused is app.wizard
        typing_ended = time.perf_counter()
        await burst_task

        for _ in range(40):
            if len(app.arena.events) == burst_count:
                break
            await pilot.pause(0.1)

        burst_seconds = burst_timing["end"] - burst_timing["start"]
        burst_rate = burst_count / burst_seconds
        assert burst_rate >= 31.0
        assert burst_timing["start"] < typing_ended
        assert burst_timing["end"] > typing_started
        assert app.wizard.prompt == typed_goal
        assert app.wizard.step_index == 4
        assert focus_was_preserved is True
        assert app.focused is app.wizard
        assert len(app.arena.events) == burst_count
        assert len({event.event_id for event in app.arena.events}) == burst_count

    print(
        "PHASE C INPUT BURST: "
        f"events={burst_count}, seconds={burst_seconds:.3f}, rate_eps={burst_rate:.2f}, "
        f"typed_chars={len(typed_goal)}, dropped_or_reordered=0, focus_preserved=True"
    )


@pytest.mark.asyncio
async def test_10k_profile_resize_memory_plateaus_across_breakpoints(
    phase_c_scale_profile,
    build_tui_app,
    monkeypatch,
) -> None:
    """Repeated responsive re-rendering retains exact history without memory drift."""
    _install_profile_keys()
    monkeypatch.setenv("KIN_RELAY_URL", "http://127.0.0.1:9")
    profile_dir = phase_c_scale_profile["profile_dir"]
    tracemalloc.start()
    app = build_tui_app(profile_name=PROFILE_NAME, profile_dir=profile_dir)
    memory_samples: list[int] = []
    breakpoints = (
        ((160, 44), "wide"),
        ((120, 36), "standard"),
        ((90, 28), "compact"),
        ((80, 24), "minimal"),
    )

    try:
        async with app.run_test(size=(160, 44)) as pilot:
            app.tab_manager.open_tab(f"tab:{HOT_SESSION_ID}", "10k scale arena", "session")
            app.sync_tab_bar()
            await app.canvas.recompose()
            await pilot.pause(0.5)
            arena = app.canvas.query_one(SessionArenaWidget)
            expected_ids = [event.event_id for event in arena.events]
            assert len(expected_ids) >= BASE_EVENT_COUNT
            assert len(set(expected_ids)) == len(expected_ids)

            gc.collect()
            baseline_current, _ = tracemalloc.get_traced_memory()
            for _cycle in range(3):
                for (width, height), expected_breakpoint in breakpoints:
                    await pilot.resize_terminal(width, height)
                    await pilot.pause(0.15)
                    assert app.screen.size.width == width
                    assert app.screen.size.height == height
                    assert app.current_breakpoint == expected_breakpoint
                    assert [event.event_id for event in arena.events] == expected_ids
                    if expected_breakpoint == "minimal":
                        assert app.sidebar.styles.display == "none"
                        assert app.minimal_breadcrumb.styles.display == "block"
                    else:
                        assert app.sidebar.styles.display == "block"
                        assert app.minimal_breadcrumb.styles.display == "none"
                gc.collect()
                current, _ = tracemalloc.get_traced_memory()
                memory_samples.append(current)

            retained_growth = memory_samples[-1] - memory_samples[0]
            assert retained_growth < 16 * 1024 * 1024
            assert memory_samples[-1] < baseline_current + 32 * 1024 * 1024
            current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    print(
        "PHASE C RESIZE MEMORY: "
        f"events={len(expected_ids)}, cycles=3, breakpoints=4, "
        f"samples_mb={[round(sample / 1024 / 1024, 2) for sample in memory_samples]}, "
        f"retained_growth_mb={retained_growth / 1024 / 1024:.2f}, "
        f"current_mb={current / 1024 / 1024:.2f}, peak_mb={peak / 1024 / 1024:.2f}"
    )
