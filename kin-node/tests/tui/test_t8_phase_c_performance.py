"""T8 Phase C release gates for startup scale and 10k-event paging."""

from time import perf_counter
from io import StringIO

from rich.console import Console

from kin.tui.fixtures import make_agent_card_view_fixture, make_session_summary_fixture
from kin.schemas import AgentAvailability
from kin.tui.local_state import ensure_profile_db, get_session_events_page
from kin.tui.state import HealthSnapshot
from kin.tui.widgets.data_table import DataTableWidget
from kin.tui.widgets.home_screen import HomeScreenWidget
from kin.tui.widgets.session_arena import SessionArenaWidget


def test_dashboard_100_sessions_20_agents_is_ready_under_two_seconds(tmp_path):
    agents = [
        make_agent_card_view_fixture(AgentAvailability.READY)
        for _ in range(20)
    ]
    sessions = [make_session_summary_fixture("active", f"sess-scale-{index}") for index in range(100)]
    started = perf_counter()
    widget = HomeScreenWidget(
        profile_dir=tmp_path,
        profile_name="scale-owner",
        agents=agents,
        sessions=sessions,
        health=HealthSnapshot(
            keychain_ok=True,
            identity_ok=True,
            relay_reachable=True,
            node_reachable=True,
            pending_inbox_count=0,
        ),
    )
    output = StringIO()
    Console(file=output, width=160, color_system=None, force_terminal=False).print(widget.render())
    rendered = output.getvalue()
    elapsed = perf_counter() - started
    assert elapsed < 2.0, f"100-session/20-agent dashboard took {elapsed:.3f}s"
    assert "+ 90 more sessions" in rendered
    assert "+ 14 more agents" in rendered


def test_10k_collection_navigation_keeps_render_work_bounded():
    rows = [{"id": index, "name": f"Event {index}", "status": "verified"} for index in range(10_000)]
    widget = DataTableWidget(rows=rows, visible_rows_window=12)
    started = perf_counter()
    for _ in range(100):
        widget.cursor_down()
        rendered = widget.render()
    elapsed = perf_counter() - started
    assert elapsed < 0.5, f"100 input/render updates took {elapsed:.3f}s"
    assert "101/10000 rows" in rendered
    assert rendered.count("verified") <= 12


def test_10k_session_events_page_without_order_loss_or_duplicate(tmp_path):
    conn = ensure_profile_db(tmp_path / "kin.db")
    conn.execute(
        """INSERT INTO sessions
           (session_id, initiator_username, receiver_username, status, type, created_at, updated_at)
           VALUES ('sess-10k', 'alice', 'bob', 'active', 'research',
                   '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )
    conn.executemany(
        """INSERT INTO session_events
           (event_id, session_id, kind, created_at, actor_username, event_order, visibility)
           VALUES (?, 'sess-10k', 'finding', ?, 'bob', ?, 'peer_visible')""",
        [
            (f"event-{index:05d}", f"2026-08-05T00:{index // 60 % 60:02d}:{index % 60:02d}Z", index)
            for index in range(1, 10_001)
        ],
    )
    conn.commit()
    conn.close()

    started = perf_counter()
    newest, has_older = get_session_events_page(tmp_path, "sess-10k", page_size=500)
    elapsed = perf_counter() - started
    assert elapsed < 2.0, f"Initial 10k-history page took {elapsed:.3f}s"
    assert has_older is True
    assert [event.event_order for event in newest] == list(range(9501, 10_001))

    arena = SessionArenaWidget(session_id="sess-10k", profile_dir=tmp_path, profile_name="scale-owner")
    assert len(arena.events) == 500
    assert arena.has_older_events is True
    while arena.has_older_events:
        assert arena.load_older_events() == 500
    orders = [event.event_order for event in arena.events]
    assert orders == list(range(1, 10_001))
    assert len({event.event_id for event in arena.events}) == 10_000
