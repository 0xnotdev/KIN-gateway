# System Design — V1
**Status:** Finalized for build — companion to PRD-v1-personal-agent-network.md
**Scope:** 2 agents, 2 independent systems (2 laptops), real internet boundary

---

## 1. Architecture overview

Four components, three of them genuinely separable rather than one fused blob — this is what lets KIN integrate with wherever someone's agent already lives (local process, cloud workspace, hybrid, an existing autonomous cluster), instead of forcing every agent to be rebuilt inside KIN.

- **KIN CLI** — the terminal UX (like Claude Code/opencode/Codex). A thin client. Talks to a KIN node — usually running locally on the same machine for V1's pilot, but architecturally, it could point at a remote node instead (cloud-hosted), without changing the CLI at all.
- **KIN node** — protocol adapter + identity + messaging: everything in the protocol contract (section 4). This is what's actually reachable over the internet via Cloudflare Tunnel and what the other person's node talks to.
- **Agent backend (pluggable)** — whatever actually reasons and produces a response. The node talks to it through one small, documented interface (1.1 below). V1 ships exactly **one** reference backend (a provider-agnostic LLM call, embedded in the node process) — proving the seam works — without taking on the real scope of supporting many agent frameworks in V1 itself.
- **Directory + relay service** (one hosted instance for V1; federation is a named V3+ item in vision-roadmap.md):
  1. **Directory**: maps a chosen username to a public key and current reachable address. Used once at first contact.
  2. **Relay/mailbox**: when the recipient is offline, holds an end-to-end-encrypted message for up to 7 days, then deletes it if never fetched. It cannot read message content — it stores and forwards opaque, encrypted blobs only.
  At 2-user pilot scale, this comfortably fits free hosting tiers (Fly.io, Render, Railway) — no cost expected for V1.

Why layer it this way: either system's internals can change completely — including swapping what actually produces a response — without breaking the other side, as long as the node still speaks the same protocol contract.

### 1.1 Agent backend interface (the pluggable seam)

The node calls the backend with one simple shape, regardless of what's behind it:

```json
// Request (node -> backend)
{
  "task_goal": "string",
  "context": { "...": "..." },
  "conversation_history": ["...prior messages in this task..."]
}
// Response (backend -> node)
{
  "reply": "string or structured proposal",
  "message_type": "proposal | counter_proposal | question | answer | confirmation"
}
```

For a **local** backend (V1's reference implementation), this is a call through a thin, provider-agnostic layer — configurable to Anthropic, OpenAI, Google, or others, rather than hardcoded to one provider. For a **remote** backend (someone's existing LangGraph app, a Bedrock Agent, a whole cluster), this is the same request/response shape called as a webhook. Same interface either way; the node doesn't need to know or care which.

**Context/memory isolation guarantee (explicit, not incidental):** a backend call only ever receives the goal, context, and conversation history belonging to *that specific task* — never another task's history, another contact's data, or anything outside the active negotiation. This was already true by construction (each call is built fresh from one task's stored rows), but is now a named, permanent interface contract, not an implementation detail that could quietly erode as the roster/multi-agent work in the roadmap proceeds.

### 1.2 Relationship to A2A/ACP (explicit, so this is never ambiguous later)

KIN implements a **custom protocol**, not the actual A2A or ACP specifications. Two concepts are borrowed because they're good ideas — the Agent Card (discoverable capability document) and the Task lifecycle (`submitted → working → input-required → completed/failed`) — but the wire format, fields, identity model, offline relay, and autonomy enforcement are all KIN's own design, built specifically around requirements A2A/ACP don't address (personal identity without an enterprise identity provider, store-and-forward for offline recipients, graduated human autonomy). A KIN node can currently only interoperate with another KIN node — not with third-party A2A-compliant agents. Real A2A compliance is a deliberate, named possibility for later (see vision-roadmap.md) if wider agent-ecosystem interoperability ever becomes a goal — it was consciously not chosen for V1.

## 2. Technology stack (concrete choices, with reasoning)

| Layer | Choice | Why |
|---|---|---|
| Language / API framework | Python 3.11+, FastAPI | Agreed earlier — best-documented ecosystem for agent protocols; async support built in |
| HTTP client (node-to-node, node-to-relay) | `httpx` (async) | Standard, async-native, pairs naturally with FastAPI |
| Signing / key pairs | `cryptography` (Ed25519) | Small, fast, well-audited; Ed25519 is the modern standard for signing (used by SSH, TLS certs, etc.) |
| Recovery phrase | `mnemonic` (BIP39 wordlists) + HKDF to derive the Ed25519 seed | Same proven mechanism as crypto wallets; no need to invent our own word list or derivation scheme |
| OS keychain access | `keyring` | Cross-platform (macOS Keychain, Windows Credential Manager, Linux Secret Service) behind one API |
| LLM provider abstraction | LiteLLM (or equivalent thin unifying layer) | Lets the reference backend support Anthropic/OpenAI/Google/etc. through one call shape |
| Local storage | SQLite, sensitive columns encrypted using a key from the OS keychain | File-based, zero-ops, fits a single-user local app; encryption key never touches disk in plaintext |
| CLI / terminal UX | `Typer` (commands) + `Rich` (streaming output) + `prompt_toolkit` (interactive REPL) | Same category of tools real CLI agent harnesses use for a responsive, Claude-Code-like feel |
| Tunnel automation | `cloudflared` binary, managed as a subprocess (auto-installed if missing) | Free tier, no router config, gives a stable public HTTPS URL automatically |
| Relay/directory service | FastAPI + SQLite (or Postgres if the free tier prefers it) | Same stack as the node — one less thing to context-switch on while learning |

## 3. Local data model

Each KIN node keeps its own local SQLite database — nothing shared with the other side except what the protocol explicitly sends.

```
identity (single row)
  username            TEXT
  public_key          TEXT
  keychain_ref        TEXT   -- reference into OS keychain, never the raw private key
  protocol_version    TEXT

contacts
  username            TEXT PRIMARY KEY
  display_name        TEXT
  public_key          TEXT
  endpoint            TEXT
  autonomy_level      TEXT   -- "always_ask" | "auto_relay_info"
  fingerprint_verified_at   TIMESTAMP

tasks
  task_id             TEXT PRIMARY KEY
  contact_username    TEXT REFERENCES contacts(username)
  goal                TEXT
  context_json        TEXT
  status              TEXT   -- submitted | working | input-required | completed | failed
  created_at          TIMESTAMP
  updated_at          TIMESTAMP
  result_json         TEXT   -- nullable until completed

messages
  message_id          TEXT PRIMARY KEY
  task_id             TEXT REFERENCES tasks(task_id)
  from_username       TEXT
  content             TEXT
  message_type        TEXT
  created_at          TIMESTAMP
  signature           TEXT
```

The relay/directory service's own store is deliberately thinner — it never needs a `messages`-shaped table with real content, only:

```
directory_entries: username, public_key, endpoint, registered_at
mailbox: message_id (primary key), username, encrypted_blob, received_at, expires_at   -- deleted at 7 days or on fetch
```

## 4. The protocol contract (the critical artifact)

This is what both systems must implement identically. If code and this doc disagree, the doc wins until deliberately changed together.

### 4.1 Agent Card (discovery)

Each system exposes, unauthenticated, at `GET /.well-known/agent-card.json`:

```json
{
  "name": "string — display name of this agent",
  "username": "string — the claimed, directory-registered handle",
  "public_key": "string — this agent's public key",
  "endpoint": "https://<tunnel-url>/",
  "capabilities": ["info_request", "negotiation"],
  "protocol_version": "string — e.g. 0.1.0"
}
```

If two nodes' `protocol_version` values are incompatible, the receiving node refuses the request with a clear "protocol version mismatch" message — never a confusing generic failure.

### 4.2 Identity, username, and first-contact verification

1. On first run, KIN generates a 12-word recovery phrase (BIP39-style, human-writable) and **deterministically derives** the key pair from it. The phrase is shown once with a clear "write this down, it's the only way to recover your identity" warning, and KIN requires re-typing back 2 randomly-selected words before proceeding, to confirm it was actually captured. Running `kin restore <phrase>` on any machine regenerates the exact same key pair and identity. We never store or see this phrase.
2. The human picks a username, registered against their public key with the directory service (first-come, permanent — a username can never be reassigned to a different key once claimed).
3. To contact someone new: look up their username in the directory to get their public key and current endpoint.
4. **First-contact verification (required, not optional):** before the very first message is trusted, KIN displays a short, human-readable word-based fingerprint derived from both public keys (e.g. `correct-harbor-violet-kettle`). Both humans confirm out of band that they see the same fingerprint. Any `/ask` attempt before this step is a hard block — no override.
5. Once verified, both sides save each other as a **contact** — this step never repeats.
6. Every message after this is signed with the sender's private key and verified against the stored public key for that contact. A message that fails verification is rejected outright and reported distinctly (4.7).

### 4.3 Task lifecycle

A **Task** is the unit of cross-agent work, living inside a persistent per-contact thread. Multiple tasks can exist within one contact's thread over time.

`submitted → working → input-required → completed | failed`

- `submitted`: created, not yet processed.
- `working`: the receiving node is reasoning about it (or it's queued at the relay, waiting for the recipient to come online).
- `input-required`: a drafted response exists and needs the human's explicit approval before it's sent (see 4.10).
- `completed` / `failed`: terminal states — `failed` includes "recipient unreachable," "no agreement reached," and "verification failed," shown verbatim, never silently swallowed.

**Negotiation termination:** a fixed round limit (default 10 proposal/counter-proposal exchanges) is the hard stop. Within that limit, either node can also bail early and report `failed` if it detects the exchange isn't converging. Either way, the human sees exactly why it ended.

### 4.4 Endpoints (both systems implement all of these)

**Create a task**
```
POST /tasks
Headers: X-Signature: <sender's signature over the body>
Body:
{
  "goal": "string — what the requesting agent wants",
  "context": { "...": "..." },
  "requester_username": "string"
}
Response: { "task_id": "uuid", "status": "submitted" }
```
If the recipient's endpoint is unreachable, the protocol adapter automatically falls back to POST-ing the same (encrypted) payload to the relay's mailbox for that username, rather than failing immediately.

**Send a message within an existing task**
```
POST /tasks/{task_id}/messages
Headers: X-Signature: <sender's signature over the body>
Body:
{
  "from_username": "string",
  "content": "string or structured proposal",
  "message_type": "proposal | counter_proposal | question | answer | confirmation"
}
Response: { "status": "working | input-required | completed | failed" }
```

**Check task status** (also what a human inspects to see the real transcript)
```
GET /tasks/{task_id}
Response:
{
  "status": "...",
  "history": ["...ordered list of all messages exchanged..."],
  "result": { "...": "final outcome, only present when completed" }
}
```

**Fetch anything waiting at the relay** (called automatically when KIN starts up)
```
GET /relay/inbox
Response: { "messages": ["...encrypted blobs addressed to this username..."] }
```

### 4.5 Autonomy enforcement (2-level, V1)

Per contact, configurable, default **"always ask"**:
- **Always ask** — any proposal, answer, or outcome is shown to the human for explicit confirmation before it's sent to the other agent as final.
- **Auto-relay info only** — the agent may autonomously answer a scoped factual question and relay a received answer back, but may never commit to, agree to, or finalize anything without explicit confirmation.

This check happens in the **node**, not the pluggable agent backend, since the backend could be a third-party agent system we don't control. The node enforces policy regardless of what produced the proposed response, and this is also the enforcement point for prompt-injection defense: an inbound message can request things, but it cannot grant itself permissions beyond what the receiving human configured.

### 4.6 Relay retention policy

Undelivered messages are held by the relay, encrypted, for 7 days, then permanently deleted if never fetched.

### 4.7 Distinct failure states (never one generic error)

- **Queued, not lost** — recipient hasn't come online yet; message is safely waiting at the relay.
- **Unknown username** — no such identity in the directory.
- **Signature verification failed** — a real security event, surfaced distinctly from ordinary connectivity issues.

### 4.8 Terminal transparency level (V1)

The live view during a negotiation shows the **structured exchange only** (proposal → counter-proposal → outcome) — not the agent's raw internal reasoning trace. Full transcripts remain inspectable via `GET /tasks/{id}` at any time.

### 4.9 Relay contract (distinct from KIN-to-KIN)

```
POST /directory/register   { username, public_key, endpoint }
GET  /directory/lookup/{username}   -> { public_key, endpoint }
POST /relay/mailbox/{username}   { encrypted_blob }
GET  /relay/inbox   (authenticated as the requesting username)  -> { messages: ["...encrypted blobs..."] }
```

### 4.10 New-task auto-draft behavior

When a new task arrives from an already-verified contact, the node passes it to the agent backend immediately and gets a **drafted** response — it does not wait for the human to be present to start reasoning. That draft is held (`input-required`) and never sent until the human explicitly approves it.

### 4.11 Multi-profile support (development convenience)

KIN supports multiple local identities via profiles (`kin --profile <name>`), each with its own data directory. Lets both sides of a conversation be developed and tested on a single machine before needing two physical laptops.

### 4.12 Secret storage (BYOK, keychain-backed)

Both local secrets — the private key and the LLM provider API key — are stored via the OS's built-in secure keychain, never in a plain config file. BYOK is provider-agnostic: each person supplies and pays for their own key, for whichever provider they choose, with no shared or hosted billing.

## 5. Example flow — UC-1 (negotiated agreement), including the offline case

1. In your KIN terminal, you state a goal and preference — e.g. "agree with the other side on a number between 1 and 10, I'd prefer close to 7."
2. Your node creates a Task via `POST /tasks` on the other system's endpoint. If reachable, it goes directly; if not, it's queued at the relay automatically.
3. Whenever the other system comes online, it fetches anything waiting (`GET /relay/inbox`), and its agent backend drafts a response based on its own human's stated preference — held for approval per 4.10.
4. The two sides go back and forth (`POST /tasks/{id}/messages`) — proposing, countering — until they converge, or explicitly report they couldn't agree.
5. Task reaches `completed` or `failed`. Both humans can inspect the full `history` in their own terminal at any time.

## 6. Non-functional notes

- **Observability**: the `history` array on every task IS the audit log, built into the contract itself.
- **Reliability**: protocol calls need timeouts and retries; offline recipients fall back to the relay automatically rather than hanging or failing loudly.
- **Security**: per-message signatures (not a shared secret), mandatory first-contact fingerprint verification, node-side policy enforcement against prompt injection, and keychain-backed secret storage — layered, not a single point of trust.

## 7. Repo structure

Three repos, matching the three independently-versioned pieces:

- **`kin-node`** — the CLI + node + reference agent backend. This is the app installed independently on each laptop. One shared open-source codebase (like WhatsApp: one app, installed on two phones) — "independent systems" means independent running instances with their own identity/data/process, not literally different source code, since you're building both sides yourself.
- **`kin-relay`** — the directory + relay service, deployed once, hosted centrally for the pilot.
- **`kin-protocol-spec`** (optional but recommended) — this document, versioned, as the source of truth both `kin-node` and `kin-relay` are built against — useful even solo, and essential if this ever has other contributors or implementations.

## 9. Packaging & distribution

**Primary install path** — a single shell command:
```
curl -fsSL https://kin.dev/install.sh | sh
```
This script: checks for Python (guides installation if missing), installs the KIN CLI via `pipx` (isolated, no dependency clashes with other Python projects on the machine), and installs the `cloudflared` binary if not already present — covering the one non-Python dependency the project has. Hosted as a short, plainly readable script (not obfuscated), since `curl | sh` is a well-known trust concern and the standard mitigation is keeping it inspectable.

**Alternative path** for people who prefer standard tooling over piping a remote script: `pipx install kin-cli` directly. Same end result, for anyone already comfortable with Python packaging.

## 10. Next steps

1. Confirm this document as final for Milestone 0.
2. Scaffold `kin-node` (repo, dependencies, empty FastAPI app, CLI entry point) and `kin-relay` (repo, minimal directory+mailbox endpoints).
3. Design the terminal UX in detail — exact command names, prompts, and what streaming output looks like.
4. Build the walking skeleton (Milestone 0): identity generation, directory registration, a trivial info-request task, and the offline relay fallback — proven end to end before any real negotiation logic.
