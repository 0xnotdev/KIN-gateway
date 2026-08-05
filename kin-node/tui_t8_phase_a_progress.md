# KIN V1.1 T8 — Phase A Real-Node Integration Evidence

**Spec authority:** `KIN-V1.1-TUI-SYSTEM.md` §14.10, §14.11

**Scope:** Phase A / Build Step 1 only

**Branch:** `codex/t8-phase-a-real-node`

**Status:** Ready for review; Phase B has not started

## Implementation

The original `scripts/smoke_two_node.py` remains the entry point and now accepts `--protocol v11`. Relay startup, identity initialization, real node startup, bidirectional fingerprint pairing, port allocation, environment isolation, and teardown live in one shared `TwoNodeSmokeHarness`. The legacy M0 test and both V1.1 tests consume that same setup; there is no parallel pairing or process-management implementation.

The V1.1 path performs these operations in profile-specific subprocesses:

1. Alice and Bob import deterministic V1.1 agent cards.
2. Each profile synchronizes the other's published card through the authenticated real `/v1.1/agents/cards` HTTP endpoint.
3. Alice calls the production `kin.transport.v11.dispatch_session()` against Bob's running node with `collaboration_mode="ask"` and a real goal.
4. A separate Bob subprocess opens Bob's own database and proves the session and first event were persisted.
5. Bob accepts through `respond_to_session()`.
6. Alice sends a question, Bob sends an answer, and Bob sends `final_result` through `send_session_message()`.
7. Separate Alice and Bob subprocesses prove both databases contain the same ordered five event kinds and terminal `completed` status.

The TUI smoke test mounts a real `KinApp` against the same Alice profile directory currently served by Alice's node. `pilot.press()` opens Dispatch, selects the paired Bob contact, selects Alice and Bob's real synced cards, types the goal, advances through review, and confirms. A separate Bob subprocess then proves Bob stored the resulting session.

## Integration Defects Found and Fixed

- `KinApp(profile_dir=...)` previously constructed `MainCanvas()` without the supplied profile context. Consequently the reachable Dispatch wizard silently queried the default profile. `KinApp` now passes `profile_dir` and `profile_name` into `MainCanvas`, which passes them to its workspace widgets.
- The Dispatch completion label only recognized obsolete `delivered_direct` / `queued_relay` spellings. It now also recognizes the production transport results `delivered` / `queued`.
- The real-network smoke worker now explicitly installs the existing file-backed unsafe test keyring when requested. This lets separate subprocesses use the same isolated profile keys without substituting synthetic transport or identity mocks.
- V1.1 agent provisioning is enabled only for V1.1 harness runs, preserving the legacy M0 agent-roster format and smoke path.

The profile-context correction intentionally updates one golden snapshot: `test_long_profile_name_snapshot_120x36.svg` now shows the requested long profile in the canvas instead of the incorrect `default` profile. The other thirteen snapshots are unchanged.

## What Crossed a Real Network Boundary

- Relay health and directory registration use the running `kin-relay` Uvicorn process.
- Alice and Bob are separate `kin.cli serve` subprocesses on distinct real TCP ports.
- Pairing performs real directory lookup and fingerprint verification in both directions.
- Agent card synchronization performs signed HTTP GETs against the peer node.
- Dispatch performs Bob capability negotiation and sends the signed task-request envelope to Bob's `/v1.1/sessions` endpoint.
- Acceptance, question, answer, and final-result envelopes are cryptographically signed, self-ingested, and sent to the other running node.
- Bob-side receipt and both terminal histories are queried by separate profile subprocesses, not imported into Alice's process.
- The TUI-confirmed Dispatch request travels from the pytest-hosted Alice `KinApp` to the separate Bob node process over real HTTP.

No `httpx.MockTransport`, mocked POST, in-process peer ingestion, or raw cross-profile database import is used in either Phase A proof.

## What Remains an Intentional Local Read / Fixture

- `KinApp` reads Alice's own SQLite profile directly through `local_state.py`. This is the product's intended local state boundary.
- The smoke profiles, agent cards, keyring files, and ports are isolated temporary test fixtures.
- The imported agent cards are deterministic smoke definitions. V1.1 Phase A does not invoke an LLM or claim to verify model behavior.
- Bob's database is read directly only inside a separate Bob subprocess, as required. Alice's process never opens Bob's database.

## Raw Standalone Output

Command:

```powershell
python scripts/smoke_two_node.py --protocol v11
```

Output:

```text
SMOKE V1.1: session_id=sess_83ffac862e3f4a81
SMOKE V1.1: Bob subprocess storage proof -> status=peer_review, event_count=1, goal='Coordinate a real V1.1 smoke collaboration'
SMOKE V1.1: Alice final -> status=completed, event_count=5, kinds=["task_request", "acceptance", "question", "answer", "final_result"]
SMOKE V1.1: Bob final -> status=completed, event_count=5, kinds=["task_request", "acceptance", "question", "answer", "final_result"]
PASS: V1.1 two-node session lifecycle over real sockets succeeded!
SMOKE: Selected real ports -> relay: 64562, alice: 64563, bob: 64564
SMOKE: Computed Fingerprints MATCH -> alice: great-nose-flower-rifle, bob: great-nose-flower-rifle
```

Exit code: `0`.

## Raw Focused Pytest Output

Command:

```powershell
python -m pytest -m smoke -s -vv tests/test_smoke_two_node.py::test_two_node_v11_session_lifecycle_real_sockets tests/tui/test_smoke_real_node_dispatch.py::test_keyboard_dispatch_reaches_separate_real_bob_node
```

Output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.12.1, asyncio-1.4.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_smoke_two_node.py::test_two_node_v11_session_lifecycle_real_sockets SMOKE V1.1: session_id=sess_36cd19731d2641df
SMOKE V1.1: Bob subprocess storage proof -> status=peer_review, event_count=1, goal='Coordinate a real V1.1 smoke collaboration'
SMOKE V1.1: Alice final -> status=completed, event_count=5, kinds=["task_request", "acceptance", "question", "answer", "final_result"]
SMOKE V1.1: Bob final -> status=completed, event_count=5, kinds=["task_request", "acceptance", "question", "answer", "final_result"]
PASS: V1.1 two-node session lifecycle over real sockets succeeded!
PASSED
tests/tui/test_smoke_real_node_dispatch.py::test_keyboard_dispatch_reaches_separate_real_bob_node TUI REAL-NODE: alice_profile=C:\Users\deban\AppData\Local\Temp\kin_smoke_hb07hbrj\alice_home\.kin\profiles\alice, bob_port=52836
TUI REAL-NODE: keyboard dispatch -> session_id=sess_85422050fe8f41c6, transport_status=delivered
TUI REAL-NODE: Bob subprocess storage proof -> status=peer_review, event_count=1, kinds=['task_request'], goal='prove keyboard dispatch over a real node boundary'
PASS: KinApp pilot keyboard dispatch reached the separate real Bob node
PASSED

============================= 2 passed in 52.65s ==============================
SMOKE: Selected real ports -> relay: 52799, alice: 52800, bob: 52801
SMOKE: Computed Fingerprints MATCH -> alice: fame-library-riot-bronze, bob: fame-library-riot-bronze
SMOKE: Selected real ports -> relay: 52834, alice: 52835, bob: 52836
SMOKE: Computed Fingerprints MATCH -> alice: save-tuition-drink-embody, bob: save-tuition-drink-embody
```

Exit code: `0`.

## Raw Combined Smoke Regression

Command:

```powershell
python -m pytest -m smoke -s -vv tests/test_smoke_two_node.py tests/tui/test_smoke_real_node_dispatch.py
```

Result:

```text
collected 3 items
tests/test_smoke_two_node.py::test_two_node_walking_skeleton_real_sockets PASSED
tests/test_smoke_two_node.py::test_two_node_v11_session_lifecycle_real_sockets PASSED
tests/tui/test_smoke_real_node_dispatch.py::test_keyboard_dispatch_reaches_separate_real_bob_node PASSED
======================== 3 passed in 69.12s (0:01:09) =========================
```

## Raw Default Regression Output

Command:

```powershell
python -m pytest -q
```

Output:

```text
........................................................................ [  4%]
........................................................................ [  9%]
........................................................................ [ 14%]
........................................................................ [ 19%]
........................................................................ [ 24%]
........................................................................ [ 29%]
........................................................................ [ 34%]
........................................................................ [ 39%]
........................................................................ [ 44%]
........................................................................ [ 49%]
........................................................................ [ 54%]
........................................................................ [ 59%]
........................................................................ [ 64%]
........................................................................ [ 69%]
........................................................................ [ 74%]
........................................................................ [ 79%]
........................................................................ [ 84%]
........................................................................ [ 88%]
........................................................................ [ 93%]
........................................................................ [ 98%]
.................                                                        [100%]
--------------------------- snapshot report summary ---------------------------
14 snapshots passed.
1457 passed, 3 deselected in 112.39s (0:01:52)
```

Exit code: `0`.

## Review Gate

Phase A is complete and pushed for independent review. Phase B relay fallback, restart/reconnect, expiry, and artifact-restart work has deliberately not begun.
