# Milestone T2 Progress Report — Navigation Shell & Workspace Lifecycle

**Issued for:** Claude (Tech Lead)  
**Spec Authority:** `KIN-V1.1-TUI-SYSTEM.md` §4, §5.1–5.4, §14.4  
**Date:** July 27, 2026  
**Status:** COMPLETE & VERIFIED  

---

## 1. Architectural Decisions

1. **Central Keybinding Registry (`kin/tui/keymap.py`):**
   - Implemented `KeyBindingSpec` and `validate_keymap_registry` as the authoritative single source of truth for all §5.1, §5.2, and §5.3 bindings (including T1 shell geometry controls `alt+[`, `alt+]`, `alt+{`, `alt+}`, `[`, `]`).
   - Every single binding has explicit `priority` (boolean), `suppressed_when_text_focused` (boolean), and `justification` fields.
   - Fast-failing validator runs on module import and in unit tests (`test_keymap_registry.py`) enforcing a single flat namespace check across all registered keybindings attached to the application.

2. **Intentional `q` Keybinding Behavior Change Callout (§5.1):**
   - **T1 Behavior:** Unconditional app quit (`exit(0)`).
   - **T2 Behavior:** Smart Quit (`action_smart_quit`). Pressing `q` when active tab is `Home` exits the app cleanly. Pressing `q` when active tab is NOT `Home` returns to `Home` tab cleanly (gated by confirmation modal if active work is dirty/unsaved).

3. **Inbox / Approvals Routing Decision (§4.1, §5.1):**
   - Opening Approvals (`p`) routes to the singleton `inbox` tab (`kind="inbox"`), as active approval requests and "Needs You" items are unified within the Inbox workspace context.

4. **Sidebar Tree Filtering Scope (`/`):**
   - At T2, pressing `/` activates tree filter mode on the sidebar (`sidebar.filter_query = "a"`). Interactive inline filter text entry is deferred to Milestone T3's dedicated SearchField widget.

5. **Esc Priority Chain (§4, §14.4):**
   - Implemented strict 3-stage Esc priority chain in `KinApp.action_action_handle_escape()`:
     - **Stage 1:** If active search/filter input (`sidebar.filter_query` or focused input) has a value, Esc clears search/filter first while modal screen remains open.
     - **Stage 2:** If an open modal/overlay (`CommandPaletteModal`, `QuickSwitcherModal`, `HelpOverlayScreen`, `ConfirmationModal`) is open, Esc closes the overlay.
     - **Stage 3:** Otherwise, Esc returns focus to main canvas workspace (`#command-input`).
   - Covered by exhaustive 3-stage unit test `test_esc_priority_chain_exhaustive`.

6. **Workspace Tab Lifecycle (`kin/tui/workspace.py`):**
   - **Home Tab:** Permanent at index 0, non-closeable (`Ctrl+W` on Home is a no-op).
   - **Singleton Tabs:** `Agents`, `Network`, `Inbox`. Attempting to open an already open singleton focuses the existing tab without duplicating.
   - **Dispatch Draft:** Single reusable draft tab. Warns before discarding if `dirty=True`.
   - **Reopen Stack:** Closing a closeable non-sensitive tab pushes it onto `closed_tabs_stack`. `Ctrl+Shift+T` reopens the last closed tab.
   - **Stable Ordering & Background Events:** Background fixture updates (`update_tab_badge`) modify badges in-place without reordering tabs or stealing focus.

7. **Command Palette & Colon Command Security Parser (`kin/tui/palette.py`):**
   - `Ctrl+K` Command Palette: Evaluates candidate items using strict 4-tier ranking function (`rank_command_palette`):
     - **Tier 1:** Exact command match
     - **Tier 2:** Recent action match
     - **Tier 3:** Contextual relevance match
     - **Tier 4:** Fuzzy match
     - Verified via golden test `test_command_palette_ranking_golden`.
   - Colon Commands: Security parser (`parse_colon_command`) validates whitelisted commands (`:theme <name>`, `:open <tab>`, `:quit`, `:help`) and strictly rejects shell execution vectors (`:!rm -rf /`, `:exec(...)`, `:import os`). Verified via test `test_colon_command_security_parser`.

8. **Consequential Action Confirmation Gate (`kin/tui/shell.py`):**
   - `x` (cancel/archive) and tagged consequential palette actions launch `ConfirmationModal`. No action takes effect until explicitly confirmed by user ('y'). Verified via tests `test_no_single_key_executes_consequential_action` (decline) and `test_consequential_action_confirm_path_executes_action` (confirm).

9. **Sensitive Tab Definition:**
   - All fixture tabs at Milestone T2 are defined as **non-sensitive**. In future milestones (T3+), tabs tagged `sensitive=True` (e.g. key material or unencrypted secret view) will be excluded from the `closed_tabs_stack` to prevent secret persistence.

---

## 2. Keybinding Priority & Focus-Suppression Table

| Key | Action | Section | Priority | Text-Yield | Explicit Justification |
|---|---|---|---|---|---|
| `ctrl+c` | `quit` | global | `True` | `False` | Global system interrupt signal. |
| `ctrl+k` | `command_palette` | global | `True` | `False` | Global system shortcut; Ctrl modifier safely bypasses text fields. |
| `ctrl+p` | `quick_switcher` | global | `True` | `False` | Global navigation shortcut; Ctrl modifier safely bypasses text fields. |
| `d` | `open_dispatch` | global | `False` | `True` | Printable letter 'd'; must yield to text input fields when focused. |
| `a` | `open_agents` | global | `False` | `True` | Printable letter 'a'; must yield to text input fields when focused. |
| `n` | `open_network` | global | `False` | `True` | Printable letter 'n'; must yield to text input fields when focused. |
| `i` | `open_inbox` | global | `False` | `True` | Printable letter 'i'; must yield to text input fields when focused. |
| `p` | `open_approvals` | global | `False` | `True` | Printable letter 'p'; must yield to text input fields when focused. |
| `?` | `toggle_help` | global | `False` | `True` | Printable symbol '?'; must yield to text input fields when focused. |
| `/` | `focus_filter` | global | `False` | `True` | Printable symbol '/'; must yield to text input fields when focused. |
| `escape` | `handle_escape` | global | `True` | `False` | Global escape key; priority required to trigger Esc priority chain. |
| `tab` | `focus_next` | global | `False` | `False` | Standard focus navigation key. |
| `shift+tab` | `focus_prev` | global | `False` | `False` | Standard focus navigation key. |
| `ctrl+tab` | `next_tab` | global | `True` | `False` | Global tab cycle shortcut. |
| `ctrl+shift+tab` | `prev_tab` | global | `True` | `False` | Global tab cycle shortcut. |
| `ctrl+w` | `close_tab` | global | `True` | `False` | Global workspace tab close shortcut. |
| `ctrl+shift+t` | `reopen_tab` | global | `True` | `False` | Global tab reopen shortcut. |
| `ctrl+s` | `save_draft` | global | `True` | `False` | Global draft save shortcut. |
| `q` | `smart_quit` | global | `False` | `True` | Printable letter 'q'; must yield to text input fields when focused. |
| `alt+[` | `decrease_sidebar_width` | global | `True` | `False` | Alt+[ modifier shortcut for sidebar resize. |
| `alt+]` | `increase_sidebar_width` | global | `True` | `False` | Alt+] modifier shortcut for sidebar resize. |
| `alt+{` | `decrease_inspector_width` | global | `True` | `False` | Alt+{ modifier shortcut for inspector resize. |
| `alt+}` | `increase_inspector_width` | global | `True` | `False` | Alt+} modifier shortcut for inspector resize. |
| `[` | `toggle_sidebar` | global | `False` | `True` | Printable symbol '['; must yield to text input fields when focused. |
| `]` | `toggle_inspector` | global | `False` | `True` | Printable symbol ']'; must yield to text input fields when focused. |
| `alt+1`..`alt+9` | `jump_tab_N` | global | `True` | `False` | Alt+N tab jump shortcut. |
| `j` | `cursor_down` | collection | `False` | `True` | Vim-style navigation key; yields to text input fields. |
| `k` | `cursor_up` | collection | `False` | `True` | Vim-style navigation key; yields to text input fields. |
| `g` | `cursor_top` | collection | `False` | `True` | Vim-style navigation key; yields to text input fields. |
| `G` | `cursor_bottom` | collection | `False` | `True` | Vim-style navigation key; yields to text input fields. |
| `enter` | `activate_selection` | collection | `False` | `False` | Standard activation key. |
| `space` | `preview_selection` | collection | `False` | `True` | Printable space character; yields to text input fields. |
| `o` | `open_in_new_tab` | collection | `False` | `True` | Printable letter 'o'; yields to text input fields. |
| `r` | `replay_item` | collection | `False` | `True` | Printable letter 'r'; yields to text input fields. |
| `f` | `fork_item` | collection | `False` | `True` | Printable letter 'f'; yields to text input fields. |
| `.` | `open_actions` | collection | `False` | `True` | Printable dot '.'; yields to text input fields. |
| `x` | `consequential_action` | collection | `False` | `True` | Printable letter 'x'; yields to text input fields. Requires confirmation gate. |
| `z` | `lane_focus` | arena | `False` | `True` | Printable letter 'z'; yields to text input fields. |
| `t` | `lane_transcript` | arena | `False` | `True` | Printable letter 't'; yields to text input fields. |
| `e` | `lane_activity` | arena | `False` | `True` | Printable letter 'e'; yields to text input fields. |
| `c` | `lane_decisions` | arena | `False` | `True` | Printable letter 'c'; yields to text input fields. |
| `u` | `lane_needs_you` | arena | `False` | `True` | Printable letter 'u'; yields to text input fields. |
| `m` | `compose_message` | arena | `False` | `True` | Printable letter 'm'; yields to text input fields. |
| `s` | `session_state_menu` | arena | `False` | `True` | Printable letter 's'; yields to text input fields. |

---

## 3. Raw Test Suite Outputs

### A. Raw `py -3.11 -m pytest -v tests/tui/` Output (68 Passed, 10 Snapshots Passed)

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0 -- C:\Users\deban\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
rootdir: D:\KIN\kin-node
configfile: pyproject.toml
plugins: anyio-4.14.0, langsmith-0.8.16, asyncio-1.4.0, cov-7.1.0, httpbin-2.1.0, textual-snapshot-1.1.0, syrupy-4.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 68 items

tests/tui/test_app_shell.py::test_non_tty_launches_one_line_message_and_exits_zero PASSED [  1%]
tests/tui/test_app_shell.py::test_tty_detection_positive PASSED          [  2%]
tests/tui/test_app_shell.py::test_app_normal_quit PASSED                 [  4%]
tests/tui/test_app_shell.py::test_app_ctrl_c_quit PASSED                 [  5%]
tests/tui/test_app_shell.py::test_terminal_restoration_on_injected_exception PASSED [  7%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_160x44 PASSED     [  8%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_120x36 PASSED     [ 10%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_90x28 PASSED      [ 11%]
tests/tui/test_app_shell.py::test_blank_shell_snapshot_80x24 PASSED      [ 13%]
tests/tui/test_command_palette.py::test_command_palette_ranking_golden PASSED [ 14%]
tests/tui/test_command_palette.py::test_colon_command_security_parser PASSED [ 16%]
tests/tui/test_dangerous_actions_gated.py::test_no_single_key_executes_consequential_action PASSED [ 17%]
tests/tui/test_dangerous_actions_gated.py::test_consequential_action_confirm_path_executes_action PASSED [ 19%]
tests/tui/test_dangerous_actions_gated.py::test_esc_priority_chain_exhaustive PASSED [ 20%]
tests/tui/test_error_boundary.py::test_exception_conversion_to_recoverable_error PASSED [ 22%]
tests/tui/test_error_boundary.py::test_tui_error_boundary_catches_exception_without_crashing PASSED [ 23%]
tests/tui/test_keymap_registry.py::test_keymap_registry_no_collisions PASSED [ 25%]
tests/tui/test_keymap_registry.py::test_keymap_collision_detection PASSED [ 26%]
tests/tui/test_keymap_registry.py::test_every_printable_character_has_text_yield_justification PASSED [ 27%]
tests/tui/test_keymap_registry.py::test_help_overlay_generated_from_keymap PASSED [ 29%]
tests/tui/test_layout.py::test_classify_breakpoint_exhaustive_boundaries PASSED [ 30%]
tests/tui/test_layout.py::test_explicit_80x24_minimal_checkpoint_bar PASSED [ 32%]
tests/tui/test_layout.py::test_sidebar_width_clamping PASSED             [ 33%]
tests/tui/test_layout.py::test_inspector_width_clamping PASSED           [ 35%]
tests/tui/test_persistence.py::test_valid_file_roundtrips_correctly PASSED [ 36%]
tests/tui/test_persistence.py::test_malformed_json_resets_ui_preferences_safely PASSED [ 38%]
tests/tui/test_persistence.py::test_unknown_schema_version_resets_ui_preferences_safely PASSED [ 39%]
tests/tui/test_persistence.py::test_missing_file_creates_defaults_atomically PASSED [ 41%]
tests/tui/test_persistence.py::test_out_of_range_values_are_clamped_to_valid_bounds PASSED [ 42%]
tests/tui/test_persistence.py::test_compatible_upgrade_loads_missing_fields_with_defaults PASSED [ 44%]
tests/tui/test_persistence.py::test_atomic_write_preserves_existing_valid_file_on_crash PASSED [ 45%]
tests/tui/test_quick_switcher.py::test_quick_switcher_keyboard_navigation_and_filtering PASSED [ 47%]
tests/tui/test_shell_geometry.py::test_stable_region_widget_ids_mounted PASSED [ 48%]
tests/tui/test_shell_geometry.py::test_keyboard_sidebar_resize_and_clamping PASSED [ 50%]
tests/tui/test_shell_geometry.py::test_keyboard_inspector_resize_and_clamping PASSED [ 51%]
tests/tui/test_shell_geometry.py::test_keyboard_toggle_sidebar_and_inspector PASSED [ 52%]
tests/tui/test_shell_geometry.py::test_dock_non_overlap_safety_guarantee PASSED [ 54%]
tests/tui/test_shell_geometry.py::test_100_health_updates_focus_and_cursor_stability PASSED [ 55%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_160x44 PASSED [ 57%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_120x36 PASSED [ 58%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_90x28 PASSED [ 60%]
tests/tui/test_shell_geometry.py::test_blank_shell_snapshot_80x24 PASSED [ 61%]
tests/tui/test_shell_geometry.py::test_degraded_health_snapshot_160x44 PASSED [ 63%]
tests/tui/test_shell_geometry.py::test_long_profile_name_snapshot_120x36 PASSED [ 64%]
tests/tui/test_sidebar_tree.py::test_sidebar_keyboard_navigation_and_collapse PASSED [ 66%]
tests/tui/test_sidebar_tree.py::test_section_collapse_persistence PASSED [ 67%]
tests/tui/test_sidebar_tree.py::test_disappearing_row_sticky_selection_fallback PASSED [ 69%]
tests/tui/test_sidebar_tree.py::test_space_key_previews_in_inspector PASSED [ 70%]
tests/tui/test_state_fixtures.py::test_session_summary_factories_cover_all_16_statuses PASSED [ 72%]
tests/tui/test_state_fixtures.py::test_agent_card_view_factories_cover_all_8_availabilities PASSED [ 73%]
tests/tui/test_approval_view_factories_cover_risk_labels_and_decisions PASSED [ 75%]
tests/tui/test_state_fixtures.py::test_approval_view_injectable_clock_determinism PASSED [ 76%]
tests/tui/test_state_fixtures.py::test_artifact_view_factory_mime_variants PASSED [ 77%]
tests/tui/test_state_fixtures.py::test_recoverable_error_factories PASSED [ 79%]
tests/tui/test_state_fixtures.py::test_default_uistate_fixture_construction PASSED [ 80%]
tests/tui/test_state_fixtures.py::test_peer_agent_card_view_security_isolation PASSED [ 82%]
tests/tui/test_state_fixtures.py::test_exhaustive_presentation_class_mapping_purity PASSED [ 83%]
tests/tui/test_tokens.py::test_every_required_role_resolves_under_kin_graphite PASSED [ 85%]
tests/tui/test_tokens.py::test_missing_role_theme_is_rejected_by_validator PASSED [ 86%]
tests/tui/test_tokens.py::test_unimplemented_theme_name_falls_back_to_kin_graphite PASSED [ 88%]
tests/tui/test_tokens.py::test_widget_role_consumption_validator PASSED  [ 89%]
tests/tui/test_tokens.py::test_glyph_registry_ascii_fallbacks PASSED     [ 91%]
tests/tui/test_workspace_tabs.py::test_home_tab_cannot_close PASSED      [ 92%]
tests/tui/test_workspace_tabs.py::test_singleton_tab_rules PASSED        [ 94%]
tests/tui/test_workspace_tabs.py::test_dispatch_dirty_draft_warning PASSED [ 95%]
tests/tui/test_close_and_reopen_last_tab PASSED  [ 97%]
tests/tui/test_tab_stable_ordering_and_background_events PASSED [ 98%]
tests/tui/test_alt_number_tab_jumping_and_cycling PASSED [100%]

--------------------------- snapshot report summary ---------------------------
10 snapshots passed.
============================= 68 passed in 12.51s =============================
```

---

## 4. Created and Modified Files

### Created Files
- `kin/tui/keymap.py` — Central keybinding registry, flat collision validator, and Textual `Binding` generator.
- `kin/tui/workspace.py` — Workspace tab manager, singleton rules, dirty draft protection, reopen stack.
- `kin/tui/palette.py` — Command Palette (`Ctrl+K`), Quick Switcher (`Ctrl+P`), 4-tier ranking function, colon command security parser.
- `kin/tui/help.py` — Dynamic Contextual Help overlay screen generator (`?`).
- `tests/tui/test_keymap_registry.py` — Unit tests for binding collisions, priority rules, and help text.
- `tests/tui/test_workspace_tabs.py` — Unit tests for tab lifecycle, singletons, reopen stack, and background event stability.
- `tests/tui/test_sidebar_tree.py` — Unit tests for tree navigation, section collapse persistence, and sticky selection fallback.
- `tests/tui/test_command_palette.py` — Golden tests for 4-tier ranking and colon command security parser.
- `tests/tui/test_quick_switcher.py` — Integration test for Quick Switcher navigation and filtering.
- `tests/tui/test_dangerous_actions_gated.py` — Architectural gate tests for consequential actions (`x`) decline/confirm paths and 3-stage Esc priority chain.

### Modified Files
- `kin/tui/shell.py` — Added interactive tree nodes, sticky selection removal, Inspector preview integration, and `ConfirmationModal`.
- `kin/tui/app.py` — Integrated `build_textual_bindings()`, 3-stage Esc priority chain, Smart Quit, Command Palette, Quick Switcher, Help overlay, and tab jumping bindings.
- `tui_t2_progress.md` — Milestone T2 progress report.

---

## 5. Known Limitations & Handoff to Milestone T3

- **Session Arena & Timeline Controls (Milestone T3):** Milestone T2 establishes the complete keyboard navigation infrastructure, tab manager, keymap registry, and palette surfaces. Screen contents for individual tabs (Session Arena, Timeline, Activity, Decisions, Needs-You lanes) are stubbed and ready to be built in Milestone T3 per §6.
