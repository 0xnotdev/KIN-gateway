# CP0 External Task Sessions

## Boundary

`ExternalTaskSession` is an observer-only completion record beside the A2A proxy path:

```text
A2A request -----> transparent proxy -----> protected A2A upstream
       |
       +---------> ExternalTaskSession observer
```

The proxy never converts A2A requests into the imported KIN protocol or calls the legacy KIN session engine. It never reads a decision from the observer. A missing observer is a no-op, and an observer exception cannot change the A2A status, headers, body, stream bytes, or termination behavior.

## Record schema

CP0 records exactly these fields:

| Field | Meaning |
|---|---|
| `session_id` | Unique UUIDv4 for one gateway attempt. |
| `a2a_task_id` | Best-effort task ID from a completed buffered JSON response; otherwise `None`. |
| `transport` | `JSONRPC` or `HTTP+JSON`. |
| `request_method` | JSON-RPC method when present; otherwise the HTTP method. |
| `request_hash` | Deterministic SHA-256 correlation value defined below. |
| `upstream` | Configured upstream origin, with no request query string. |
| `started_at` | Timezone-aware UTC start time. |
| `ended_at` | Timezone-aware UTC completion time. |
| `outcome` | Proxy lifecycle outcome from the closed vocabulary below. |

The bridge does not add principal, organization, partner relationship, grant, purpose, authorization, approval, data-classification, or policy fields in CP0.

## Request hash

The request hash is SHA-256 over canonical JSON containing:

- transport;
- request method;
- raw public path and query target;
- a canonical allowlist of A2A/content-negotiation headers;
- SHA-256 of the raw request body.

Canonical JSON uses sorted keys, UTF-8, and compact separators. External `Authorization` and all non-protocol headers are excluded. The raw request body, raw query values, and external credential are not stored in the session record. Identical protocol requests therefore produce the same request hash even when their external bearer credentials differ, while each attempt receives a distinct session ID.

This hash is a correlation/integrity input only. It is not an authorization decision, identity proof, evidence signature, or replay defense.

## Outcomes

| Outcome | Meaning |
|---|---|
| `forwarded` | An upstream response or complete stream was transparently forwarded. |
| `unsupported_version` | The pinned A2A version check rejected the request before upstream. |
| `unsupported_operation` | The CP0 REST operation allowlist rejected the request before upstream. |
| `upstream_unavailable` | Credential acquisition or initial upstream HTTP transport failed. |
| `upstream_disconnected` | An established upstream stream failed while reading. |
| `upstream_timeout` | The established upstream stream exceeded its inter-event timeout. |
| `client_disconnected` | Downstream cancellation stopped the stream and closed upstream resources. |

An upstream HTTP error status is still `forwarded`: transparent transport succeeded and the original status/body remains authoritative.

## Streaming rule

SSE remains opaque. The observer does not parse events to discover a task ID, terminal state, or error. Consequently `a2a_task_id` is normally `None` for streams. Lifecycle outcomes are derived only from transport completion, cancellation, read failure, or timeout. Session completion occurs from the stream generator's cleanup path after upstream resources are closed.

## Acceptance evidence

`tests/contract/test_external_task_sessions.py` proves the exact schema, deterministic credential-independent hash, distinct UUIDs, JSON-RPC and REST metadata, buffered task-ID observation, byte/status/header equivalence, upstream-failure outcome, and observer-failure isolation.

`tests/contract/test_sse_gateway.py` proves observer outcomes for normal stream completion, downstream disconnect, upstream disconnect, and inter-event timeout while retaining the transparent SSE contract. Both suites are required on Python 3.11 and 3.12.
