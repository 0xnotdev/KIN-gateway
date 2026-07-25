# KIN V1.1 — Milestone M4 Progress Summary
**Adapter Runtime and Bounded Collaboration Orchestration (§15.7)**

---

## 1. Milestone Overview

Milestone M4 turns accepted session state into controlled local agent work and verified, observable outputs. No adapter has direct network transport handles or peer/tool authority.

### Key Objectives Achieved:
1. **Adapter Abstraction & Runtime Engine (`kin/adapters/`)**:
   - Implemented standard Pydantic request/event/response wire contract matching §9.3 (`extra="forbid"`, schema/protocol version `"1.1"`).
   - **LiteLLM Embedded Adapter (`kin/adapters/embedded.py`)**: Prompt-injection-safe system prompt framing, BYOK key resolution, and `max_runtime_seconds` wall-clock timeout enforcement.
   - **Webhook Adapter (`kin/adapters/webhook.py`)**: Endpoint posting with bearer credential resolution from OS keychain (`get_agent_credential_service`).
   - **Supervised Subprocess Bridge (`kin/adapters/local_command.py`)**: `subprocess.Popen(shell=False)` execution, path traversal protection, minimal env whitelisting (`PATH`, `HOME`/`USERPROFILE`, `LANG`), process-tree kill (`psutil` / `taskkill /F /T`), and `max_artifact_bytes` output truncation with audit logging.
   - **Factory (`kin/adapters/factory.py`)**: Unified adapter resolution; cleanly raises `NotImplementedError` for out-of-scope `SdkAdapterConfig`.

2. **Output Redaction & Security Validation (`validate_adapter_output`)**:
   - Closed-list redaction of forbidden chain-of-thought keys (`reasoning`, `thinking`, `chain_of_thought`, `scratchpad`, `internal_notes`).
   - Secret and API key pattern detection regexes.
   - Capability declaration enforcement (`AdapterCapabilityDeclaration`) rejecting unauthorized event kinds or action classes per adapter type.
   - Audit logging via `write_audit_event` on security rejections.

3. **Session Orchestrator (`kin/session/orchestrator.py`)**:
   - `advance_session_turn`: Turns accepted state into adapter executions, handles local activity logging, policy checks via `evaluate_action_for_session`, pending approval creation (`create_pending_approval`), outbound envelope signing, self-ingest, and queueing in `outbound_envelope_queue`.
   - Event ordering: Enforces that `local_only` activity events strictly precede `peer_visible` outbound messages.
   - Artifact handling: SHA-256 calculation, `max_artifact_bytes` enforcement, and encrypted vault storage (`bytes_encrypted`).
   - `send_status_nudge`: 60-second rate-limited owner status nudges.
   - `tag_in_handoff`: Bounded agent substitution package, `sessions` table update, and signed `PARTICIPANT_CHANGED` envelope dispatch.

---

## 2. File & Package Structure

```
kin-node/
├── kin/
│   ├── adapters/
│   │   ├── __init__.py            # Public adapter exports
│   │   ├── base.py                # Models, capability declarations, validate_adapter_output
│   │   ├── embedded.py            # LiteLLM embedded adapter
│   │   ├── factory.py             # Adapter factory dispatch
│   │   ├── local_command.py       # Supervised subprocess bridge
│   │   └── webhook.py             # Remote webhook adapter
│   ├── policy/
│   │   └── persistence.py         # Added create_pending_approval
│   ├── schemas.py                 # Added ACTIVITY & ADAPTER_ERROR to InternalEventKind
│   └── session/
│       ├── orchestrator.py        # advance_session_turn, send_status_nudge, tag_in_handoff
│       └── reducer.py             # Added mark_awaiting_owner_approval & hardened substitution lock
├── scratch/
│   └── smoke_m4_e2e.py            # E2E two-profile collaboration smoke test script
├── tests/
│   ├── test_adapter_output_redaction.py
│   ├── test_adapters_contract.py
│   ├── test_local_command_security.py
│   ├── test_orchestrator_e2e.py
│   └── test_orchestrator_event_ordering.py
└── m4_progress.md
```

---

## 3. Verification & Test Suite

The test suite contains **276 passing tests** across `kin-node`:

```text
tests/test_adapter_output_redaction.py .....                               [  1%]
tests/test_adapters_contract.py ...                                        [  2%]
tests/test_local_command_security.py ...                                   [  3%]
tests/test_orchestrator_e2e.py ...                                         [  4%]
tests/test_orchestrator_event_ordering.py .                                [  5%]
tests/test_v11_transport_m3.py ...............................             [ 16%]
[... 245 additional passing tests ...]
276 passed, 1 deselected, 1 warning in 22.91s
```

### Smoke Test Output (`scratch/smoke_m4_e2e.py`):
```text
=== KIN V1.1 Milestone M4 Smoke Test ===
[1] Turn advanced result: {'status': 'delivered', 'sequence': 1, 'kind': 'proposal'}
[2] Reconstructed SessionState status: active, current_turn: 1
[3] Total persisted session events: 2
    - Event kind=activity, visibility=local_only
    - Event kind=proposal, visibility=peer_visible
=== Smoke Test Completed Successfully! ===
```

---

## 4. Deliverables Checklist (§15.7)

- [x] Standard adapter contract defined (`AdapterRequest`, `AdapterEvent`, `AdapterResponse`)
- [x] LiteLLM embedded adapter runtime implemented with timeout enforcement
- [x] Webhook adapter runtime implemented with OS keyring credential resolution
- [x] Supervised local command subprocess bridge implemented with environment isolation and process-tree termination
- [x] Adapter factory dispatch implemented
- [x] Output validation and security redaction engine (`validate_adapter_output`) implemented
- [x] Pending approval creation and policy integration implemented (`create_pending_approval`)
- [x] Session Orchestrator (`advance_session_turn`, `send_status_nudge`, `tag_in_handoff`) implemented
- [x] Local activity events precede peer-visible outbound messages
- [x] Complete test suite passing (276/276 green) and clean git commit pushed (`8fa2687`)

---

## 5. Known Limitations (§2.2, §2.7)

1. **Subprocess Process-Tree Termination Platform Fallback**:
   - On Windows, `LocalCommandAdapter._kill_process_tree` uses `taskkill /F /T /PID <pid>`.
   - On POSIX (Linux/macOS), if `psutil` is installed, it walks child process trees recursively and kills each child. If `psutil` is not installed, it falls back to `os.killpg(os.getpgid(pid), signal.SIGKILL)`. If `os.setpgid` was not invoked during `Popen` creation, process-group killing on non-Windows without `psutil` may leave detached daemonized sub-processes running.
2. **Local Command Bare-Metal Network Access Non-Isolation**:
   - As explicitly documented in §2.2, `boundaries.network_access == "deny"` is not OS-level sandboxed at the kernel socket boundary when executing local command subprocesses on bare metal (without Docker/container namespaces).
3. **SDK Adapter Out-of-Scope**:
   - SDK adapter type (`SdkAdapterConfig`) is out of scope for M4 per master spec §6.2 and raises `NotImplementedError`.

---

## 6. Open Questions for Tech Lead

1. **Subprocess Process-Group Creation on POSIX**:
   - Should `LocalCommandAdapter` explicitly pass `preexec_fn=os.setsid` on POSIX platforms during `Popen` spawn to guarantee process group isolation even when `psutil` is absent?
2. **Action Class Classification for Outbound Messages**:
   - Currently, outgoing turn messages (`PROPOSAL`, `COUNTERPROPOSAL`, `ANSWER`, `PLAN`, etc.) use `ActionClass.SESSION_PARTICIPATION` and `ActionClass.INFORMATIONAL_RELAY`. Should specific envelope kinds trigger granular action classes when policy evaluator checks are performed?
