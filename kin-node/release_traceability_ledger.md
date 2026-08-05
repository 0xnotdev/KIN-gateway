# KIN V1.1 Requirement Traceability Ledger (§15.12)

Updated: 2026-08-05. Owner defaults to Engineering unless a human/manual owner
is named. Evidence links are repository-relative. `PARTIAL` and `OPEN` are
intentional release blockers until their missing evidence lands.

## §3.2 measurable acceptance bar

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| One-command Windows install under five minutes | M8 installer not yet in scope | packaging/installer test OPEN | clean Windows laptop install | OPEN | §15.11 |
| Core journey without DB/protocol hand edits | TUI + V1.1 CLI contracts | T8 Phase A/B smoke; `test_cli_v11_contract.py` | two-laptop full journey | PARTIAL | `tui_t8_phase_a_progress.md` |
| Dashboard interactive under 2s at 100 sessions/20 agents | TUI performance harness + `kin session list` projection | T8 Phase C tests; `test_cli_session_list_100_sessions_20_agents_under_two_seconds` | none | PASS automated | `tests/test_cli_v11_contract.py` |
| Direct session under 5s; offline queue resumes | `transport/v11.py`, retry queue | T8 Phase B/C smoke | normal two-laptop timing | PARTIAL | `tests/test_smoke_two_node.py` |
| Timestamp/actor/signature/provenance on transitions, approvals, artifacts, messages | schemas, audit writer, artifact vault, policy persistence | transport/artifact/approval/export suites | inspect final two-laptop transcript | PASS automated; manual OPEN | `tests/test_v11_transport_m3.py` |
| Peer cannot execute command/read file/access secret by request | adapter boundary/policy/approval/content scrubbing | adversarial adapter, approval, redaction suites | hostile peer acceptance step | PASS automated; manual OPEN | `tests/test_content_scrubbing_adversarial.py` |

## §6 Agent model

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| Person identity remains trust anchor; agents are local owner-controlled profiles | `identity`, `agent_registry` | identity/agent registry suites | inspect owner/agent attribution | PASS | `tests/test_agent_registry.py` |
| Stable ID/name, adapter config, published card, local boundaries/policy | `schemas.AgentCard`, YAML loader/registry | `test_cli_agent.py`, registry/schema tests | none | PASS | `kin/schemas.py` |
| Credentials never stored in YAML | keychain services + loader validation | storage/keychain and projection tests | inspect example card | PASS | `tests/test_storage_keychain.py` |
| Embedded, webhook, local-command, SDK adapter contract | `adapters/` | adapter contract tests | SDK documentation review | PARTIAL | `tests/test_adapters_contract.py` |
| Published card contains safe metadata only | `publish_card` field-by-field projection | `test_agent_projection.py` | none | PASS | `kin/agent_registry/registry.py` |
| Published card never exposes paths/secrets/prompts/memory/tool authority | safe projection | adversarial projection tests | none | PASS | `tests/test_agent_projection.py` |
| Tag-in creates bounded package and signed participant change; no private memory | orchestrator handoff | handoff/transport tests | TUI tag-in flow | PARTIAL | `kin/session/orchestrator.py` |
| Reservations and local quality remain private, never public reputation | `collaboration_depth.py`; local session-derived projection | reservation/readiness/local-quality tests | review published projection | PASS | `m7_slice4_operational_depth_progress.md` |

## §7 Collaboration model

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| Six structured session types remain bounded | `SessionType`, transport dispatch | schema/transport tests | none | PASS | `kin/schemas.py` |
| Dispatch lifecycle and explicit receiver agent confirmation | reducer/transition matrix/TUI Inbox | dispatch/transport/two-node smoke | receiver review | PARTIAL | `kin/session/transition_matrix.py` |
| Participant cards snapshotted; changes do not rewrite history | session persistence/card snapshots | transport/card state tests | inspect old session after card edit | PASS automated | `tests/test_v11_transport_m3.py` |
| Owner pause/cancel visible and signed; 12-turn hard cap cannot auto-expand | reducer/transport budgets | control/budget tests | none | PASS | `tests/test_approval_decisions.py` |
| Every message has session, sequence, identity/agent, versions, timestamp, hash, signature | envelope schemas and verifier | signature/sequence/replay tests | none | PASS | `tests/test_v11_transport_m3.py` |
| Immutable encrypted artifacts; explicit import; patch apply separately approved | artifact vault/import/apply gates | artifact suites | review artifact on two laptops | PASS automated; manual OPEN | `tests/test_artifact_workspace_import.py` |
| V1.1 social boundary excludes public discovery/reputation/payments/strangers | no production seams permitted | per-slice P2 scope check | repository feature review | PASS current scope | §15.10 step 4 |
| Playbooks require fresh choices/approvals and reject stale cards/policy | encrypted playbooks + compatibility gate | playbook compatibility/stale-policy test | none | PASS | `m7_slice4_operational_depth_progress.md` |
| Pause/resume/fork/clarification/budgets/checkpoint retry/export semantics | reducer, audited export, persistent history/fresh rerun | control/export + `test_session_history_m7.py` | none | PASS for M7 history/rerun scope | `m7_slice2_history_progress.md` |
| Context Pantry classifications, expiry, explicit packs, no browsable local paths | `context_pantry.py`, signed dispatch pack | `test_context_pantry_m7.py` | review send boundary | PASS automated | `m7_slice3_context_pantry_progress.md` |

## §8 Security, privacy, and consent

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| Ed25519 identity, OOB fingerprint, X25519 relay, keychain, direct-first/offline remain mandatory | identity/transport/keychain | CLI pair, crypto, relay fallback suites | OOB fingerprint on two laptops | PASS automated; manual OPEN | `tests/test_cli_pair.py` |
| Inbound peer content/cards/artifacts/metadata are untrusted | verifier, loader, artifact validation | adversarial suites | none | PASS | `tests/test_content_scrubbing_adversarial.py` |
| No delegated peer tool authority; owner-local policy only | adapter runtime/policy evaluator | hostile action and approval authorization tests | deny hostile request | PASS automated; manual OPEN | `tests/test_approval_decisions.py` |
| No raw chain-of-thought; structured observable results only | adapter scrubber/TUI redaction | reasoning exposure/redaction tests | inspect transcript | PASS automated | `tests/test_adapter_output_redaction.py` |
| Least data; unrelated memory/prompts/workspace stay local | safe card/context boundaries and reviewed Pantry pack | projection/redaction + Pantry adversarial tests | none | PASS automated | `m7_slice3_context_pantry_progress.md` |
| Capability claims do not authorize actions | policy evaluator | policy/agent card tests | none | PASS | `tests/test_agent_projection.py` |
| Immutable inspectable audit | append-only triggers/audit writer/export | storage/export tests | inspect completed transcript | PASS | `tests/test_export.py` |
| Explicit agent selection and visible signed replacement | transport/orchestrator | participant-change tests | TUI tag-in | PARTIAL | `kin/session/orchestrator.py` |
| Approval classes enforce local defaults and bounded decisions | policy persistence | approval suites + CLI parity | approval review | PASS | `tests/test_cli_v11_contract.py` |
| Threat responses: invalid signature/unpaired/stale/prompt injection/relay offline/ACK honesty | verifier, stale cards, queue/retry | transport/security/relay suites | resilience journey | PASS automated; manual OPEN | `tests/test_v11_transport_m3.py` |
| Trust/provenance is visible and card changes reviewable | Arena trust strip, Inspector, card diff | TUI trust/card tests | 15-second Arena assessment | PARTIAL | `kin/tui/widgets/trust_strip.py` |
| Cost/time/budget transparency; exhaustion pauses; peer cost private | budget persistence/orchestrator + Arena gauges | budget + private-peer-cost tests | gauge review | PASS automated; manual OPEN | `m7_slice4_operational_depth_progress.md` |

## §9 Technical architecture and compatibility

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| TUI and scriptable CLI use local node/persistence seams | `kin/tui/local_state.py`, `kin/cli_v11.py` | CLI non-TTY parity + T8 smoke | none | PASS for named M6 actions | `tests/test_cli_v11_contract.py` |
| Identity/registry/runtime/orchestrator/policy/artifact/transport/audit modules own stated boundaries | package modules | component suites | architecture review | PASS automated | `kin/` |
| Adapter sees only approved session inputs/history and cannot send directly | adapter contract/runtime | adapter contract tests | none | PASS | `kin/adapters/base.py` |
| Sensitive stored content encrypted at rest; public metadata safe | vault + persistence | storage/vault/projection tests | none | PARTIAL: legacy/plain session metadata compatibility remains documented | `kin/audit/export.py` |
| V1.1 capability advertisement and precise incompatible-version failure | node capabilities/negotiation | capability/transport tests | none | PASS | `kin/transport/v11.py` |
| V1 primitives migrate additively and failed migration preserves old profile | migration staging/atomic replace | migration tests | upgrade real profile copy | PASS automated; manual OPEN | `tests/test_migrations.py` |

## §10 Installation and operations

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| Readable pinned/checksummed one-command PowerShell installer with pipx alternative | M8 packaging OPEN | tests OPEN | clean Windows install | OPEN | §10.1 |
| Installer detects prerequisites, explains cloudflared, runs doctor/init | M8 installer OPEN | tests OPEN | clean Windows install | OPEN | §10.1 |
| Doctor covers version/profile, keychain, identity, relay, node/tunnel, cards, credentials, inbox, recovery | `kin/doctor.py`, `kin doctor` | `tests/test_cli_doctor.py` | run against broken dependency | PASS | `m6_cli_scriptable_parity_progress.md` |
| P0 product surfaces remain ahead of P1/P2 | milestone scope control | progress docs | release review | PARTIAL | §10.3 |

## TUI quality gates

| Requirement | Implementation seam | Automated test ID | Manual step | Result | Evidence |
|---|---|---|---|---|---|
| Deterministic snapshots, keyboard flows, lifecycle states, accessibility | TUI harness/canonical app fixture | TUI full suite | human visual review | PASS automated; manual OPEN | `ui_completion_ledger.md` |
| No task depends on width/color/Unicode/mouse/motion | breakpoint/plain/colorless/reduced-motion implementation | T7 suites | terminal spot-check | PASS automated | `tui_t7_progress.md` |
| Mounted content repaints on live theme change | Textual CSS variables and compositor | `test_live_theme_switch_rethemes_mounted_session_arena` | none | PASS | `tests/tui/test_arena_integration_real_app.py` |
| Real-node integration, 10k events, focus/selection stability, recovery | T8 harness | T8 Phase A–C tests | none | PARTIAL pending ledger reconciliation | §14.10 |
| Two-independent-laptop acceptance | human-only | not automatable | schedule two humans/accounts; redacted evidence only | OPEN — SCHEDULING REQUIRED | T8 §14.10.4 / M8 §15.11.5 |

## Seven explicit release blockers (§15.12)

| # | Assertion | Implementation seam | Automated test ID | Manual step/owner | Result | Evidence |
|---|---|---|---|---|---|---|
| 1 | V1 identities, contacts, commands, and queued relay messages survive migration | staging migration + compatibility CLI | migration/CLI regression suites | real upgrade copy / Release owner | PARTIAL | `tests/test_migrations.py` |
| 2 | Every peer-visible message, transition, approval, artifact has timestamp, actor, provenance/signature, inspectable history | schemas/audit/transport/artifacts/policy | transport, approval, artifact, export suites | inspect two-laptop export / Security owner | PASS automated; manual OPEN | `tests/test_export.py` |
| 3 | Peer cannot command, access secret/filesystem, or bypass approval through crafted inputs | policy/adapter/verifier/redaction | adversarial and authorization suites | hostile peer denial / Security owner | PASS automated; manual OPEN | `tests/test_content_scrubbing_adversarial.py` |
| 4 | No CoT/hidden prompt/credential/unapproved file content is requested, stored, relayed, exported, or rendered | adapter/TUI/export scrubbing + reviewed Pantry boundary | redaction/reasoning/doctor/Pantry tests | inspect release transcript / Security owner | PASS automated; manual OPEN | `tests/test_context_pantry_m7.py` |
| 5 | All primary flows work from keyboard and coherent non-TTY/plain alternative | TUI keymap + V1.1 CLI | 80×24 flows + CLI parity contracts | keyboard journey / Product owner | PASS named automated flows; manual OPEN | `tests/test_cli_v11_contract.py` |
| 6 | Dashboard under 2s; direct session under 5s; offline state honest and resumes | T8 performance + CLI scale + relay retry | Phase B/C + CLI scale | normal network timing / Release owner | PARTIAL | `tests/test_cli_v11_contract.py` |
| 7 | Two-person journey completes from documented install to deterministic export without DB/protocol edits | installer/TUI/node/export | smoke suites | two laptops/accounts / two humans | OPEN — SCHEDULING REQUIRED | T8 §14.10.4 / M8 §15.11.5 |
