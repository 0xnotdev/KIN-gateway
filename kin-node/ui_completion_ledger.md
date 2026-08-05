# KIN V1.1 UI Completion Ledger (§14.11)

Updated: 2026-08-05. `PASS automated` means the repository contains the named
repeatable evidence. It does not substitute for the two-laptop acceptance gate.
All snapshot/interaction apps use the canonical capability-pinned constructor in
`tests/tui/conftest.py`.

| Screen/widget | Owner and view model | Commands/events | Lifecycle and visual evidence | Keyboard/accessibility evidence | Real boundary | Result |
|---|---|---|---|---|---|---|
| Shell/chrome | `app.py`, `shell.py`; preferences/health/tabs | global keymap, navigation, settings | lifecycle matrix; four-breakpoint shell refs; default/HC/ASCII | 80×24 semantic flow, MRO guard, compositor retheme | real-node dispatch smoke | PASS automated |
| First Flight | `first_flight_modal.py`, wizard/controller; durable setup state | create/restore identity, import card, relay, exact OOB pair, demo, dispatch | primary refs at 160×44/120×36/90×28/80×24 plus theme refs | complete production-launcher keyboard flow at 80×24; exact fingerprint proof | real crypto/profile writes; fixture demo labelled optional | PASS automated |
| Home | `home_screen.py`; health/sessions/Needs You | open workspaces, guide, dispatch | four primary refs plus default/HC/ASCII | keyboard reachability at 80×24; semantic state labels | real profile projection | PASS automated |
| Agents | `agents_screen.py`; `AgentCardView` | inspect, enable/disable, import | four primary refs plus theme matrix | keyboard selection; visible boundaries, no hover dependency | real registry/card validation | PASS automated |
| Network | `network_screen.py`; contacts/peer cards | pair, review, open contact | four primary refs plus theme matrix | keyboard navigation; textual trust/provenance | real two-process pairing/fingerprint smoke | PASS automated |
| Dispatch + picker | wizard/controller; draft, agents, reviewed Pantry | real signed dispatch; local/peer selection | four refs each; theme/ASCII matrix | all seven steps via `pilot.press`; long labels/details at 80×24 | real transport smoke and Pantry signing | PASS automated |
| Inbox / Needs You | `inbox_screen.py`; needs/approval views | accept, decline, approval review | four primary refs plus theme matrix | ordered 80×24 keyboard flow; urgency/risk text | two-node pending-review flow | PASS automated |
| Approval modals | approval card/modals; request/decision | approve once/bounded, deny, constraints | four primary refs and modal/colorless coverage | exact scope/risk review and confirmation at 80×24 | real policy persistence and CLI parity | PASS automated |
| Session Arena | arena and lanes; events/outcome/budgets/artifacts | message, replay, export, state, tag-in, note, checkpoint, decision, rerun, playbook | four refs; theme/ASCII; mounted repaint; 10k paging | full lane/key matrix, semantic plain mode, reduced motion | real persistence, signing, artifacts and transport | PASS automated |
| Private notes | arena notes lane/modal; `PrivateNoteView` | local create, exact-text signed promotion | four primary refs and lifecycle/theme coverage | keyboard authoring/promotion; explicit local-only label | real dual-profile Ed25519/decryption/export proof | PASS automated |
| Settings | settings screen; preferences | theme/color/ascii/motion controls | four overlay refs; six themes; HC/ASCII | F2/palette at 80×24; immediate reduced motion | durable local preferences | PASS automated |
| Toast | app host/toast; severity/timing | publish/dismiss | four deterministic overlay refs; lifecycle/timing | colorless severity text; callback-free auto-dismiss | mounted production host used by inbox/completion | PASS automated |
| Spinner | app host/spinner; activity/elapsed | start/stop/cancel | four clock/frame-pinned overlay refs; lifecycle/timing | reduced-motion elapsed label; keyboard cancellation route | mounted production host used by dispatch | PASS automated |
| Guide/help/palette | guide/help/palette modules | open/search/navigate/execute | four overlay refs plus token/theme coverage | `?`, Ctrl+K, colon commands, plain guide | production shell routes | PASS automated |

## External acceptance

T8 §14.10.4 / M8 §15.11.5 remains `OPEN — HUMAN EXECUTION REQUIRED`:
two independent laptops/accounts must run
`docs/v1.1/TWO-LAPTOP-ACCEPTANCE.md`. This is a release gate, not a missing UI
implementation.
