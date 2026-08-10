# CP0 Transparent A2A Streaming

## Contract

KIN treats an A2A SSE response as an opaque application-byte stream. It does not parse, synthesize, coalesce, reorder, retry, or reinterpret events. This applies to:

- JSON-RPC `SendStreamingMessage` and `SubscribeToTask`;
- HTTP+JSON `POST /message:stream`;
- HTTP+JSON `GET|POST /tasks/{id}:subscribe`.

The gateway forwards the upstream status and allowlisted protocol headers, emits downstream response start before consuming the upstream body, then awaits each downstream send before requesting the next upstream chunk. This is the backpressure boundary; the gateway does not read the entire stream into memory.

`stream_read_timeout_seconds` is an inter-event/read timeout, defaulting to 30 seconds. It begins only while awaiting the next upstream chunk, not while a slow downstream consumer is processing the previous chunk. A timeout or origin read failure terminates the downstream connection. KIN never appends an error or completion event after response headers have started.

Downstream cancellation closes the upstream response and HTTP client in a `finally` path. Normal origin termination closes the same resources. External `Authorization` remains outside the forwarded header allowlist; the request-time upstream credential provider supplies customer-local authority independently.

## Capability projection

The mirrored Agent Card advertises `streaming: true` only when the protected upstream advertises it. Push notifications, extended Agent Card support, and arbitrary upstream extensions remain removed because CP0 does not implement those surfaces.

## Acceptance evidence

`tests/contract/test_sse_gateway.py` proves:

- official SDK streaming event sequence through JSON-RPC and HTTP+JSON;
- exact application bytes and IDs for 100 consecutive events;
- malformed framing and a 64 KiB event pass unchanged;
- no upstream body is consumed before downstream response start;
- slow-consumer backpressure and no duplicate events;
- downstream disconnect closes the in-flight upstream stream;
- abrupt origin failure and inter-event timeout propagate with no synthetic terminal event;
- JSON-RPC and REST task-subscription routes use the streaming path.

The same suite is required on Python 3.11 and 3.12. Network-level integration remains part of the final CP0 canonical demo/TCK record; ASGI contract tests directly avoid the buffering behavior of test HTTP transports when proving stream timing.
