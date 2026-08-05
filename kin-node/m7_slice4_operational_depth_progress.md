# M7 Slice 4 — Operational Depth over Real Primitives

Date: 2026-08-05
Spec: `KIN-V1.1-MASTER-SPEC.md` §15.10 build step 3

## Delivered now

- Real local reservations feed readiness recommendations with a one-sentence
  explanation and disabled-policy handling.
- Private quality signals derive only from local session persistence and are
  absent from `PublishedAgentCard`.
- Encrypted playbooks require a completed persisted outcome. Opening one requires
  fresh person/agent choices, rejects stale cards or blocked local policy, checks
  capabilities, and carries zero approvals.
- Arena gauges consume persisted time/artifact/cost ceilings already enforced by
  orchestration. Missing estimates say “not reported”; peer cost remains absent
  unless explicitly supplied as `peer_cost_summary` in a signed final result.

## Deliberately deferred because the primitive is not complete

- Safe tag-in UX: no completed signed `participant_changed` transport/state-machine
  primitive exists. A visual-only tag-in would overstate authority.
- Advanced export/redaction templates: this is P2 in §10.3 and remains behind P0/P1.
  Existing audited deterministic export/redaction remains active.

## Real / fixture boundary

Tests use migrated reservation/playbook/session tables, encrypted playbook content,
real cached peer cards and stale state, terminal outcomes, and persisted budget
counters/timestamps. No visual gauge fixture substitutes for the budget backend.

## P2 discipline

No public discovery, reputation, payments, multi-owner teams, direct peer tool
control, or graphical client was introduced. Local quality is never published.

## Focused raw output

```text
....                                                                     [100%]
4 passed in 0.18s
```
