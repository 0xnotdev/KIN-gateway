# KIN Gateway

KIN Gateway is a customer-local enforcement seam for external A2A agents. The
CP0 data plane transparently proxies the frozen A2A 1.0 profile while keeping
external caller credentials separate from customer-local upstream authority.

## Current status

CP0 is complete and frozen under the Apache License 2.0. The annotated
`v0.0.1-cp0` tag identifies the release tree after the complete licensed-tree
regression, live TCK profile, canonical demo, and dual-interpreter license audit.

Read these documents before changing the build:

- [`scope.md`](scope.md) is the frozen product and checkpoint authority.
- [`CP0_CHECKPOINT.md`](CP0_CHECKPOINT.md) records exactly what is built, the
  verification matrix, evidence index, exclusions, and remaining release work.
- [`A2A_COMPATIBILITY.md`](A2A_COMPATIBILITY.md) defines the public CP0 protocol
  contract and conformance claims.
- [`UPSTREAM_KIN_V1_1_SNAPSHOT.md`](UPSTREAM_KIN_V1_1_SNAPSHOT.md) records the
  immutable source import.
- [`docs/adr/0002-apache-2.0-licensing.md`](docs/adr/0002-apache-2.0-licensing.md)
  records the licensing authority and project-license decision.

CP0 includes public Agent Card mirroring, JSON-RPC and HTTP+JSON forwarding,
opaque SSE streaming, request-time customer-local credential selection, a
separate authenticated admin application, and observer-only external task
sessions. It intentionally does not include identity verification, grants,
policy decisions, approvals, evidence chains, OIDC, PartnerGrant, push
notifications, extended Agent Cards, or gRPC.

## Verify the gateway

KIN Gateway supports Python 3.11 and 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest -q tests\contract
.\.venv\Scripts\python scripts\audit_cp0_licenses.py `
  --output .artifacts\license-audit.json
.\scripts\run_cp0_demo.ps1 -Python ".\.venv\Scripts\python.exe"
```

The canonical demo starts loopback-only reference and gateway listeners, calls
the same unmodified `a2a-sdk==1.1.2` agent directly and through KIN over both
supported bindings, writes evidence under `.artifacts/`, and cleans up both
listeners. The pinned TCK procedure and its separate-checkout command are in
[`docs/baseline/GATE-004-A2A-TCK.md`](docs/baseline/GATE-004-A2A-TCK.md).

## Repository layout

- `kin_gateway/`: CP0 gateway implementation.
- `tests/contract/`: frozen protocol, security, lifecycle, and TCK contracts.
- `scripts/`: reproducible CP0 demo and selected-profile TCK runners.
- `docs/`: architecture, security, protocol, baseline, and captured evidence.
- `kin-node/` and `kin-relay/`: imported KIN v1.1 baseline retained for
  provenance and regression verification; the gateway does not depend on its
  legacy session engine.

CP1 begins with failing deterministic policy-semantic tests. Identity-provider
or OIDC integration is not the first CP1 implementation step.
