# KIN Node

KIN is a terminal-first personal-agent network. Each person runs a local node with their own identity, agent key, contacts, task history, and approval decisions. Nodes exchange signed messages directly when possible and use an end-to-end-encrypted relay mailbox when either side is offline.

## What V1 does

- Creates a recoverable Ed25519/X25519 identity from a 12-word phrase; private keys and BYOK provider keys stay in the OS keychain.
- Registers a permanent username, pairs contacts through the directory, and requires an out-of-band word fingerprint before any message is trusted.
- Drafts replies using an embedded LiteLLM backend or a configured webhook backend; inbound content is explicitly treated as untrusted.
- Keeps humans in control: received agent output becomes a local draft that must be reviewed with `kin respond` before it is sent or finalized.
- Supports multi-turn proposals, counter-proposals, questions, answers, and finalization, with a hard 10-message task limit and an inspectable local transcript.
- Delivers directly to a reachable node, or encrypts and queues the message at the relay for seven days. A relay message is deleted only after the recipient has processed and acknowledged it.

V1 deliberately does **not** execute cross-node tools, access calendars, make payments, or discover arbitrary third-party agent protocols.

## Install for development

Requires Python 3.11+ and a secure OS keychain (Windows Credential Manager, macOS Keychain, or Linux Secret Service/KWallet).

```powershell
cd kin-node
python -m pip install -e ".[dev]"
```

Run a relay separately for local development:

```powershell
cd ..\kin-relay
python -m pip install -e ".[dev]"
uvicorn kin_relay.app:app --port 8000
```

Set `KIN_RELAY_URL` when using a deployed relay; it defaults to `http://localhost:8000`.

## First-use flow

```powershell
# Creates identity, shows and verifies the recovery phrase, then registers the username.
kin init

# Stores a provider key in the OS keychain and selects the default embedded model.
kin configure --provider openrouter --model openrouter/google/gemini-2.5-flash:free

# Make this node reachable. A manually managed HTTPS endpoint is also supported.
kin serve --tunnel
# or: kin serve --host 0.0.0.0 --public-endpoint https://your-node.example

# Pair after comparing the displayed fingerprint out of band.
kin pair other-person

# Send work, inspect drafts/transcripts, and approve the next message.
kin ask other-person "Find an option that works for both of us."
kin fetch
kin tasks
kin status <task-id>
kin respond <task-id>
```

Use `kin --profile alice ...` and `kin --profile bob ...` to run two isolated identities on one machine. `kin restore` prompts for a phrase without putting it in shell history and verifies that it matches the registered username before restoring the keys.

## Operational commands

- `kin contacts` — trusted contacts and their policy.
- `kin contact-policy <username> always_ask|auto_relay_info` — sets the contact policy. `auto_relay_info` can relay only a backend-produced factual `answer` to a received `question`; negotiation and finalization remain human-approved.
- `kin tasks [--status input-required]` — work needing attention and full task list.
- `kin status <task-id>` — transcript, result, and pending draft.
- `kin fetch` — process and acknowledge encrypted offline deliveries.
- `kin serve [--tunnel | --public-endpoint URL]` — run the local node and publish reachability.

## Verification

```powershell
cd kin-node; pytest -q
cd ..\kin-relay; pytest -q
```

The protocol contract and product limits are documented in [`../system-design-v1.1.md`](../system-design-v1.1.md).

## Local two-process smoke test (not yet a real network boundary)

The two-process local smoke test suite (`python -m pytest -q -m smoke -v` or `python scripts/smoke_two_node.py`) proves:
- Real separate OS processes running simultaneously on local TCP sockets.
- Full end-to-end identity initialization, pairing, fingerprint verification, signed request delivery, task drafting, human response, and status completion over real sockets.

What it does **NOT** yet prove:
- A real internet boundary or Cloudflare tunnel across physical machines (this requires manual two-laptop testing).

