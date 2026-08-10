# KIN Gateway CP0 Checkpoint

Checkpoint date: 2026-08-10

Scope authority: `scope.md`

Target: CP0 — Foundation and Transparent A2A

Release status: **complete and frozen; annotated release marker `v0.0.1-cp0`**

## Executive state

KIN Gateway now provides the complete scoped transparent A2A enforcement seam:

```text
unmodified official A2A client
             |
             v
public KIN data plane
  - mirrored public Agent Card
  - A2A 1.0 version boundary
  - external credential stripping
  - customer-local upstream credential
  - transparent JSON-RPC
  - transparent HTTP+JSON
  - opaque SSE streaming
  - observer-only task session
             |
             v
unmodified official A2A 1.0 upstream agent
```

The separate private admin plane exists and is authenticated, but CP0 intentionally contains no grants, identity verification, policy engine, revocation, approval, evidence chain, shadow mode, hosted control plane, or PartnerGrant implementation.

The implementation, dual-version contract suites, pinned TCK subset, full TCK accounting, imported KIN regressions, canonical live-network demo, and installed-metadata license audit are complete. The repository owner confirmed licensing authority over all imported KIN contributions, ADR 0002 records the Apache-2.0 decision, and the licensed tree passed the complete release rerun before freeze.

## Checkpoint dashboard

| Gate | State | What is complete | Remaining |
|---|---|---|---|
| GATE-001 — immutable import | Complete | Original clone is clean at source commit `58258fb037ea49f23d8e572ad7cd9df59ef5e388`, tree `808d495e70f7d03ac75f2ecaff50b29280fed494`; annotated `kin-v1.1-import` peels to the same commit/tree. | None. |
| GATE-002 — baseline/license | Complete | Authority is recorded; root `LICENSE`/`NOTICE` are present; all three project distributions declare `Apache-2.0`; exhaustive installed-metadata audits pass on Python 3.11/3.12; licensed-tree regressions are green. | None. Third-party dependencies retain their own licenses. |
| GATE-003 — invariants ADR | Complete | A2A public protocol, local authority, credential separation, listener separation, scope governance, and no legacy-session dependency are locked. | None. |
| GATE-004 — SDK/TCK/profile | Complete | SDK/spec/TCK pins, immutable collection hash, exhaustive 265-case accounting, live-network runner, 68/68 selected profile, and raw reports exist. | Upstream TCK/SDK limitations remain documented, not hidden. |
| GATE-005 — AgentCardMirror | Complete | SSRF/rebinding defenses, same-origin redirects, limits, SDK validation, public allowlist, private-reference removal, hashes, ETag, and cache are proven. | None in CP0. |
| GATE-006 — JSON-RPC | Complete | Official client → KIN → official upstream is green; unsupported version stops before upstream. | None in CP0. |
| GATE-006A — credentials | Complete | Exactly three request-time providers; external authority is structurally unavailable to upstream context; missing secrets fail before upstream. | Workload federation/token exchange deferred. |
| GATE-006B — admin plane | Complete | Separate loopback/private application and listener defaults; token/mTLS bootstrap authentication; public `/admin` absent; canaries never forwarded/logged. | SSO/RBAC deferred. |
| GATE-007 — REST/SSE | Complete | Buffered REST, binding-correct known exclusions, opaque SSE, bytes/order/IDs, backpressure, disconnect, timeout, origin failure, and subscription paths are proven. | Push delivery/configuration, extended cards, and gRPC remain excluded. |
| GATE-008 — task session | Complete | Exact nine-field immutable record, deterministic credential-independent request hash, task-ID observation for buffered JSON, stream outcomes, and fail-open observer isolation are proven. | Identity/grant/policy/evidence fields start only in later checkpoints. |
| GATE-014 — demo | Complete | Official client calls `inventory.lookup` directly and through KIN over both bindings with equivalent completed state/artifact. | None in CP0. |
| GATE-015 — practitioner demos | Planned | Not a CP0 customer gate; CP0 customer gate is `None`. | Run as CP1 customer evidence before CP2 feature work. |

## Frozen public compatibility profile

| Dimension | CP0 contract | Evidence |
|---|---|---|
| Specification | A2A 1.0, no implicit 0.3 downgrade | `A2A_COMPATIBILITY.md` |
| SDK | `a2a-sdk==1.1.2` | `pyproject.toml`; direct/proxy contract tests |
| Discovery | Standard public well-known Agent Card, protected mirrored projection | Agent Card contract suite; live TCK 9/9 |
| JSON-RPC | `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask` | Official-client and raw transparent proxy tests |
| HTTP+JSON | send/stream, get/list/cancel/subscribe routes | Official-client and TCK/profile tests |
| Streaming | Opaque bytes; no parse/synthesis/retry/reorder; bounded inter-event timeout | `CP0-TRANSPARENT-STREAMING.md`; SSE contract suite |
| Credentials | External credential stripped; customer-local upstream authority selected at request time | `CP0-UPSTREAM-CREDENTIALS.md`; canary tests |
| Admin | Separate application/listener, loopback default, token or serving-stack mTLS | `CP0-ADMIN-PLANE.md`; negative tests |
| Session observation | Exact CP0 facts only; no authorization meaning | `CP0-EXTERNAL-TASK-SESSIONS.md`; observer tests |
| Explicit exclusions | gRPC, push notification config/delivery, extended Agent Card, identity, grants, policy, approval, evidence chain | compatibility manifest and scope |

## Final verification matrix

| Suite | Python 3.11 | Python 3.12 | Status |
|---|---:|---:|---|
| Gateway contract suite | 51 passed | 51 passed | Green |
| Imported `kin-node` | 1,617 passed; 9 deselected; 101 snapshots | 1,617 passed; 9 deselected; 101 snapshots | Green |
| Imported `kin-relay` | 12 passed | 12 passed | Green |
| Selected live A2A TCK profile | 68 passed on Python 3.11.9 | Contract behavior separately green on gateway 3.12 | Green |
| Canonical direct/proxy demo | JSON-RPC and HTTP+JSON equivalent | Uses pinned 1.1.2 runtime | Green |
| Installed license metadata | 105 distributions; no missing declaration; three KIN packages `Apache-2.0` | 102 distributions; no missing declaration; three KIN packages `Apache-2.0` | Green |

Known non-failing output:

- 100 upstream A2A protobuf deprecation warnings per gateway matrix run;
- one imported FastAPI/Starlette `httpx` deprecation warning per KIN node/relay suite.

## TCK accounting

The TCK claim is intentionally bounded. KIN does **not** claim full 265-case TCK conformance.

| Disposition | Count | Meaning |
|---|---:|---|
| Selected and passing | 68 | Exact node IDs executed through the live KIN fixture; all green. |
| Expected unsupported | 108 | Frozen-profile exclusions or capability-inapplicable tests. |
| Tracked TCK/SDK defect | 89 | Pinned TCK endpoint/SUT reproducibility gaps or released SDK behavior outside the selected profile. |
| Unaccounted | 0 | The verifier fails if any case is unmatched. |

The most material limitation is the pinned TCK JSON-RPC client resolving `POST "/"`, which discards a valid non-root Agent Card endpoint path. KIN retains `/a2a/jsonrpc` because that is the frozen public contract and the released official SDK consumes the full interface URL correctly. The pinned TCK's generated Python SUT also lacks a companion SDK commit and cannot import against the tested released versions. Full details and raw evidence are in `docs/baseline/GATE-004-A2A-TCK.md`.

## Canonical demo result

For `widget-cp0`, both direct and through-KIN calls returned:

```text
state:    TASK_STATE_COMPLETED
artifact: inventory:widget-cp0:available
```

This passed independently over JSON-RPC and HTTP+JSON. Server-generated task IDs differ by design and are not part of semantic equivalence. The mirrored public Agent Card rewrites both interface URLs to KIN and carries its deterministic public ETag plus the upstream normalized-card SHA-256.

## Security properties proven

- Private, loopback, link-local, metadata, RFC1918, and IPv6-local Agent Card targets fail closed unless the exact host is explicitly trusted.
- All DNS answers are validated and the connection is pinned to the validated address while preserving Host/SNI.
- Redirects remain bounded and same-origin.
- Oversized or slow Agent Cards fail closed before parsing/publication.
- Upstream URL, provider, security declarations, signatures, credentials, and unapproved skills cannot survive public projection.
- External bearer credentials cannot enter upstream request context and are replaced by customer-local authority.
- Admin credentials cannot authorize the data plane, reach upstream, or appear in captured logs.
- SSE application bytes, event IDs, order, terminal data, malformed framing, and large events are not rewritten.
- Client cancellation closes upstream; origin failure/timeout never receives a synthetic completion event.
- Session observation cannot change a buffered response or decide proxy behavior.
- Unsupported known REST features return binding-correct A2A error payloads without forwarding.

## Evidence index

- `UPSTREAM_KIN_V1_1_SNAPSHOT.md` — source provenance and immutable import.
- `docs/baseline/GATE-002-BASELINE.md` — original dual-version baseline.
- `docs/baseline/GATE-002-DEPENDENCY-LICENSES.md` — dependency and project license audit.
- `docs/baseline/GATE-002-LICENSING-AUTHORITY.md` — founder authority evidence.
- `docs/adr/0002-apache-2.0-licensing.md` — project-license decision.
- `docs/baseline/evidence/gate-002/` — exhaustive Python 3.11/3.12 installed-metadata evidence.
- `docs/adr/0001-gateway-architecture-invariants.md` — locked boundaries.
- `A2A_COMPATIBILITY.md` — release compatibility contract and test index.
- `tests/contract/tck-manifest.yaml` — selected TCK node IDs and exhaustive exclusions.
- `docs/baseline/GATE-004-A2A-TCK.md` — TCK procedure, results, and upstream defects.
- `docs/baseline/evidence/gate-004/` — full diagnostic, exact accounting, and selected-profile reports.
- `docs/baseline/GATE-014-CANONICAL-DEMO.md` — demo contract and reproduction.
- `docs/baseline/evidence/gate-014/inventory-lookup-demo.json` — captured live result.
- `docs/security/CP0-UPSTREAM-CREDENTIALS.md` — authority separation.
- `docs/security/CP0-ADMIN-PLANE.md` — management boundary.
- `docs/protocol/CP0-TRANSPARENT-STREAMING.md` — SSE contract.
- `docs/protocol/CP0-EXTERNAL-TASK-SESSIONS.md` — observer contract.

## Freeze record

- The repository owner confirmed authority to license every imported KIN contribution under Apache-2.0; the evidence and decision are recorded separately.
- The canonical Apache-2.0 `LICENSE` and project `NOTICE` are present at the repository root.
- `kin-gateway`, `kin-cli`, and `kin-relay` installed metadata all report `License-Expression: Apache-2.0` and include `LICENSE` and `NOTICE`.
- Fresh Python 3.11.9 and 3.12.13 environments reproduced the complete gateway, node, relay, license, live TCK, and canonical-demo gates shown above.
- The immutable reference clone remained clean at the recorded source commit/tree, the release worktree was clean before tagging, and no fixture listeners remained.
- Annotated tag `v0.0.1-cp0` is the immutable CP0 release marker. CP1 work is strictly after that tag.

The first CP1 commit must contain failing deterministic policy-semantic tests for unknown/known principals, relationship and grant state, expiry/revocation, target/skill scope, task ownership, and shadow non-interference. It must not begin with OIDC implementation.
