# KIN V1.1 TUI — T8 Phase C Progress

Date: 2026-08-05
Branch: `codex/t8-phase-c-performance-scale`
Base: `6e730af test(tui): enforce Phase B artifact hash equality`
Scope: T8 Phase C only. Phase D has not started.

## Outcome

Phase C is implemented and verified against the four performance and scale gates:

1. A real profile retains 10,100 events, including a 10,000-event active session. Every event is written through production `append_session_event()` so encryption, audit mirroring, actor sequencing, and commit behavior remain in the measurement. Full history preserves exact order, actor provenance, and unique IDs; incremental C2 polling reads only the 35 newly appended rows.
2. A real `KinApp` mounts Home with 100 persisted sessions and 20 filesystem agent cards and accepts focus in less than two seconds on three consecutive runs.
3. A production event writer delivers 48 events at 40 events/second while `pilot.press()` types a 107-character Dispatch Goal. The exact string, character order, wizard step, and focus are preserved; the Arena receives 48 unique events.
4. A real 10k-event Arena survives three complete resize cycles across wide, standard, compact, and 80x24 minimal breakpoints. Exact event IDs remain stable, responsive shell regions switch correctly, and retained memory growth plateaus at 0.14 MiB.

## Production changes

### Full retention with bounded presentation

`ExchangeTimelineWidget` still owns and navigates the complete event list. Its rendered card window is bounded to 100 coalesced groups around the selection, with explicit earlier/later retained-history markers. Tail jumps and keyboard navigation continue to address the full index space; no event is truncated from state.

### Persisted Home sessions

Home previously defaulted to an empty session list even when the selected profile contained real sessions. It now loads the persisted session summaries whenever the caller has not supplied an explicit override. Bounded Home presentation remains unchanged.

### Interactive startup no longer waits for relay timeout

Home render previously performed the relay reachability request synchronously. An unavailable relay could block initial input for roughly five seconds. Home now builds its immediate snapshot from local identity/keychain/inbox state and performs the real relay probe in a Textual worker, updating the cached snapshot on the UI thread when it completes. Explicit injected health and HTTP clients remain deterministic for tests.

## Real/fixture boundary

- Event rows are never inserted directly. The 10,135 scale and incremental events all enter through `append_session_event()` with a real vault key and production SQLite schema.
- Session and identity setup uses direct SQL only as prerequisite fixture setup; it does not bypass the event path being measured.
- Startup mounts the real `KinApp`, `MainCanvas`, and `HomeScreenWidget`; its 100 sessions and 20 agent cards are read from the profile database/filesystem.
- Burst input is real Textual keyboard delivery through `pilot.press()`. Event writes run concurrently in another thread through the production append API, and Arena consumes them through its real C2 poller.
- Resize/memory proof mounts the real shell and real Arena over the 10k profile. `tracemalloc` samples after garbage collection at the end of each complete breakpoint cycle.

## Reproducible raw evidence

### Complete Phase C performance/scale module

Command:

```text
python -m pytest tests/tui/test_t8_phase_c_performance_scale.py -m smoke -q -s
```

Output:

```text
PHASE C 10K: profile_events=10100, append_seed_seconds=53.109, initial_fetch_seconds=0.255, timeline_render_seconds=0.009, visible_groups=100/10000, incremental_rows=35, incremental_seconds=0.0081
.PHASE C STARTUP: runs_seconds=[0.8498, 0.6834, 0.4247], max_seconds=0.8498, sessions=100, agents=20
.PHASE C INPUT BURST: events=48, seconds=1.200, rate_eps=40.00, typed_chars=107, dropped_or_reordered=0, focus_preserved=True
.PHASE C RESIZE MEMORY: events=10035, cycles=3, breakpoints=4, samples_mb=[16.42, 16.52, 16.55], retained_growth_mb=0.14, current_mb=16.55, peak_mb=25.72
.
4 passed in 123.49s (0:02:03)
```

### Focused UI regressions

Command:

```text
python -m pytest tests/tui/test_home_screen.py tests/tui/test_session_arena_streaming_c1.py tests/tui/test_session_arena_streaming_c2.py tests/tui/test_workspace_tabs.py -q
```

Output:

```text
.......................................                                  [100%]
39 passed in 2.85s
```

### Complete default regression gate

Command:

```text
python -m pytest -m "not smoke" -q
```

Output tail:

```text
..................                                                       [100%]
--------------------------- snapshot report summary ---------------------------
14 snapshots passed.
1458 passed, 9 deselected in 114.82s (0:01:54)
```

## Review boundary

Phase C is ready for independent review on `codex/t8-phase-c-performance-scale`. Phase D release-gate implementation is intentionally excluded pending review.
