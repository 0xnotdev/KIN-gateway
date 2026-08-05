# KIN V1.1 TUI — T8 Phase B Progress

Date: 2026-08-05
Branch: `codex/t8-phase-b-resilience`
Base: `aa3bde3 test(tui): prove T8 phase A over real nodes`
Scope: T8 Phase B only. Phase C has not started.

## Outcome

Phase B is implemented end to end over the shared real relay/two-node harness:

1. Bob is stopped with SIGTERM before Alice dispatches. Alice queues one encrypted V1.1 envelope at the real relay. Bob restarts, processes it on a real authenticated poll, ACKs it, and a second poll produces neither a mailbox message nor a duplicate event.
2. Alice is stopped with SIGTERM in an active session and restarted on the same port and `profile_dir`. A separate worker process reconstructs the active state and actor sequences from SQLite. The real Textual Arena mounts, streams a new event, unmounts, remounts, resumes its worker, and reaches the five-event terminal history with no missing or duplicate session event IDs.
3. A pending approval uses a 0.5-second test-only expiry. After real elapsed time, the production `decide_pending_approval()` path returns the specific expired-approval error and leaves `decision` null.
4. Alice sends a real artifact offer to Bob. Bob is stopped and restarted. A separate Bob worker decrypts the artifact again and proves the stored SHA-256, computed SHA-256, content, `offered_by=alice`, and `source=peer_received` are unchanged.

## Real/fixture boundary

- Real processes: one `kin-relay`, Alice `kin.cli serve`, Bob `kin.cli serve`, and every profile-scoped worker operation.
- Real network: relay directory, relay mailbox/inbox/ACK, capability reads, V1.1 session envelopes, messages, and artifact offer.
- Real persistence: Alice and Bob each open only their own profile SQLite and key material inside their own subprocess environment.
- The Textual Arena reads Alice's own local SQLite directly. That is the production TUI boundary by design; it does not open Bob's database.
- The short approval duration is injected only through `scripts/smoke_v11_worker.py --expiry-seconds`; production expiry defaults are unchanged.

## Production defects found and fixed

### V1.1 relay contract was unreachable

The V1.1 transport used `/relay/mailbox` with `recipient_username`/`payload`, while the real relay implements `/relay/mailbox/{username}` with `sender_username`/`encrypted_blob`. All V1.1 relay sends now use one shared `_queue_relay_envelope()` helper matching the real HTTP contract.

### V1.1 relay fetch and ACK were incompatible with the real relay

The poller looked for `payload` instead of `encrypted_blob`, used node-auth base64url signatures for relay inbox reads, and reused the inbox signature for a body-bound ACK. It now uses relay-compatible hex signatures and signs the canonical compact ACK body before posting it.

### Arena remount could duplicate streamed events

The prior boolean lifecycle flag allowed an old sleeping worker to become active again when a remount set the same flag to true. Two workers could then append the same new audit records. A monotonic mount-generation token now permanently invalidates workers from earlier mounts, including the wake-up-after-sleep race.

### Legacy smoke direct timeout was implicit and too short

The complete smoke gate exposed the M0 `/tasks` handler exceeding HTTPX's implicit five-second timeout and incorrectly falling back to relay. `kin ask` now uses an explicit 30-second direct-response timeout. The focused CLI suite remains green.

## T7 closure re-check requested during Phase B

The earlier grep conclusion was incomplete. The T7 integration is present in `KinApp`:

```text
$ rg -n "def record_latency_sample|def _sample_event_loop_latency|self\.record_latency_sample|_motion_probe_timer = self\.set_interval|yield self\.activity_spinner|yield self\.notification_toast|def show_toast|def start_activity|def stop_activity" kin/tui/app.py
312:    def record_latency_sample(self, latency_ms: float) -> None:
326:    def _sample_event_loop_latency(self) -> None:
338:        self.record_latency_sample(drift_ms)
355:    def show_toast(self, message: str, severity: str = "info", duration_ms: Optional[int] = None) -> None:
359:    def start_activity(self, label: str, cancel_callback: Optional[Callable[[], None]] = None) -> None:
363:    def stop_activity(self, message: Optional[str] = None, severity: str = "success") -> None:
378:        yield self.activity_spinner
379:        yield self.notification_toast
398:        self._motion_probe_timer = self.set_interval(

$ rg -n "start_activity|stop_activity" kin/tui/widgets/dispatch_wizard.py
355:        if self.is_mounted and hasattr(self.app, "start_activity"):
356:            self.app.start_activity("Dispatching session")
365:            if self.is_mounted and hasattr(self.app, "stop_activity"):
366:                self.app.stop_activity("Dispatch failed", severity="error")
426:        if self.is_mounted and hasattr(self.app, "stop_activity"):
430:                    self.app.stop_activity,
435:                self.app.stop_activity(

$ rg -n "show_toast" kin/tui/widgets/inbox_screen.py
96:            if hasattr(self.app, "show_toast"):
97:                self.app.show_toast(
104:        if self.is_mounted and hasattr(self.app, "show_toast") and self.last_action_message:
105:            self.app.show_toast(
```

The caller is `KinApp._sample_event_loop_latency()` and `on_mount()` schedules it. The production mount site is `KinApp.compose()`. Dispatch and Inbox are real producers. The unused First Flight import remains dead code, but it is not the mount/integration mechanism.

## Reproducible raw evidence

### Standalone Phase B harness

Command:

```text
python scripts/smoke_two_node.py --protocol v11-phase-b
```

Output:

```text
SMOKE V1.1 PHASE B RELAY: session_id=sess_14c5a251794f4852, dispatch=queued, queued_messages=1, first_poll=1, mailbox_after_ack=0, second_poll=0, bob_event_count=1
SMOKE V1.1 PHASE B RESTART: session_id=sess_7254622292dc4df2, sigterm_returncode=1, before_status=active, reconstructed_status=active, reconstructed_events=4, final_status=completed, final_events=5
SMOKE V1.1 PHASE B EXPIRY: session_id=sess_1b12e1b574a34ff4, approval_id=app_smoke_780e36f1dbc0, expires_at=2026-08-05T06:01:08.177805Z, success=False, error="Approval 'app_smoke_780e36f1dbc0' has expired.", decision=None
SMOKE V1.1 PHASE B ARTIFACT: session_id=sess_5a96db62fd924cff, artifact_id=art_894c08a448af, delivery=direct, sha256=11c64c5f4fa9ca111e9b7c8a94cb8483298288495b37e92feb4e37b326461d6c, computed_sha256=11c64c5f4fa9ca111e9b7c8a94cb8483298288495b37e92feb4e37b326461d6c, offered_by=alice, source=peer_received
PASS: V1.1 Phase B relay, restart, expiry, and artifact gates succeeded!
```

### Real Textual restart/reopen proof

Command:

```text
python -m pytest tests/tui/test_smoke_real_node_resilience.py -m smoke -q -s
```

Output:

```text
TUI PHASE B RESTART: session_id=sess_bc327ff1dc3a45e5, sigterm_returncode=1, reconstructed_status=active, reconstructed_events=3
TUI PHASE B ARENA: on_mount restarted polling after reopen; status=completed, event_count=5, unique_event_ids=5, kinds=['task_request', 'acceptance', 'question', 'answer', 'final_result']
PASS: real-node SIGTERM/restart and Arena reopen preserved exact history
.
1 passed in 38.89s
```

### Focused regressions

```text
$ python -m pytest tests/test_v11_transport_m3.py -q
.................................                                        [100%]
33 passed in 8.99s

$ python -m pytest tests/tui/test_session_arena_streaming_c2.py -q
.........                                                                [100%]
9 passed in 1.40s

$ python -m pytest tests/test_cli_relay_fallback.py tests/test_cli_ask.py -q
.................................                                        [100%]
33 passed in 11.39s
```

### Complete real-process smoke group

Command:

```text
python -m pytest tests/test_smoke_two_node.py tests/tui/test_smoke_real_node_dispatch.py tests/tui/test_smoke_real_node_resilience.py -m smoke -q -s
```

Output:

```text
.SMOKE V1.1: session_id=sess_b984e92686484ffe
SMOKE V1.1: Bob subprocess storage proof -> status=peer_review, event_count=1, goal='Coordinate a real V1.1 smoke collaboration'
SMOKE V1.1: Alice final -> status=completed, event_count=5, kinds=["task_request", "acceptance", "question", "answer", "final_result"]
SMOKE V1.1: Bob final -> status=completed, event_count=5, kinds=["task_request", "acceptance", "question", "answer", "final_result"]
PASS: V1.1 two-node session lifecycle over real sockets succeeded!
.SMOKE V1.1 PHASE B RELAY: session_id=sess_dee8115b9f174369, dispatch=queued, queued_messages=1, first_poll=1, mailbox_after_ack=0, second_poll=0, bob_event_count=1
SMOKE V1.1 PHASE B RESTART: session_id=sess_def9b6d5a26f4ae1, sigterm_returncode=1, before_status=active, reconstructed_status=active, reconstructed_events=4, final_status=completed, final_events=5
SMOKE V1.1 PHASE B EXPIRY: session_id=sess_fb220f71371a42c5, approval_id=app_smoke_caf2fe495aa8, expires_at=2026-08-05T06:20:05.562540Z, success=False, error="Approval 'app_smoke_caf2fe495aa8' has expired.", decision=None
SMOKE V1.1 PHASE B ARTIFACT: session_id=sess_b2f332808b17494c, artifact_id=art_f3f2d6178812, delivery=direct, sha256=11c64c5f4fa9ca111e9b7c8a94cb8483298288495b37e92feb4e37b326461d6c, computed_sha256=11c64c5f4fa9ca111e9b7c8a94cb8483298288495b37e92feb4e37b326461d6c, offered_by=alice, source=peer_received
PASS: V1.1 Phase B relay, restart, expiry, and artifact gates succeeded!
.TUI REAL-NODE: keyboard dispatch -> session_id=sess_6a3879e66dab4003, transport_status=delivered
TUI REAL-NODE: Bob subprocess storage proof -> status=peer_review, event_count=1, kinds=['task_request'], goal='prove keyboard dispatch over a real node boundary'
PASS: KinApp pilot keyboard dispatch reached the separate real Bob node
.TUI PHASE B RESTART: session_id=sess_b400b18fffe44a32, sigterm_returncode=1, reconstructed_status=active, reconstructed_events=3
TUI PHASE B ARENA: on_mount restarted polling after reopen; status=completed, event_count=5, unique_event_ids=5, kinds=['task_request', 'acceptance', 'question', 'answer', 'final_result']
PASS: real-node SIGTERM/restart and Arena reopen preserved exact history
.
5 passed in 178.32s (0:02:58)
```

### Default regression gate

Command:

```text
python -m pytest -m "not smoke" -q
```

Output tail:

```text
..................                                                       [100%]
--------------------------- snapshot report summary ---------------------------
14 snapshots passed.
1458 passed, 5 deselected in 120.70s (0:02:00)
```

## Review boundary

Phase B is ready for independent review on `codex/t8-phase-b-resilience`. No Phase C implementation is included.
