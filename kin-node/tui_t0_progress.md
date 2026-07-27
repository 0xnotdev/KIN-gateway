# KIN V1.1 TUI Milestone T0 Progress Report

**Milestone:** T0 — Skeleton, Tokens, Typed View Models, and Deterministic Snapshot Infrastructure  
**Issued by:** Claude (Tech Lead)  
**Execution Engine:** Antigravity  
**Spec Authority:** `KIN-V1.1-TUI-SYSTEM.md` §2, §3.4, §8.1, §11, §14.1, §14.2  
**Date:** 2026-07-26  

---

## 1. Architectural Decisions & Rationale

1. **Strict Enum Mapping & Loud Failure Mode (`map_event_kind_to_presentation_class`):**
   - Refactored `map_event_kind_to_presentation_class` in `kin/tui/state.py` to switch strictly on real schema enum members (`MessageKind` and `InternalEventKind`), eliminating string literal matches typed from memory.
   - **Exhaustive Mapping Rationale (25 Enum Members):**
     - `MessageKind` (18 members):
       - `TASK_REQUEST`, `CLARIFICATION`, `PROPOSAL`, `COUNTERPROPOSAL`, `QUESTION`, `ANSWER` -> `"message"`
       - `ACCEPTANCE`, `DECLINE`, `FINAL_RESULT`, `CANCEL`, `PARTICIPANT_CHANGED` -> `"state_transition"`
       - `PLAN`, `FINDING`, `STATUS_EVENT` -> `"activity"` *(Rationale: STATUS_EVENT does not drive reducer state transitions in PEER_KIND_TRANSITION_MAP; it represents periodic non-transitional status info).*
       - `ARTIFACT_OFFER`, `ARTIFACT_ACCEPT` -> `"artifact"`
       - `APPROVAL_REQUEST`, `APPROVAL_DECISION` -> `"approval"`
     - `InternalEventKind` (7 members):
       - `MESSAGE`, `PUBLIC_MSG` -> `"message"`
       - `ENVELOPE_RECEIVED`, `PRIVATE_NOTE`, `OUTBOUND_ENVELOPE_QUEUED`, `ACTIVITY` -> `"activity"`
       - `ADAPTER_ERROR` -> `"security"` *(Explicit rationale: adapter errors/failures must be rendered as security/alert presentation class so they are never lost in muted activity noise).*
   - **Loud Failure Mode:** Unrecognized event kinds raise `ValueError` rather than silently defaulting to `"activity"`. When M5 adds a new `MessageKind` or `InternalEventKind` in the future, the TUI test suite will fail loudly during CI.

2. **Deterministic Injectable Clock (`ApprovalView`):**
   - Added an optional `now: datetime | str | None` parameter to `ApprovalView`.
   - When supplied, `time_remaining` calculation is 100% deterministic and isolated from test runner execution speed.
   - When omitted, it safely defaults to wall-clock `datetime.now(timezone.utc)`.

3. **Theme Scope Cut (Deferred to T7):**
   - Implemented one fully populated theme: `kin-graphite` (graphite/indigo surfaces, mint live state, violet focus).
   - Registered the remaining 5 theme names (`kin-night`, `nord`, `dracula`, `catppuccin-mocha`, `high-contrast`) as recognized fallback themes. Requesting them resolves to `kin-graphite` with `is_fallback = True` and records the requested theme name without raising, strictly preserving the scope cut specified for T0 (§14.9).

4. **Snapshot Testing API Choice:**
   - Evaluated `pytest-textual-snapshot` (v1.1.0) and used its official `snap_compare` pytest fixture.
   - Snapshots were captured deterministically for the blank shell at all four specified breakpoint dimensions: `160x44` (wide), `120x36` (standard), `90x28` (compact), and `80x24` (minimal).

5. **No Editing of Restricted Modules:**
   - Zero edits were made to `kin/cli.py`, `kin/artifacts/*`, `kin/policy/*`, `kin/session/*`, `kin/node/*`, `kin/agent_registry/*`, `kin/storage/*`, or `kin/transport/*`.
   - Entry point for T0 is strictly `python -m kin.tui` (`kin/tui/__main__.py`).
   - Profile path computation (`Path.home() / ".kin" / "profiles" / profile_name`) was implemented as an independent one-liner helper in `kin/tui/app.py` to prevent coupling with `kin/cli.py`.

6. **Grepping for Direct `rich` Imports:**
   - Grepped codebase across `kin/` and `tests/` for `import rich` and `from rich`. Result: 0 matches found. No existing rendering code regressed.

---

## 2. Exact Resolved Dependency Versions & Shared Side Effect Notice

```text
textual: 8.2.8
rich: 14.3.3
typer: 0.27.0
pytest: 8.4.2
pytest-asyncio: 1.4.0
pytest-textual-snapshot: 1.1.0
syrupy: 4.8.0
```

> **Disclosed Shared Side Effect:** `pytest-textual-snapshot 1.1.0` pins `syrupy==4.8.0`, which caps `pytest<9.0.0`; combined with `pytest-asyncio`'s floor requirement of `pytest>=8.4`, `8.4.2` is the only satisfiable version. This downgrades `pytest` project-wide (not just for `kin/tui`) from the `9.1.0` baseline used in every previous M5 phase report. This is a disclosed, shared side effect of introducing Textual visual snapshot testing into `pyproject.toml`.

---

## 3. Three Consecutive Pre-Existing Test Suite Raw Outputs (`py -3.11 -m pytest --ignore=tests/tui`)

### Run 1 (Pre-existing Suite — 292 Passed)
```text
[2026-07-26 18:22:58,076] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 293 items / 1 deselected / 292 selected

tests\test_adapter_output_redaction.py ....                              [  1%]
tests\test_adapters_contract.py ...                                      [  2%]
tests\test_agent_projection.py ..                                        [  3%]
tests\test_agent_registry.py ............                                [  7%]
tests\test_agent_roster.py ................                              [ 12%]
tests\test_artifacts_vault.py ........                                   [ 15%]
tests\test_audit.py ..                                                   [ 16%]
tests\test_cli_agent.py .....                                            [ 17%]
tests\test_cli_ask.py ............................                       [ 27%]
tests\test_cli_pair.py ..........                                        [ 30%]
tests\test_cli_relay_fallback.py .....                                   [ 32%]
tests\test_compatibility.py ....                                         [ 33%]
tests\test_export.py ....                                                [ 35%]
tests\test_fingerprint.py ...                                            [ 36%]
tests\test_harness_isolation.py ....                                     [ 37%]
tests\test_keyring_isolation.py ..                                       [ 38%]
tests\test_keys.py .............                                         [ 42%]
tests\test_local_command_security.py ...                                 [ 43%]
tests\test_migrations.py ...........                                     [ 47%]
tests\test_orchestrator_e2e.py ......                                    [ 49%]
tests\test_orchestrator_event_ordering.py .                              [ 50%]
tests\test_policy_evaluator.py .........                                 [ 53%]
tests\test_schemas.py ...............                                    [ 58%]
tests\test_session_recovery.py ..                                        [ 58%]
tests\test_session_reducer.py .......................................... [ 73%]
............................                                             [ 82%]
tests\test_setup.py ...                                                  [ 83%]
tests\test_storage.py .                                                  [ 84%]
tests\test_storage_keychain.py ............                              [ 88%]
tests\test_v11_transport_m3.py .................................         [ 99%]
tests\test_vault.py .                                                    [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 292 passed, 1 deselected, 1 warning in 22.39s ================
```

### Run 2 (Pre-existing Suite — 292 Passed)
```text
[2026-07-26 18:23:25,784] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 293 items / 1 deselected / 292 selected

tests\test_adapter_output_redaction.py ....                              [  1%]
tests\test_adapters_contract.py ...                                      [  2%]
tests\test_agent_projection.py ..                                        [  3%]
tests\test_agent_registry.py ............                                [  7%]
tests\test_agent_roster.py ................                              [ 12%]
tests\test_artifacts_vault.py ........                                   [ 15%]
tests\test_audit.py ..                                                   [ 16%]
tests\test_cli_agent.py .....                                            [ 17%]
tests\test_cli_ask.py ............................                       [ 27%]
tests\test_cli_pair.py ..........                                        [ 30%]
tests\test_cli_relay_fallback.py .....                                   [ 32%]
tests\test_compatibility.py ....                                         [ 33%]
tests\test_export.py ....                                                [ 35%]
tests\test_fingerprint.py ...                                            [ 36%]
tests\test_harness_isolation.py ....                                     [ 37%]
tests\test_keyring_isolation.py ..                                       [ 38%]
tests\test_keys.py .............                                         [ 42%]
tests\test_local_command_security.py ...                                 [ 43%]
tests\test_migrations.py ...........                                     [ 47%]
tests\test_orchestrator_e2e.py ......                                    [ 49%]
tests\test_orchestrator_event_ordering.py .                              [ 50%]
tests\test_policy_evaluator.py .........                                 [ 53%]
tests\test_schemas.py ...............                                    [ 58%]
tests\test_session_recovery.py ..                                        [ 58%]
tests\test_session_reducer.py .......................................... [ 73%]
............................                                             [ 82%]
tests\test_setup.py ...                                                  [ 83%]
tests\test_storage.py .                                                  [ 84%]
tests\test_storage_keychain.py ............                              [ 88%]
tests\test_v11_transport_m3.py .................................         [ 99%]
tests\test_vault.py .                                                    [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 292 passed, 1 deselected, 1 warning in 22.27s ================
```

### Run 3 (Pre-existing Suite — 292 Passed)
```text
[2026-07-26 18:23:55,024] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 293 items / 1 deselected / 292 selected

tests\test_adapter_output_redaction.py ....                              [  1%]
tests\test_adapters_contract.py ...                                      [  2%]
tests\test_agent_projection.py ..                                        [  3%]
tests\test_agent_registry.py ............                                [  7%]
tests\test_agent_roster.py ................                              [ 12%]
tests\test_artifacts_vault.py ........                                   [ 15%]
tests\test_audit.py ..                                                   [ 16%]
tests\test_cli_agent.py .....                                            [ 17%]
tests\test_cli_ask.py ............................                       [ 27%]
tests\test_cli_pair.py ..........                                        [ 30%]
tests\test_cli_relay_fallback.py .....                                   [ 32%]
tests\test_compatibility.py ....                                         [ 33%]
tests\test_export.py ....                                                [ 35%]
tests\test_fingerprint.py ...                                            [ 36%]
tests\test_harness_isolation.py ....                                     [ 37%]
tests\test_keyring_isolation.py ..                                       [ 38%]
tests\test_keys.py .............                                         [ 42%]
tests\test_local_command_security.py ...                                 [ 43%]
tests\test_migrations.py ...........                                     [ 47%]
tests\test_orchestrator_e2e.py ......                                    [ 49%]
tests\test_orchestrator_event_ordering.py .                              [ 50%]
tests\test_policy_evaluator.py .........                                 [ 53%]
tests\test_schemas.py ...............                                    [ 58%]
tests\test_session_recovery.py ..                                        [ 58%]
tests\test_session_reducer.py .......................................... [ 73%]
............................                                             [ 82%]
tests\test_setup.py ...                                                  [ 83%]
tests\test_storage.py .                                                  [ 84%]
tests\test_storage_keychain.py ............                              [ 88%]
tests\test_v11_transport_m3.py .................................         [ 99%]
tests\test_vault.py .                                                    [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 292 passed, 1 deselected, 1 warning in 21.73s ================
```

---

## 4. New TUI Test Suite Raw Output (`py -3.11 -m pytest -v tests/tui/`)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, asyncio-1.4.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 25 items

tests/tui/test_app_shell.py::test_non_tty_launches_one_line_message_and_exits_zero PASSED [  4%]
tests/tui/test_app_shell.py::test_tty_detection_positive PASSED          [  8%]
tests/tui/test_app_shell.py::test_app_normal_quit PASSED                 [ 12%]
tests/tui/test_app_shell.py::test_app_ctrl_c_quit PASSED                 [ 16%]
tests/tui/test_app_shell.py::test_terminal_restoration_on_injected_exception PASSED [ 20%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_160x44 PASSED     [ 24%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_120x36 PASSED     [ 28%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_90x28 PASSED      [ 32%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_80x24 PASSED      [ 36%]
tests/tui/test_error_boundary.py::test_exception_conversion_to_recoverable_error PASSED [ 40%]
tests/tui/test_error_boundary.py::test_tui_error_boundary_catches_exception_without_crashing PASSED [ 44%]
tests/tui/test_state_fixtures.py::test_session_summary_factories_cover_all_16_statuses PASSED [ 48%]
tests/tui/test_state_fixtures.py::test_agent_card_view_factories_cover_all_8_availabilities PASSED [ 52%]
tests/tui/test_state_fixtures.py::test_approval_view_factories_cover_risk_labels_and_decisions PASSED [ 56%]
tests/tui/test_state_fixtures.py::test_approval_view_injectable_clock_determinism PASSED [ 60%]
tests/tui/test_state_fixtures.py::test_artifact_view_factory_mime_variants PASSED [ 64%]
tests/tui/test_state_fixtures.py::test_recoverable_error_factories PASSED [ 68%]
tests/tui/test_state_fixtures.py::test_default_uistate_fixture_construction PASSED [ 72%]
tests/tui/test_state_fixtures.py::test_peer_agent_card_view_security_isolation PASSED [ 76%]
tests/tui/test_state_fixtures.py::test_exhaustive_presentation_class_mapping_purity PASSED [ 80%]
tests/tui/test_tokens.py::test_every_required_role_resolves_under_kin_graphite PASSED [ 84%]
tests/tui/test_tokens.py::test_missing_role_theme_is_rejected_by_validator PASSED [ 88%]
tests/tui/test_tokens.py::test_unimplemented_theme_name_falls_back_to_kin_graphite PASSED [ 92%]
tests/tui/test_tokens.py::test_widget_role_consumption_validator PASSED  [ 96%]
tests/tui/test_tokens.py::test_glyph_registry_ascii_fallbacks PASSED     [100%]

--------------------------- snapshot report summary ---------------------------
4 snapshots passed.
============================= 25 passed in 1.18s ==============================
```

---

## 5. Known Limitations & Deferred Items

1. **Unimplemented Themes (Deferred to T7):** Five recognized theme names (`kin-night`, `nord`, `dracula`, `catppuccin-mocha`, `high-contrast`) fall back to `kin-graphite`. Full palette implementation deferred to Milestone T7 per spec §14.9.
2. **Product Screens (Deferred to T1+):** No product screens, sidebar regions, workspace tabs, or inspector panels exist in T0.
3. **`kin/cli.py` Wiring (Deliberate Hold):** Main application entry point is `python -m kin.tui`. Wiring into `kin/cli.py` is deliberately deferred until M5 CLI changes conclude.
4. **Live Node Integration (Deferred to T8):** `UiState.node_snapshot` is an opaque dictionary container. Real node integration arrives in T8.
5. **Plain-Mode Parity (Deferred to T7):** Non-TTY launch outputs a one-line notification (`KIN TUI requires an interactive terminal; run a subcommand instead.`). Full plain-mode rendering parity is deferred to T7.

---

## 6. Checkpoint T0 Bar Verification

> **Checkpoint T0 bar:** *"kin launches a blank styled shell and exits cleanly; it can be snapshotted at every required size. No workflow is exposed yet."*

- **Status:** **PASSED GREEN**
- **Evidence:** `python -m kin.tui` launches the blank styled panel in interactive terminals and exits cleanly on `q` or `Ctrl+C`. Textual snapshot tests pass deterministically at `160x44`, `120x36`, `90x28`, and `80x24`.
