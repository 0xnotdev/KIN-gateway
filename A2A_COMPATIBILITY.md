# KIN Gateway A2A Compatibility Profile

- Gateway release: v0.1 paid-pilot profile
- A2A specification: 1.0
- Specification tag: `a2aproject/A2A@v1.0.0`
- Specification commit: `173695755607e884aa9acf8ce4feed90e32727a1`
- Python SDK: `a2a-sdk==1.1.2`
- SDK tag/commit: `a2aproject/a2a-python@v1.1.2` / `3e6fa6a41d64f0581202df214a0515a0b0194832`
- TCK pin for initial harness: `a2aproject/a2a-tck@5996b79f9cefa6fc390980e383e358a66fb9e49e`

This file is a release contract. “A2A compatible” means only the operations and bindings marked supported below. A skipped TCK case must be listed with its reason; it may not disappear silently.

## Bindings

| Binding | v0.1 status | Contract |
|---|---|---|
| JSON-RPC 2.0 over HTTP(S) | Supported | A2A 1.0 PascalCase methods and `A2A-Version: 1.0`; JSON request/response and SSE streaming. |
| HTTP+JSON/REST | Supported | A2A 1.0 REST endpoints and `A2A-Version: 1.0`; JSON request/response and SSE streaming. |
| gRPC | Unsupported | Add only after an approved scope update and design-partner requirement. |
| A2A 0.3 compatibility | Unsupported | No implicit downgrade. A later release may add an explicit, tested compatibility profile. |

## Discovery and Agent Card

| Feature | v0.1 status | Contract |
|---|---|---|
| Public Agent Card | Supported | Served from the standard well-known location and generated from a validated upstream card. |
| Interface rewriting | Supported | Public JSON-RPC/REST URLs point to KIN; private upstream URLs and credentials never appear. |
| Descriptive fields | Supported | Preserve validated name, description, version, approved skills, modes, and capabilities. |
| Security declaration | Supported | Advertise only the customer-configured external OIDC/OAuth/mTLS requirements. |
| Upstream card hash/version | Supported | Record in configuration/evidence so the public card can be traced to its source. |
| Authenticated extended Agent Card | Unsupported | `GetExtendedAgentCard` and REST `/extendedAgentCard` are not in v0.1. |
| Agent Card signatures | Pass-through only when validated | Gateway signing/rewriting semantics require a later explicit profile before being advertised. |

## Operations

| Function | JSON-RPC | REST | v0.1 status and semantics |
|---|---|---|---|
| Send message | `SendMessage` | `POST /message:send` | Supported. Initiate or continue a task; preserve Task or Message result. |
| Send streaming message | `SendStreamingMessage` | `POST /message:stream` | Supported. Preserve SSE event order, payload, terminal state, errors, and disconnect behavior. |
| Get task | `GetTask` | `GET /tasks/{id}` | Supported. CP1 binds visibility to authenticated principal, tenant, and immutable grant version. |
| List tasks | `ListTasks` | `GET /tasks` | Supported. CP1 filters by authenticated principal/tenant; never list another caller's tasks. |
| Cancel task | `CancelTask` | `POST /tasks/{id}:cancel` | Supported. Ownership is authorized before forwarding; upstream cancel semantics are preserved. |
| Subscribe to task | `SubscribeToTask` | `POST /tasks/{id}:subscribe` | Supported for non-terminal streaming tasks; first event and subsequent SSE order are preserved. |
| Push notification configuration | Create/Get/List/Delete methods | `/tasks/{id}/pushNotificationConfigs...` | Unsupported. Return binding-correct unsupported-operation behavior without forwarding. |
| Extended Agent Card | `GetExtendedAgentCard` | `GET /extendedAgentCard` | Unsupported. Return binding-correct unsupported-operation behavior. |

## Authentication and authorization

- Missing or invalid external authentication is rejected in the native binding.
- OIDC bearer JWT and optional mTLS principal binding are the v0.1 external schemes.
- Every operation is authorized; task/list/cancel/subscribe access is scoped to the authenticated caller, tenant, and applicable Partner Grant.
- Request-body identity, organization, or purpose claims are never sufficient authority.
- External caller credentials are not forwarded upstream by default.
- The no-invitation path is canonical: an administrator configures issuer/client identity and grant, then the existing external A2A client calls KIN.

### Authorization-denial semantics

- REST: HTTP 403 with an A2A-compatible error payload.
- JSON-RPC: binding-correct JSON-RPC authorization error using the pinned SDK/spec error representation.
- Authentication failure is distinct from authorization denial and uses the binding-correct unauthenticated response.
- A denial never reveals whether an unauthorized task or resource exists.

## Streaming contract

- KIN does not synthesize, coalesce, reorder, or reinterpret upstream A2A events in transparent mode.
- The first `SubscribeToTask` event represents current task state as required by A2A 1.0.
- Client disconnect propagates upstream and releases gateway resources.
- Upstream disconnect, malformed event, timeout, and cancellation map to documented binding-correct behavior and an evidence event.
- Shadow mode leaves stream status, headers, event sequence, event bytes/semantics, and termination behavior unchanged except for declared observability headers, if any.

## Upstream compatibility

The protected upstream must implement the same A2A 1.0 operation/binding being exposed. KIN does not translate a non-A2A proprietary upstream into A2A in v0.1. Unsupported upstream capabilities are removed from the mirrored Agent Card.

## TCK accounting

`tests/contract/tck-manifest.yaml` will map every pinned TCK case to `pass`, `expected-unsupported`, or a tracked defect. Every `expected-unsupported` entry must cite the unsupported feature in this document. The manifest and test report are required CP0 acceptance artifacts.

## Upgrade rule

Changing the specification, SDK, TCK pin, supported operation set, error mapping, or binding requires this document and its contract tests to change in the same release. No dependency updater may advance the A2A SDK independently of this profile.
