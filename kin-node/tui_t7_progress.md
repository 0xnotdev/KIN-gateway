# KIN V1.1 — T7 Completion Report

**Milestone:** T7 — Motion Timing Limits, Theme System, Colorless MRO Guard, Automatic Reduced Motion, and 80×24 Plain Mode

**Status:** Complete

**Date:** August 5, 2026

## Outcome

T7 is closed against `KIN-V1.1-TUI-SYSTEM.md` §14.9. The application no longer requires width, true color, Unicode, mouse input, or motion to complete a required T7 workflow.

All five build steps are implemented:

1. Six built-in themes, live theme changes, persisted display preferences, and a globally reachable Settings surface.
2. Semantic colorless and ASCII fallbacks with the permanent `_c()` MRO compliance guard.
3. Centralized timing limits for focus, pulses, expand/collapse, spinners, toasts, and modals.
4. Manual and automatic reduced motion, including terminal blur and live event-loop pressure detection.
5. Complete 80×24/plain-mode behavior for Home, Dispatch, agent selection, Inbox, approvals, Session Arena, replay/export, and recovery.

The previously recorded toast/spinner deferral is resolved. Both widgets now have persistent application-owned hosts and real producers. The previously recorded callback-free toast defect is also resolved: a mounted toast hides when its dismissal timer fires even without a callback, without triggering layout reflow.

## Closure Evidence

### Settings is reachable

- `F2` opens Settings from every workspace, including while a text field is focused.
- `Ctrl+K` exposes the same Settings action in the command palette.
- Theme, color depth, ASCII fallback, and reduced motion changes are applied and persisted through `KinApp.set_preference()`.

### Automatic reduced motion is live

- A 250 ms production event-loop probe measures scheduling drift and feeds every sample into `record_latency_sample()`.
- Three consecutive samples above 100 ms activate the CPU-pressure override.
- A healthy sample clears the CPU-pressure override; terminal blur remains an independent override until focus returns.
- The effective state propagates immediately to every mounted motion-aware widget.
- Spinner frames, warning-toast pulses, event-tail pulses, sidebar width interpolation, and section transition timers stop under reduced motion while labels remain visible.
- Manual reduced motion, automatic CPU-pressure reduction, and terminal focus state compose without one source accidentally clearing another.

### 80×24 and plain mode are complete

- Minimal mode replaces nonessential shell chrome with a one-line breadcrumb and keyboard back path.
- Resizing between minimal and larger breakpoints preserves the exact Dispatch widget, focused field, and draft text.
- Required views render ordered, box-free semantic text in minimal or ASCII mode.
- Long agent labels and full capability/boundary details are keyboard-visible without hover.
- Approval details and all approval decisions remain keyboard-accessible.
- Session Arena lanes, replay, recovery guidance, and plain-text export remain available.
- Plain export writes the current redacted semantic view to `exports/latest-view.txt`.
- The mounted 80×24 tests use keyboard interaction only; no flow depends on mouse support.

### Toast and spinner integration is complete

- `KinApp` owns one reusable toast overlay and one reusable activity spinner overlay.
- Inbox publishes real pending-review and approval-result notifications through the toast host.
- Quiet-hours and snooze checks run before the Inbox notification is published.
- Dispatch starts the activity host before worker execution and stops it with completion or failure feedback.
- Hosted animations obey the same effective reduced-motion state as the Session Arena.
- Timed dismissal is paint-only and callback-free mounted toasts are hidden correctly.

## Primary Production Changes

- `kin/tui/app.py`: global Settings and export actions; minimal breadcrumb/back navigation; persistent toast/spinner hosts; live pressure probe; reduced-motion propagation.
- `kin/tui/keymap.py`: global `F2` Settings and `Ctrl+E` semantic export bindings.
- `kin/tui/motion.py`: shared pressure-probe interval, threshold, and hysteresis constants.
- `kin/tui/shell.py` and `kin/tui/widgets/sidebar_tree.py`: reduced-motion-safe transitions.
- `kin/tui/widgets/lifecycle.py`: canonical effective plain/reduced-motion capability helpers.
- `kin/tui/widgets/home_screen.py`, `dispatch_wizard.py`, `agent_picker.py`, `inbox_screen.py`, `approval_card.py`, and `session_arena.py`: ordered semantic minimal/plain renderings and complete keyboard action labels.
- `kin/tui/widgets/exchange_timeline.py`: live application reduced-motion propagation.
- `kin/tui/widgets/spinner.py` and `toast.py`: reusable hosted lifecycle, immediate reduced-motion response, and correct callback-free dismissal.

## Verification

### Addendum — CSS variables, mounted repaint, and modal cap

- `KinApp.get_css_variables()` maps KIN's semantic roles and Textual aliases
  into live CSS variables; `_refresh_theme_ui()` calls
  `refresh_css(animate=False)` and refreshes mounted workspace children.
- The original live-Arena retheming test proved only a direct `render()` call.
  It now captures `KinApp.export_screenshot()` before and after `set_theme()`,
  proving Textual's compositor repaints the already-mounted Session Arena and
  removes the prior theme's accent from the actual screen paint.
- `MODAL_ANIMATION_MAX_MS` is a compatibility alias for the enforced canonical
  `MODAL_TRANSITION_MS_MAX`. The timing contract now asserts that equality and
  the 120 ms maximum explicitly; production modals remain synchronous at 0 ms.

The 80×24 closure matrix uses mounted `KinApp` instances at exactly 80 columns × 24 rows. It verifies the eight named flows, draft/focus preservation during resize, breadcrumb navigation, long-label details, approval decisions, replay/export, recovery ordering, and ASCII-only output.

The motion matrix verifies live event-loop sampling, three-sample pressure hysteresis, independent blur/focus behavior, instant manual preference changes, propagation to mounted Arena/spinner/toast widgets, label retention, and animation recovery.

### Permanent MRO guard correction

The original closeout report named a permanent `_c()` MRO guard before the
package-wide non-shadowing test actually existed. That enforcement now lives
in `tests/tui/test_c_method_mro_compliance.py`. It imports every module under
`kin.tui`, discovers every class defined there that inherits
`LifecycleWidgetMixin`, and rejects any class whose own `__dict__` contains
`_c`.

The negative control restored the exact historical `AgentCardWidget._c`
override from the parent of `489187c` and produced the expected failure naming
`kin.tui.widgets.agent_card.AgentCardWidget`. Removing the temporary override
returned the guard to `1 passed`; the combined MRO/theme compliance run reports
`78 passed`.

Exactly two snapshot references changed, both intentional 80×24 shell snapshots:

- `tests/tui/__snapshots__/test_app_shell/test_blank_shell_snapshot_80x24.svg`
- `tests/tui/__snapshots__/test_shell_geometry/test_blank_shell_snapshot_80x24.svg`

They now include the minimal-mode breadcrumb. The remaining twelve snapshots are unchanged.

### Three consecutive complete TUI runs

```text
Run 1: 14 snapshots passed; 1111 passed in 62.11s
Run 2: 14 snapshots passed; 1111 passed in 61.26s
Run 3: 14 snapshots passed; 1111 passed in 60.77s
```

### Full repository run

```text
14 snapshots passed.
1457 passed, 1 deselected in 109.39s
```

### Diff hygiene

```text
git diff --check
# no errors
```

## Final Checkpoint

T7 satisfies its checkpoint: no required task depends on width, true color, Unicode, mouse input, or motion. There are no deferred T7 implementation gaps remaining.
