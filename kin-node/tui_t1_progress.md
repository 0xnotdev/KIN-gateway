# KIN V1.1 TUI Milestone T1 Progress Report

**Milestone:** T1 — Stable Shell, Responsive Geometry, and Preference Persistence  
**Issued by:** Claude (Tech Lead)  
**Execution Engine:** Antigravity  
**Spec Authority:** `KIN-V1.1-TUI-SYSTEM.md` §3, §3.1, §3.2, §3.3, §3.4, §14.3  
**Date:** 2026-07-26  

---

## 1. Architectural Decisions & Rationale

1. **Five Stable Persistent Regions (`shell.py`):**
   - Implemented `WorkspaceTabBar` (`#workspace-tab-bar`), `Sidebar` (`#sidebar`), `MainCanvas` (`#main-canvas`), `Inspector` (`#inspector`), and `StatusBar` (`#status-bar`) as Textual widgets with stable IDs.
   - All five regions remain mounted when content, profile, or breakpoint changes. They are never torn down or recreated on terminal resize.

2. **Breakpoint Classification (`layout.py`):**
   - Defined `Breakpoint` Literal type (`wide`, `standard`, `compact`, `minimal`).
   - Pure function `classify_breakpoint(cols, rows) -> Breakpoint` classifies geometry:
     - `wide`: `cols >= 160` and `rows >= 44`
     - `standard`: `120 <= cols <= 159` and `rows >= 36`
     - `compact`: `90 <= cols <= 119` and `rows >= 28`
     - `minimal`: `cols < 90` or `rows < 28`
   - In `compact` breakpoint: sidebar automatically collapses into an icon rail (`●`, `✓`, `!`, `→`, count, selection marker), inspector hides.
   - In `minimal` breakpoint (including required `80x24`): single-pane stack with a one-time resize notification hint (`Resize terminal to at least 90x28 for full experience.`).

3. **Pydantic Preference Persistence (`persistence.py`):**
   - Modeled `UiStatePreferences` with `extra="forbid"` to ensure schema integrity.
   - **Extended Schema Version 1:**
     ```json
     {
       "schema_version": 1,
       "theme": "kin-graphite",
       "sidebar_width": 32,
       "inspector_width": 38,
       "sidebar_collapsed": false,
       "sidebar_section_collapse": {},
       "inspector_visible": true,
       "focus_mode_default": false,
       "workspace_tabs": ["home"],
       "active_tab": "home"
     }
     ```
   - Location: `<profile_dir>/ui-state.json` (`Path.home() / ".kin" / "profiles" / profile_name`).
   - Atomic writes implemented via temporary file `ui-state.json.tmp` followed by atomic `replace`.
   - Clamping out-of-range dimensions (`sidebar_width` [24, 42], `inspector_width` [30, 52]) gracefully preserves user settings without resetting valid fields.
   - Malformed JSON or unsupported schema versions safely reset UI preferences to defaults while surfacing exactly one quiet status message.

4. **Keybinding Scope & Priority (`app.py`):**
   - Removed `priority=True` from bare `[` and `]` keybindings.
   - When `#command-input` (or any editable widget) has focus, typing `[` or `]` appends the printable character directly to the input value without triggering sidebar collapse or inspector toggle.
   - Retained `priority=True` on `Alt+[`/`Alt+]`/`Alt+{`/`Alt+}` so geometry resizing works globally regardless of widget focus.

5. **StatusBar `now` Clock & `degraded_reason` Rendering (`shell.py`):**
   - `StatusBar.update_health()` handles injectable clock parameter `now` (accepting `datetime` objects, ISO strings, or defaulting to UTC wall clock) and records `last_updated_at` formatted as `HH:MM:SS`.
   - `StatusBar.render()` explicitly renders `HealthSnapshot.degraded_reason` in `[yellow]({degraded_reason})[/yellow]` when health is degraded.

6. **True Atomic Write Failure Isolation (`test_persistence.py`):**
   - `test_atomic_write_preserves_existing_valid_file_on_crash` uses monkeypatch on `Path.replace` to simulate a disk/file-system failure during atomic swap.
   - Asserts original file content is 100% untouched and still loads cleanly.

---

## 2. Dependency Versions

```text
textual: 8.2.8
rich: 14.3.3
typer: 0.27.0
pytest: 8.4.2
pytest-asyncio: 1.4.0
pytest-textual-snapshot: 1.1.0
syrupy: 4.8.0
```

*(No new dependencies added for T1. All persistence used stdlib `json` and `pathlib` + `pydantic` already present in project dependencies).*

---

## 3. New T1 Test Suite Raw Output (`py -3.11 -m pytest -v tests/tui/`)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 48 items

tests/tui/test_app_shell.py::test_non_tty_launches_one_line_message_and_exits_zero PASSED [  2%]
tests/tui/test_app_shell.py::test_tty_detection_positive PASSED          [  4%]
tests/tui/test_app_shell.py::test_app_normal_quit PASSED                 [  6%]
tests/tui/test_app_shell.py::test_app_ctrl_c_quit PASSED                 [  8%]
tests/tui/test_app_shell.py::test_terminal_restoration_on_injected_exception PASSED [ 10%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_160x44 PASSED     [ 12%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_120x36 PASSED     [ 14%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_90x28 PASSED      [ 16%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_80x24 PASSED      [ 18%]
tests/tui/test_error_boundary.py::test_exception_conversion_to_recoverable_error PASSED [ 20%]
tests/tui/test_error_boundary.py::test_tui_error_boundary_catches_exception_without_crashing PASSED [ 22%]
tests/tui/test_layout.py::test_classify_breakpoint_exhaustive_boundaries PASSED [ 25%]
tests/tui/test_layout.py::test_explicit_80x24_minimal_checkpoint_bar PASSED [ 27%]
tests/tui/test_layout.py::test_sidebar_width_clamping PASSED             [ 29%]
tests/tui/test_layout.py::test_inspector_width_clamping PASSED           [ 31%]
tests/tui/test_persistence.py::test_valid_file_roundtrips_correctly PASSED [ 33%]
tests/tui/test_persistence.py::test_malformed_json_resets_ui_preferences_safely PASSED [ 35%]
tests/tui/test_persistence.py::test_unknown_schema_version_resets_ui_preferences_safely PASSED [ 37%]
tests/tui/test_persistence.py::test_missing_file_creates_defaults_atomically PASSED [ 39%]
tests/tui/test_persistence.py::test_out_of_range_values_are_clamped_to_valid_bounds PASSED [ 41%]
tests/tui/test_persistence.py::test_compatible_upgrade_loads_missing_fields_with_defaults PASSED [ 43%]
tests/tui/test_persistence.py::test_atomic_write_preserves_existing_valid_file_on_crash PASSED [ 45%]
tests/tui/test_shell_geometry.py::test_stable_region_widget_ids_mounted PASSED [ 47%]
tests/tui/test_shell_geometry.py::test_keyboard_sidebar_resize_and_clamping PASSED [ 50%]
tests/tui/test_shell_geometry.py::test_keyboard_inspector_resize_and_clamping PASSED [ 52%]
tests/tui/test_shell_geometry.py::test_keyboard_toggle_sidebar_and_inspector PASSED [ 54%]
tests/tui/test_shell_geometry.py::test_dock_non_overlap_safety_guarantee PASSED [ 56%]
tests/tui/test_shell_geometry.py::test_100_health_updates_focus_and_cursor_stability PASSED [ 58%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_160x44 PASSED [ 60%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_120x36 PASSED [ 62%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_90x28 PASSED [ 64%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_80x24 PASSED [ 66%]
tests/tui/test_shell_geometry.py::test_degraded_health_snapshot_160x44 PASSED [ 68%]
tests/tui/test_shell_geometry.py::test_long_profile_name_snapshot_120x36 PASSED [ 70%]
tests/tui/test_state_fixtures.py::test_session_summary_factories_cover_all_16_statuses PASSED [ 72%]
tests/tui/test_state_fixtures.py::test_agent_card_view_factories_cover_all_8_availabilities PASSED [ 75%]
tests/tui/test_state_fixtures.py::test_approval_view_factories_cover_risk_labels_and_decisions PASSED [ 77%]
tests/tui/test_state_fixtures.py::test_approval_view_injectable_clock_determinism PASSED [ 79%]
tests/tui/test_state_fixtures.py::test_artifact_view_factory_mime_variants PASSED [ 81%]
tests/tui/test_state_fixtures.py::test_recoverable_error_factories PASSED [ 83%]
tests/tui/test_state_fixtures.py::test_default_uistate_fixture_construction PASSED [ 85%]
tests/tui/test_state_fixtures.py::test_peer_agent_card_view_security_isolation PASSED [ 87%]
tests/tui/test_state_fixtures.py::test_exhaustive_presentation_class_mapping_purity PASSED [ 89%]
tests/tui/test_tokens.py::test_every_required_role_resolves_under_kin_graphite PASSED [ 91%]
tests/tui/test_tokens.py::test_missing_role_theme_is_rejected_by_validator PASSED [ 93%]
tests/tui/test_tokens.py::test_unimplemented_theme_name_falls_back_to_kin_graphite PASSED [ 95%]
tests/tui/test_tokens.py::test_widget_role_consumption_validator PASSED  [ 97%]
tests/tui/test_tokens.py::test_glyph_registry_ascii_fallbacks PASSED     [100%]

--------------------------- snapshot report summary ---------------------------
10 snapshots passed.
============================= 48 passed in 10.59s =============================
```

---

## 4. Full Combined Test Suite Raw Output (`py -3.11 -m pytest`)

```text
[2026-07-27 00:25:14,786] WARNING in core: flasgger is not installed; serving the static landing page at / and skipping the Swagger UI and /spec.json.
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 341 items / 1 deselected / 340 selected

tests\test_adapter_output_redaction.py ....                              [  1%]
tests\test_adapters_contract.py ...                                      [  2%]
tests\test_agent_projection.py ..                                        [  2%]
tests\test_agent_registry.py ............                                [  6%]
tests\test_agent_roster.py ................                              [ 10%]
tests\test_artifacts_vault.py ........                                   [ 13%]
tests\test_audit.py ..                                                   [ 13%]
tests\test_cli_agent.py .....                                            [ 15%]
tests\test_cli_ask.py ............................                       [ 23%]
tests\test_cli_pair.py ..........                                        [ 26%]
tests\test_cli_relay_fallback.py .....                                   [ 27%]
tests\test_compatibility.py ....                                         [ 29%]
tests\test_export.py ....                                                [ 30%]
tests\test_fingerprint.py ...                                            [ 31%]
tests\test_harness_isolation.py ....                                     [ 32%]
tests\test_keyring_isolation.py ..                                       [ 32%]
tests\test_keys.py .............                                         [ 36%]
tests\test_local_command_security.py ...                                 [ 37%]
tests\test_migrations.py ...........                                     [ 40%]
tests\test_orchestrator_e2e.py ......                                    [ 42%]
tests\test_orchestrator_event_ordering.py .                              [ 42%]
tests\test_policy_evaluator.py .........                                 [ 45%]
tests\test_schemas.py ...............                                    [ 50%]
tests\test_session_recovery.py ..                                        [ 50%]
tests\test_session_reducer.py .......................................... [ 62%]
............................                                             [ 71%]
tests\test_setup.py ...                                                  [ 72%]
tests\test_storage.py .                                                  [ 72%]
tests\test_storage_keychain.py ............                              [ 75%]
tests\test_v11_transport_m3.py .................................         [ 85%]
tests\test_vault.py .                                                    [ 85%]
tests\tui\test_app_shell.py .........                                    [ 88%]
tests\tui\test_error_boundary.py ..                                      [ 89%]
tests\tui\test_layout.py ....                                            [ 90%]
tests\tui\test_persistence.py .......                                    [ 92%]
tests\tui\test_shell_geometry.py ............                            [ 95%]
tests\tui\test_state_fixtures.py .........                               [ 98%]
tests\tui\test_tokens.py .....                                           [100%]

============================== warnings summary ===============================
C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\deban\AppData\Local\Programs\Python\Python311\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
--------------------------- snapshot report summary ---------------------------
10 snapshots passed.
================ 340 passed, 1 deselected, 1 warning in 36.38s ================
```

---

## 5. Files Modified List

```text
kin-node/kin/tui/layout.py
kin-node/kin/tui/persistence.py
kin-node/kin/tui/shell.py
kin-node/kin/tui/app.py
kin-node/tests/tui/test_layout.py
kin-node/tests/tui/test_persistence.py
kin-node/tests/tui/test_shell_geometry.py
kin-node/tui_t1_progress.md
```

*(No pre-existing file outside `kin/tui/` and `tests/tui/` was modified).*

---

## 6. Known Limitations & Deferred Items

1. **Tab Switching & Closing Rules (Deferred to T2):** `WorkspaceTabBar` renders static tab titles from preferences (`"home"`). Tab lifecycle management, dirty draft indicators, and singleton tab rules arrive in T2 (§14.4).
2. **Sidebar Tree Interaction & Filtering (Deferred to T2/T3):** `Sidebar` renders static sections/items. Tree navigation, filtering, and `j/k` vim keys arrive in T2/T3.
3. **Reusable Widget Library (Deferred to T3):** Panels, Badges, Spinners, and Mouse Splitters are deferred to T3 (§14.5).
4. **Live Node / Session Integration (Deferred to T8):** Shell renders view models from T0 fixtures. Real node integration arrives in T8.

---

## 7. Checkpoint T1 Stop/Handoff Bar Verification

> **Checkpoint T1 bar:** *"shell geography is stable from 80x24 through wide screens, preferences persist safely, and asynchronous health cannot disrupt a user."*

- **Status:** **PASSED GREEN**
- **Evidence:**
  1. The five persistent regions (`WorkspaceTabBar`, `Sidebar`, `MainCanvas`, `Inspector`, `StatusBar`) maintain stable IDs `#workspace-tab-bar`, `#sidebar`, `#main-canvas`, `#inspector`, `#status-bar` and remain mounted across all breakpoint transitions.
  2. Terminal geometry is classified deterministically (`wide` >=160x44, `standard` 120x36, `compact` 90x28, `minimal` 80x24).
  3. `ui-state.json` preferences persist atomically, handle malformed/unknown schemas safely, and clamp out-of-range bounds without losing user preferences.
  4. Injecting 100 sequential `HealthSnapshot` updates into the status bar leaves active input focus, cursor position, scroll position, and selection 100% untouched.
