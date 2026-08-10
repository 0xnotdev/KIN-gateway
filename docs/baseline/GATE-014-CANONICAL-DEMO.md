# GATE-014 Canonical CP0 Demo

## Claim

An unmodified official A2A client can call the same unmodified `a2a-sdk==1.1.2` `inventory.lookup` agent directly and through KIN over both JSON-RPC and HTTP+JSON. KIN preserves the completed task state and artifact semantics while presenting a public mirrored Agent Card.

## Topology

```text
official A2A SDK client
   |                 |
   | direct          | through KIN
   v                 v
reference agent    KIN gateway
127.0.0.1:18081      |
                     v
                  reference agent
```

The fixture is defined in `tests/contract/cp0_live_fixture.py`. It binds only loopback addresses and uses no credentials. The direct and proxied calls intentionally receive different task IDs; equivalence compares protocol state and artifact content, not server-generated identifiers.

## Acceptance result

For item `widget-cp0`:

| Binding | Direct state | Through KIN state | Direct/through artifact | Equivalent |
|---|---|---|---|---|
| JSON-RPC | `TASK_STATE_COMPLETED` | `TASK_STATE_COMPLETED` | `inventory:widget-cp0:available` | Yes |
| HTTP+JSON | `TASK_STATE_COMPLETED` | `TASK_STATE_COMPLETED` | `inventory:widget-cp0:available` | Yes |

The gateway Agent Card contains only public gateway interface URLs, an ETag derived from the normalized public card, and `X-KIN-Upstream-Agent-Card-SHA256` for source traceability. The captured result is `docs/baseline/evidence/gate-014/inventory-lookup-demo.json`.

## Reproduce

```powershell
.\scripts\run_cp0_demo.ps1 `
  -Python "C:\path\to\kin-gateway-python.exe"
```

The runner starts the upstream and gateway listeners hidden, waits for the public Agent Card, runs the official SDK client against both paths and both bindings, writes `.artifacts/cp0-demo/inventory-lookup-demo.json`, and stops both processes in a `finally` block. A mismatch exits non-zero.

## Release-freeze rerun

The demo was rerun on the Apache-2.0 licensed tree on 2026-08-10. JSON-RPC and
HTTP+JSON again returned `TASK_STATE_COMPLETED` with
`inventory:widget-cp0:available` directly and through KIN; both equivalence
checks passed and both fixture listeners were stopped.
