# KIN V1.1 Release Continuation Progress

Date: 2026-08-05
Branch: `codex/release-continuation-m6-m7`
Authority: Master Spec §§15.9–15.12 and TUI System §§14.10–14.11

## Outcome

- T7 residual compositor retheme proof and timing-constant enforcement are closed.
- M6 doctor, non-TTY/scriptable parity, and CLI scale evidence are implemented.
- M7 Slices 2 and 3 are complete over real persistence/crypto boundaries.
- M7 Slice 4 is implemented wherever a real primitive exists: readiness,
  reservations, private local quality, playbooks, and budget/impact gauges.
- UI and release traceability ledgers now exist and identify manual/open gates.

## On-disk mismatches found and handled explicitly

1. “20 CLI commands” accurately described the old 13 top-level + seven agent
   leaf commands, but the named V1.1 session/inbox/approval/dispatch actions did
   not exist. They were added rather than relabelling legacy V1 commands.
2. Checkpoint/outcome/replay were presentational only. Slice 2 adds their first
   backend models and persistence.
3. Context Pantry had a TUI dataclass that did not even retain content and used
   non-schema classifications such as `attached`. Slice 3 replaces that boundary.
4. Real budget enforcement already existed. Slice 4 gauges consume that state.
5. A complete signed `participant_changed`/tag-in primitive does not exist.
   Tag-in UX is explicitly deferred; a visual-only control was not built.
6. Advanced export templates are P2 under §10.3 and remain deferred. Existing
   deterministic audited export/redaction remains active.

## Real / fixture boundaries

- M6 dispatch uses real Ed25519/X25519 signing, self-ingestion, encrypted queue,
  SQLite, policy decision, reducer recovery, and audited export. HTTP is replaced
  only at external directory edges in targeted CLI tests.
- M7 Slice 2 uses migrated SQLite, AES-GCM, append-only event order, database
  reopen, terminal transport integration, and the real policy evaluator.
- M7 Slice 3 uses encrypted opaque references/packs, real files, real signed task
  envelopes, self-ingestion, and the encrypted outbound queue.
- M7 Slice 4 uses persisted reservations/playbooks/budgets, real cached peer-card
  freshness, real terminal outcomes, and published-card boundary assertions.
- The smoke marker starts real relay and node subprocesses on real TCP ports.

## Deliberately broken `kin doctor` — raw output

```text
KIN DOCTOR
STATUS: DEGRADED
PROFILE: deliberately-broken
CHECKS:
[WARN] version_profile: KIN 0.1.0; selected profile 'deliberately-broken'.
  ACTION: Run 'kin init' to initialize this profile.
  FACTS: {"profile": "deliberately-broken", "profile_exists": false, "profile_location": "~/.kin/profiles/deliberately-broken", "version": "0.1.0"}
[PASS] keychain: Secure OS credential backend is available.
  ACTION: No action required.
  FACTS: {"secure_backend": true}
[FAIL] identity: Identity check failed: Profile database is not initialized.
  ACTION: Run 'kin init' or restore the identity into a new profile.
  FACTS: {"available": false}
[FAIL] relay_directory: Relay Directory check failed: [WinError 10061] No connection could be made because the target machine actively refused it
  ACTION: Check KIN_RELAY_URL and start or reconnect the relay.
  FACTS: {"available": false}
[FAIL] node_tunnel: Node Tunnel check failed: Profile database is not initialized.
  ACTION: Start 'kin serve' and verify the configured endpoint or tunnel.
  FACTS: {"available": false}
[PASS] card_validation: Validated 0 V1.1 agent card(s).
  ACTION: No action required.
  FACTS: {"invalid_cards": 0, "legacy_cards": 0, "valid_cards": 0}
[WARN] provider_credentials: No LLM provider is configured.
  ACTION: Run 'kin configure'.
  FACTS: {"credential_present": false, "provider": null}
[FAIL] inbox: Inbox check failed: Profile database is not initialized.
  ACTION: Initialize the profile or inspect pending work with 'kin inbox --plain'.
  FACTS: {"available": false}
[FAIL] recovery: Recovery check failed: Profile database is not initialized.
  ACTION: Run 'kin migrate' or inspect local recovery reports before retrying.
  FACTS: {"available": false}
SUMMARY: passed=2 warnings=2 failed=5
DOCTOR_EXIT_CODE=1
```

## Verification — raw output

CLI/doctor/pair/agent/relay/migration matrix:

```text
........................................................................ [ 68%]
.................................                                        [100%]
105 passed in 19.77s
```

Full TUI suite:

```text
........................................................................ [ 96%]
..................................                                       [100%]
--------------------------- snapshot report summary ---------------------------
14 snapshots passed.
1114 passed, 2 deselected in 62.65s (0:01:02)
```

Default repository suite (`pyproject.toml` excludes the smoke marker):

```text
........................................................................ [ 99%]
...                                                                      [100%]
--------------------------- snapshot report summary ---------------------------
14 snapshots passed.
1515 passed, 5 deselected in 122.70s (0:02:02)
```

Real relay/node subprocess and TCP smoke marker, run separately:

```text
.....                                                                    [100%]
5 passed, 1515 deselected in 172.79s (0:02:52)
```

Static compilation/diff hygiene:

```text
compileall: PASS
git diff --check: PASS (no output)
```

## Standing human release task

T8 §14.10 step 4 / M8 §15.11 step 5 remains
`OPEN — SCHEDULING REQUIRED`: two independent laptops, two accounts, two humans,
and redacted evidence only. This is not represented as automated completion.

## Publication state

Changes are intentionally uncommitted and unpushed for review. No publication was
requested in this instruction block.
