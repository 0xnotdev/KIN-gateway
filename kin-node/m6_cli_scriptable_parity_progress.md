# M6 Scriptable Parity and Doctor Progress

Date: 2026-08-05
Branch: `codex/release-continuation-m6-m7`
Spec authority: `KIN-V1.1-MASTER-SPEC.md` §15.9

## On-disk audit result

The reported “20 CLI commands” is accurate for the original leaf surface:
13 top-level commands plus seven `agent` subcommands. The repository did not
contain the V1.1 commands named by §15.9 (`session list/open/export`, Inbox,
approval decisions, or V1.1 dispatch), so flags alone could not close the gap.

| Original command | M6/TUI equivalence decision | Contract status |
|---|---|---|
| `pair` | Network/First Flight; fingerprint gate must not be bypassed | `--json`/`--plain`; noninteractive requires exact `--verified-fingerprint` |
| `init` | named §15.9 action | `--json`/`--plain`; protected phrase file path |
| `ask` | preserved V1 compatibility path, superseded by V1.1 `dispatch` | legacy output retained; not presented as V1.1 parity |
| `respond` | preserved V1 compatibility draft response, superseded by `approval decide`/`session message` | legacy output retained |
| `fetch` | V1 relay maintenance, not a TUI-only state action | legacy output retained |
| `serve` | named §15.9 action | `--json`/`--plain`; JSON requires `--no-fetch` for one-document stdout |
| `contacts` | Network read model | `--json`/`--plain` |
| `contact-policy` | local state/policy action | `--json`/`--plain` |
| `configure` | Settings/provider action | `--json`/`--plain`; protected credential file |
| `tasks` | V1 compatibility list; V1.1 uses `session list` | legacy output retained |
| `status` | V1 compatibility detail; V1.1 uses `session open` | legacy output retained |
| `restore` | named §15.9 recovery action | `--json`/`--plain`; protected phrase file and username options |
| `migrate` | recovery/upgrade action | `--json`/`--plain`, including recoverable failure result |
| `agent list/inspect/validate/enable/disable/import/publish` | named cards surface | every subcommand exposes explicit `--json` and `--plain` |

Added V1.1 parity commands: `dispatch`, `inbox`, `doctor`, `session
list/open/export/recover/pause/resume/cancel/message`, and `approval
list/decide`. They reuse TUI local-state, audit-export, reducer, policy, and
transport seams rather than parallel implementations.

## Real/fixture boundary

- CLI dispatch tests use real Ed25519/X25519 keys, the real V1.1 signing and
  symmetric self-ingestion path, SQLite persistence, and the real encrypted
  outbound queue. No network fixture is required because an unavailable peer
  intentionally exercises durable local queueing.
- Approval tests use a real pending `ApprovalRequest`, real vault-backed audit
  persistence, and the same `decide_pending_approval()` path as Inbox.
- Export and recovery tests read the real dispatched event from SQLite through
  the audited exporter and deterministic reducer reconstruction.
- HTTP is replaced only at the external directory boundary for init/restore and
  exact-fingerprint pairing. Crypto, keychain calls, and persistence remain real.

## Scope discipline

No public discovery, reputation, payments, multi-owner teams, direct peer tool
control, or graphical client was introduced.

## Standing manual task

T8 §14.10 step 4 and M8 §15.11 step 5 require two independent laptops and
accounts. Status: **OPEN — SCHEDULING REQUIRED (two humans, redacted evidence only).**

## Deliberately broken dependency — raw output

Command used a clean temporary home/profile and
`KIN_RELAY_URL=http://127.0.0.1:1`:

```text
KIN DOCTOR
STATUS: DEGRADED
PROFILE: deliberately-broken
CHECKS:
[WARN] version_profile: KIN 0.1.0; selected profile 'deliberately-broken'.
  ACTION: Run 'kin init' to initialize this profile.
[PASS] keychain: Secure OS credential backend is available.
  ACTION: No action required.
[FAIL] identity: Identity check failed: Profile database is not initialized.
  ACTION: Run 'kin init' or restore the identity into a new profile.
[FAIL] relay_directory: Relay Directory check failed: [WinError 10061] No connection could be made because the target machine actively refused it
  ACTION: Check KIN_RELAY_URL and start or reconnect the relay.
[FAIL] node_tunnel: Node Tunnel check failed: Profile database is not initialized.
  ACTION: Start 'kin serve' and verify the configured endpoint or tunnel.
[PASS] card_validation: Validated 0 V1.1 agent card(s).
  ACTION: No action required.
[WARN] provider_credentials: No LLM provider is configured.
  ACTION: Run 'kin configure'.
[FAIL] inbox: Inbox check failed: Profile database is not initialized.
  ACTION: Initialize the profile or inspect pending work with 'kin inbox --plain'.
[FAIL] recovery: Recovery check failed: Profile database is not initialized.
  ACTION: Run 'kin migrate' or inspect local recovery reports before retrying.
SUMMARY: passed=2 warnings=2 failed=5
DOCTOR_EXIT_CODE=1
```

## CLI, doctor, pairing, agent, relay, and migration matrix — raw output

```text
........................................................................ [ 68%]
.................................                                        [100%]
105 passed in 19.77s
```
