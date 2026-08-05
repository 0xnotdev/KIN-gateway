# Privacy model
Each node owns its local profile. Private keys, provider credentials, private
notes, local quality signals, unreviewed Context Pantry references, policy state,
and private peer-cost observations are local-only. A private note crosses the
boundary only when its exact text is confirmed and sent as a new signed message.

Peer-visible envelopes contain reviewed collaboration content, actor, timestamp,
protocol/schema version, content hash, and signature/provenance. The relay stores
opaque ciphertext plus the routing metadata required to deliver it. Relay
operators can observe sender/recipient mailbox identifiers, size, and timing, but
not plaintext.

KIN does not request or transmit raw chain-of-thought, hidden prompts,
credentials, or arbitrary local files. Export defaults exclude private notes and
applies deterministic redaction. Artifact import and patch application are
separate owner actions.
