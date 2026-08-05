# M7 Slice 2 — Persistent History, Replay, Outcomes, and Fresh Authority

Date: 2026-08-05
Spec: `KIN-V1.1-MASTER-SPEC.md` §15.10 build step 1

## Delivered

- `kin/session/history.py` owns real checkpoint, decision, deterministic replay,
  outcome-card, and fresh-authority rerun models and persistence.
- Checkpoints, decisions, outcomes, and rerun provenance are encrypted owner-local
  append-only events. Private notes never enter deterministic reviewed replay.
- The Arena Decisions lane consumes persisted checkpoint/decision events. Outputs
  consumes the persisted outcome and replay digest. `f` creates a fresh draft with
  copied shape/limits, zero cumulative use, and no approval/history rows.
- Outcome creation is terminal-state-only and idempotent. Real `FINAL_RESULT`
  ingestion derives it after the reducer persists the terminal state.

## Real / fixture boundary

The Slice 2 tests use real migrated SQLite databases, AES-GCM vault encryption,
append-only event ordering, database close/reopen, reducer-compatible session
records, and policy evaluation. No widget fixture is treated as backend evidence.
The transport hook runs in production code; network delivery itself is covered by
the existing real-crypto transport suites rather than duplicated here.

## Authority proof

The rerun test seeds an approved source action, creates a fresh draft, verifies
there are zero approval rows and only a `rerun_created` provenance event, then asks
the real policy evaluator about the same action. It returns `REQUIRES_APPROVAL`.

## P2 discipline

No public discovery, reputation, payments, multi-owner teams, direct peer tool
control, or graphical client was introduced.

## Focused raw output

```text
...                                                                      [100%]
3 passed in 0.56s
```
