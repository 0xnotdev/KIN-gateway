# M7 Slice 1 — Private Notes with Signed Promotion

Date: 2026-08-05
Branch: `codex/m7-slice1-private-notes`
Base: `6e730af test(tui): enforce Phase B artifact hash equality`
Scope: §15.10 build step 1 only. Checkpoints/decisions, replay determinism,
outcome cards, and fresh-authority reruns have not started.

## Owner visibility choice

Private notes are visible only in a dedicated Session Arena **Private Notes —
Local Only** lane (`l`). This makes the privacy boundary explicit and keeps
note objects out of the Exchange Timeline, Activity, Decisions, Outputs,
Needs-You, Inspector, replay, and live polling models. `Ctrl+S` on a session
opens the local note authoring modal; `p` in the Notes lane reviews and promotes
the selected note.

The existing schema member is `InternalEventKind.PRIVATE_NOTE`, not
`MessageKind.PRIVATE_NOTE`. The implementation intentionally preserves that
distinction: the scratch note is internal/local-only; promotion creates a new
wire-valid `MessageKind.QUESTION` through the existing signed message path.

## Implemented boundary

- `create_private_note()` writes through `append_session_event()` with
  `kind=private_note`, `visibility=local_only`, `signature=None`, and no
  sequence or transport call.
- `get_session_events()` excludes `local_only` rows in SQL for both full and
  incremental reads. Notes use a separate `PrivateNoteView` projection.
- Session export now calls the existing `kin.audit.export.export_session()`
  with `include_private_notes=False`. Failure is closed: it never falls back
  to rendering the local Notes lane.
- Promotion reloads the exact encrypted note text and delegates to
  `send_human_message_to_session_action()`. That existing path loads Alice's
  real Ed25519/X25519 keys, signs the canonical envelope, self-ingests it, and
  transports it to Bob.
- Promotion is gated through the shared `ConfirmationModal`. Its body is
  auto-height and visibly contains the complete, markup-escaped note text
  before confirmation.

## Verification evidence

### Private-note and existing export modules

```text
$ python -m pytest tests/tui/test_compose_messaging.py tests/test_export.py -q -s
..........
10 passed in 6.72s
```

### Real dual-profile signature/decryption proof

```text
$ python -m pytest tests/tui/test_compose_messaging.py::test_deliberate_private_note_promotion_uses_real_ed25519_signature -vv -s
tests/tui/test_compose_messaging.py::test_deliberate_private_note_promotion_uses_real_ed25519_signature PASSED
1 passed in 1.74s
```

The test captures Alice's real outbound envelope, verifies its Ed25519
signature with Alice's public key, routes it through Bob's real
`ingest_envelope()`, confirms Bob decrypts the exact content, confirms Bob's
stored signature matches the envelope, and proves both the audit export and
actual `Ctrl+E` plain-text export include the promoted message while excluding
the original `private_note` row.

### Arena/keymap/modal/transport regressions

```text
$ python -m pytest tests/tui/test_keymap_registry.py tests/tui/test_dangerous_actions_gated.py tests/tui/widgets/test_modal.py tests/tui/test_app_shell.py tests/tui/test_workspace_tabs.py tests/tui/test_80x24_plain_mode_flows.py tests/tui/test_session_arena_data.py tests/tui/test_session_arena_rendering.py tests/tui/test_session_arena_replay.py tests/tui/test_session_arena_streaming_c1.py tests/tui/test_session_arena_streaming_c2.py tests/tui/test_session_arena_key_matrix.py tests/tui/test_session_arena_phaseD_lanes.py tests/tui/test_session_arena_phaseD_approvals.py tests/tui/test_session_arena_phaseD_artifacts.py tests/test_v11_transport_m3.py -q
8 snapshots passed.
124 passed in 28.98s
```

### Full default regression suite

```text
$ python -m pytest -m "not smoke" -q
--------------------------- snapshot report summary ---------------------------
14 snapshots passed.
1460 passed, 5 deselected in 129.17s (0:02:09)
```

## Delivery boundary

This branch contains only M7 Slice 1 and its verification evidence. No later
M7 slice is included.
