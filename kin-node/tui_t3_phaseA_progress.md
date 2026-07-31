# Milestone T3 Phase A Progress Report — Foundation Widgets & Shared Lifecycle Contract

**Issued for:** Claude (Tech Lead)  
**Spec Authority:** `KIN-V1.1-TUI-SYSTEM.md` §14.5 (build steps 1, 4)  
**Date:** July 27, 2026  
**Status:** COMPLETE & VERIFIED  

---

## 1. Architectural & Engineering Decisions

1. **Shared 7-State Lifecycle State Contract (`kin/tui/widgets/lifecycle.py`):**
   - Implemented `WidgetLifecycleState` Enum (`LOADING`, `EMPTY`, `NORMAL`, `FOCUSED`, `DISABLED`, `RECOVERABLE_ERROR`, `NARROW`) and `LifecycleWidgetMixin` base mixin.
   - All 8 foundation widgets inherit from `LifecycleWidgetMixin` and validate parameter requirements on state changes.
   - **Disabled Reason Enforcement (§14.5):** Setting `WidgetLifecycleState.DISABLED` strictly requires an explicit, non-empty `disabled_reason: str` parameter. Attempting to set `DISABLED` state with empty/missing reason raises a fast-failing `ValueError`.

2. **Single Source of Truth for Breakpoint Classification (`layout.py` Integration):**
   - The `NARROW` lifecycle state connects directly to `layout.py`'s `classify_breakpoint()` function (`is_narrow_breakpoint()` returns `True` for `compact` and `minimal` breakpoint tiers), eliminating layout classification drift across widgets.

3. **Injectable Clock Discipline (`StatusLineWidget` & `SpinnerWidget`):**
   - Both `StatusLineWidget` and `SpinnerWidget` (along with `LifecycleWidgetMixin`) take an injectable `now` clock parameter (`datetime`, ISO string, or float timestamp, defaulting to UTC when omitted) for deterministic time formatting and elapsed calculations without relying on wall-clock time directly.

4. **Theme Contract Scoping Decision:**
   - As established in the plan, parametrized contract loops run against `kin-graphite` as the primary active theme. Since Milestone T0 certified that theme resolution fallbacks are enforced universally at the design-token layer (`tokens.py`), running per-widget snapshot/contract loops against `kin-graphite` fully validates token consumption without redundant theme re-testing.

5. **`ConfirmationModal` Refactoring Decision & Regression Verification:**
   - Existing `ConfirmationModal` in `kin/tui/shell.py` was refactored to extend `kin.tui.widgets.modal.ModalScreenWidget`.
   - **Regression Check:** `test_no_single_key_executes_consequential_action`, `test_consequential_action_confirm_path_executes_action`, and `test_esc_priority_chain_exhaustive` in `tests/tui/test_dangerous_actions_gated.py` were re-run post-refactor and confirmed **100% GREEN**.

6. **Keybinding Generator Maintainability (`build_textual_bindings`):**
   - The method string matching logic in `build_textual_bindings()` (`kin/tui/keymap.py`) maps standard action strings directly to Textual action handlers (`action_<name>`) while preserving builtin Textual actions (`quit`, geometry controls), ensuring zero hardcoded tuple clutter.

---

## 2. 8-Widget × 7-State Complete Coverage Matrix

Every single cell in the matrix below represents a parametrized test case executed and verified in `tests/tui/widgets/test_lifecycle_contract.py`:

| Widget | LOADING | EMPTY | NORMAL | FOCUSED | DISABLED | RECOVERABLE_ERROR | NARROW |
|---|---|---|---|---|---|---|---|
| **PanelWidget** | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |
| **BadgeWidget** | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Error Verified | ✅ Derived `layout.py` |
| **StatusLineWidget** | ✅ Clock Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |
| **SpinnerWidget** | ✅ Clock Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |
| **ProgressBarWidget** | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |
| **ToastWidget** | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |
| **ModalWidget** | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |
| **EmptyStateWidget** | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Verified | ✅ Reason Verified | ✅ Retry Verified | ✅ Derived `layout.py` |

---

## 3. Raw Test Suite Outputs

### A. T2 Modal Refactoring Regression Verification (`tests/tui/test_dangerous_actions_gated.py`)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 3 items

tests/tui/test_dangerous_actions_gated.py::test_no_single_key_executes_consequential_action PASSED [ 33%]
tests/tui/test_dangerous_actions_gated.py::test_consequential_action_confirm_path_executes_action PASSED [ 66%]
tests/tui/test_dangerous_actions_gated.py::test_esc_priority_chain_exhaustive PASSED [100%]

============================== 3 passed in 0.96s ==============================
```

### B. Widget Lifecycle Contract & Unit Test Suite (`tests/tui/widgets/`)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 241 items

tests/tui/widgets/test_badge.py::test_badge_widget_role_consumption PASSED [  0%]
tests/tui/widgets/test_badge.py::test_badge_widget_disabled_with_reason PASSED [  0%]
tests/tui/widgets/test_empty_state.py::test_empty_state_action_callback PASSED [  1%]
tests/tui/widgets/test_empty_state.py::test_empty_state_disabled_with_reason PASSED [  1%]
tests/tui/widgets/test_lifecycle_contract.py::test_widget_lifecycle_contract[wide-loading-PanelWidget-<lambda>] PASSED [  2%]
... (224 parametrized contract tests covering 8 widgets x 7 states x 4 breakpoints) ...
tests/tui/widgets/test_lifecycle_contract.py::test_disabled_state_raises_without_reason PASSED [ 96%]
tests/tui/widgets/test_modal.py::test_modal_widget_rendering PASSED      [ 96%]
tests/tui/widgets/test_modal.py::test_modal_widget_disabled_with_reason PASSED [ 96%]
tests/tui/widgets/test_panel.py::test_panel_widget_normal_rendering PASSED [ 97%]
tests/tui/widgets/test_panel.py::test_panel_widget_disabled_with_reason PASSED [ 97%]
tests/tui/widgets/test_progress_bar.py::test_progress_bar_rendering_and_updates PASSED [ 97%]
tests/tui/widgets/test_progress_bar.py::test_progress_bar_disabled_with_reason PASSED [ 98%]
tests/tui/widgets/test_spinner.py::test_spinner_cancellation_callback PASSED [ 98%]
tests/tui/widgets/test_spinner.py::test_spinner_injectable_clock_and_disabled_reason PASSED [ 98%]
tests/tui/widgets/test_status_line.py::test_status_line_injectable_clock PASSED [ 99%]
tests/tui/widgets/test_status_line.py::test_status_line_disabled_with_reason PASSED [ 99%]
tests/tui/widgets/test_toast.py::test_toast_severities_and_dismiss PASSED [ 99%]
tests/tui/widgets/test_toast.py::test_toast_disabled_with_reason PASSED  [100%]

============================ 241 passed in 1.04s =============================
```

### C. Full Combined Test Suite Output (`py -3.11 -m pytest`)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 612 items / 1 deselected / 611 selected

tests\test_adapter_output_redaction.py ....                              [  0%]
tests\test_adapters_contract.py ...                                      [  1%]
tests\test_agent_projection.py ..                                        [  1%]
tests\test_agent_registry.py ............                                [  3%]
tests\test_agent_roster.py ................                              [  6%]
tests\test_artifact_transfer.py .........                                [  7%]
tests\test_artifacts_vault.py .........                                  [  9%]
tests\test_audit.py ..                                                   [  9%]
tests\test_cli_agent.py .....                                            [ 10%]
tests\test_cli_ask.py ............................                       [ 14%]
tests\test_cli_pair.py ..........                                        [ 16%]
tests\test_cli_relay_fallback.py .....                                   [ 17%]
tests\test_compatibility.py ....                                         [ 17%]
tests\test_export.py ....                                                [ 18%]
tests\test_fingerprint.py ...                                            [ 18%]
tests\test_harness_isolation.py ....                                     [ 19%]
tests\test_keyring_isolation.py ..                                       [ 19%]
tests\test_keys.py .............                                         [ 22%]
tests\test_local_command_security.py ...                                 [ 22%]
tests\test_migrations.py ...........                                     [ 24%]
tests\test_orchestrator_e2e.py ......                                    [ 25%]
tests\test_orchestrator_event_ordering.py .                              [ 25%]
tests\test_policy_evaluator.py .........                                 [ 27%]
tests\test_schemas.py ...............                                    [ 29%]
tests\test_session_recovery.py ..                                        [ 29%]
tests\test_session_reducer.py .......................................... [ 36%]
............................                                             [ 41%]
tests\test_setup.py ...                                                  [ 41%]
tests\test_storage.py .                                                  [ 41%]
tests\test_storage_keychain.py ............                              [ 43%]
tests\test_v11_transport_m3.py .................................         [ 49%]
tests\test_vault.py .                                                    [ 49%]
tests\tui\test_app_shell.py .........                                    [ 50%]
tests\tui\test_command_palette.py ..                                     [ 51%]
tests\tui\test_dangerous_actions_gated.py ...                            [ 51%]
tests\tui\test_error_boundary.py ..                                      [ 52%]
tests\tui\test_keymap_registry.py ....                                   [ 52%]
tests\tui\test_layout.py ....                                            [ 53%]
tests\tui\test_persistence.py .......                                    [ 54%]
tests\tui\test_quick_switcher.py .                                       [ 54%]
tests\tui\test_shell_geometry.py ............                            [ 56%]
tests\tui\test_sidebar_tree.py ....                                      [ 57%]
tests\tui\test_state_fixtures.py .........                               [ 58%]
tests\tui\test_tokens.py .....                                           [ 59%]
tests\tui\test_workspace_tabs.py ......                                  [ 60%]
tests\tui\widgets\test_badge.py ..                                       [ 60%]
tests\tui\widgets\test_empty_state.py ..                                 [ 61%]
tests\tui\widgets\test_lifecycle_contract.py ........................... [ 65%]
........................................................................ [ 77%]
........................................................................ [ 89%]
........................................................................ [ 98%]
tests\tui\widgets\test_modal.py ..                                       [ 98%]
tests\tui\widgets\test_panel.py ..                                       [ 98%]
tests\tui\widgets\test_progress_bar.py ..                                [ 99%]
tests\tui\widgets\test_spinner.py ..                                     [ 99%]
tests\tui\widgets\test_status_line.py ..                                 [ 99%]
tests\tui\widgets\test_toast.py ..                                       [100%]

--------------------------- snapshot report summary ---------------------------
10 snapshots passed.
================ 611 passed, 1 deselected, 1 warning in 56.15s ================
```

---

## 4. Created & Modified Files

### Created Files
- `kin/tui/widgets/__init__.py` — Package exports for all foundation widgets and contract types.
- `kin/tui/widgets/lifecycle.py` — Shared 7-state lifecycle contract, `WidgetLifecycleState` Enum, `LifecycleWidgetMixin`, `is_narrow_breakpoint()`.
- `kin/tui/widgets/panel.py` — `PanelWidget` container foundation widget.
- `kin/tui/widgets/badge.py` — `BadgeWidget` status pill/counter consuming design token roles.
- `kin/tui/widgets/status_line.py` — `StatusLineWidget` 1-line status text with injectable clock.
- `kin/tui/widgets/spinner.py` — `SpinnerWidget` activity spinner with injectable clock and `cancel_callback`.
- `kin/tui/widgets/progress_bar.py` — `ProgressBarWidget` visual progress indicator.
- `kin/tui/widgets/toast.py` — `ToastWidget` transient notification banner with severity roles.
- `kin/tui/widgets/modal.py` — `ModalWidget` & `ModalScreenWidget` foundation modal screen overlay dialog.
- `kin/tui/widgets/empty_state.py` — `EmptyStateWidget` zero-data collection placeholder.
- `tests/tui/widgets/test_lifecycle_contract.py` — Parametrized 7-state $\times$ 4-breakpoint contract test harness.
- `tests/tui/widgets/test_panel.py` — Unit tests for PanelWidget.
- `tests/tui/widgets/test_badge.py` — Unit tests for BadgeWidget.
- `tests/tui/widgets/test_status_line.py` — Unit tests for StatusLineWidget.
- `tests/tui/widgets/test_spinner.py` — Unit tests for SpinnerWidget.
- `tests/tui/widgets/test_progress_bar.py` — Unit tests for ProgressBarWidget.
- `tests/tui/widgets/test_toast.py` — Unit tests for ToastWidget.
- `tests/tui/widgets/test_modal.py` — Unit tests for ModalWidget.
- `tests/tui/widgets/test_empty_state.py` — Unit tests for EmptyStateWidget.

### Modified Files
- `kin/tui/shell.py` — Refactored `ConfirmationModal` to extend `ModalScreenWidget`.
- `tui_t3_phaseA_progress.md` — Milestone T3 Phase A progress report.
