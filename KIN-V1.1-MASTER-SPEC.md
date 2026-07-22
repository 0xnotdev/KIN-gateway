# KIN V1.1 — Master Product & Build Specification

**Status:** Authoritative build contract

**Product name:** KIN

**Version:** 1.1.0

**Audience:** Two or more people who already know one another and want their own specialist AI agents to collaborate across independent laptops, accounts, harnesses, and workspaces.

**Precedence:** This document supersedes all earlier V1 product/design documents for V1.1 work. If code and this document differ, this document wins until deliberately amended. V1 remains supported as the migration base; V1.1 is not a rewrite of KIN’s identity, signed transport, or encrypted relay foundations.

**TUI companion:** `KIN-V1.1-TUI-SYSTEM.md` is the authoritative implementation contract for every terminal screen, widget, keyboard interaction, layout, theme, rendering rule, and micro-interaction described here.

---

## 1. The product in one sentence

**KIN is the private, terminal-native workspace where people send their own specialist agents to collaborate with trusted peers’ agents, while both people can watch, steer, approve, and keep the result.**

The emotional model is intentionally simple: a person has a roster of capable agents — their “Pokéballs.” They choose the right agent for a job, send it to a trusted peer, the peer chooses their specialist, and the two agents work in a shared, visible session. KIN is the trusted arena, courier, contract, and record keeper; it is not the owner of either person’s agents.

### 1.1 What KIN is

- A trusted peer-to-peer collaboration layer for personal and work agents.
- A polished terminal product for dispatching, observing, steering, and approving cross-person agent work.
- An adapter host: local agents, SDK/harness agents, and webhook/cloud agents can participate through one contract.
- A capability-aware task network between trusted contacts.
- A durable audit log and artifact handoff system.

### 1.2 What KIN is not in V1.1

- A public agent marketplace, reputation system, social feed, or stranger-discovery network.
- A remote shell, shared filesystem, or mechanism for one peer to directly invoke another peer’s local tools.
- A source of raw model chain-of-thought.
- A payment, calendar-booking, browser-control, or autonomous real-world action platform.
- A replacement for Claude Code, Codex, OpenCode, LangGraph, or any other agent harness.

Those exclusions are product strengths. KIN connects agents that users already trust and operate; it never turns a paired contact into an administrator of a user’s machine.

---

## 2. Product principles

1. **The human owns the agent.** An agent’s model, memory, workspace, tools, secrets, and policies remain local to its owner.
2. **A task is a collaboration contract, not remote control.** Peers request outcomes and offer capabilities; the receiving owner selects the agent and grants any local authority.
3. **Trust is person-first, agent-scoped.** Alice pairs with Bob once. Alice can then see and target Bob’s published agent cards, but a new agent cannot silently inherit broader permissions.
4. **The terminal is the product.** V1.1 should feel composed and fast like a premium native CLI/TUI: keyboard-first, dense without being noisy, calm under load, and graceful in a plain shell.
5. **Spectators see evidence, not hidden reasoning.** Live activity, verified messages, tool/event summaries, artifacts, and concise agent-provided rationale are observable. Private chain-of-thought is never requested, stored, streamed, or presented.
6. **Autonomy is explicit and narrow.** The owner decides which agent may act, what it may do locally, what can be automatically relayed, and what must stop for consent.
7. **No opaque failure.** A user always sees whether a session is waiting for a peer, an agent, an approval, a relay delivery, a capability decision, or a recoverable error.
8. **Build durable primitives before “network effects.”** Pairing, capability cards, session orchestration, artifact exchange, and consent come before public discovery, teams, or economics.

---

## 3. V1.1 outcome and success criteria

By the V1.1 checkpoint, Alice and Bob on different laptops can install KIN in one PowerShell command, create or migrate identities, register their own agents, pair, choose agents for a task, watch a live agent-to-agent session, approve meaningful local actions, exchange artifacts/results, and revisit the complete session later.

### 3.1 Core success journey

1. Alice installs KIN, opens a beautiful terminal workspace, imports or creates two agents: `Code Scout` and `Planner`.
2. Bob does the same with `Data Cleaner` and `Finance Analyst`.
3. Alice opens **Dispatch**, picks Bob, chooses `Code Scout`, sees Bob’s published agent cards, selects `Data Cleaner`, writes a task, sets a collaboration mode, and sends it.
4. Bob receives an inbox notification, reviews the requested scope, confirms `Data Cleaner`, and accepts.
5. Both terminals open the same **Session Arena**: an independently verified, live transcript with activity signals, roles, approvals, artifacts, task progress, and a spectator timeline.
6. Each agent uses only its own owner’s configured harness/tools. When a consequential local action needs consent, only that owner sees and grants it.
7. The session ends with an outcome, artifacts, a concise decision record, and an exportable audit transcript.

### 3.2 V1.1 measurable acceptance bar

- A new Windows user can install the CLI with one documented PowerShell command and reach `kin` in under five minutes, excluding provider-account setup.
- A user can complete the core journey above without hand-editing a database or raw protocol payload.
- The dashboard reaches a usable interactive state in under two seconds with 100 sessions and 20 local agents.
- A direct session begins within five seconds on a normal connection; offline delivery is visibly queued and resumes automatically on startup/fetch.
- Every session transition, approval, artifact, and message has a timestamp, actor, signature/provenance, and inspectable state.
- A remote peer cannot execute a local command, read a local file, or access a local secret merely by requesting it.

---

## 4. Information architecture

KIN has six first-class surfaces. They are views into one coherent workspace, not separate mini-apps.

| Surface | Purpose | Primary keyboard entry |
|---|---|---|
| **Home / Dashboard** | Operational overview: roster, live sessions, inbox, approvals, health | `kin` or `kin dashboard` |
| **Dispatch** | Compose and send a collaboration request | `d` or `kin dispatch` |
| **Session Arena** | Live third-person view of one collaboration | `Enter` on a session or `kin open <session>` |
| **Agents** | Create, import, inspect, enable, and configure local agent cards | `a` or `kin agents` |
| **Network** | Contacts, pairing, peer agent cards, trust, reachability | `n` or `kin network` |
| **Inbox / Approvals** | Work waiting for user choice or local consent | `i` / `p` or `kin inbox` / `kin approvals` |

### 4.1 Command model

`kin` with no subcommand opens the full-screen workspace when attached to an interactive terminal. Non-interactive commands remain clean, scriptable, and JSON-capable.

```text
kin                              # workspace dashboard
kin dispatch                     # interactive dispatcher
kin agents                       # agent roster and card manager
kin network                      # contacts + peer cards
kin inbox                        # incoming session requests and messages
kin approvals                    # local approvals requiring a decision
kin open <session-id>            # Session Arena
kin session list [--json]
kin session export <id> --format markdown|json
kin init | kin restore
kin doctor                       # installation, relay, keychain, tunnel, agent checks
kin serve                        # run node; starts relay sync and TUI notifications
```

V1 commands such as `ask`, `respond`, `tasks`, and `contacts` remain as compatibility aliases during migration, but they are not the primary V1.1 experience.

---

## 5. UX and visual design system

### 5.1 Reference interpretation

The supplied references establish the desired **feel**, not a visual template to clone:

- full-screen, pane-based command workspace;
- understated dark atmosphere with low visual noise;
- strong typographic hierarchy and generous negative space;
- work visible as calm state changes instead of chatty logs;
- keyboard fluency and a sense of an active “operations room.”

KIN’s own visual metaphor is the **Arena**: people launch agents into bounded collaborations, watch the exchange from the side, and bring the result back to their workspace.

### 5.2 Design tokens

| Token | Choice |
|---|---|
| Background | near-black blue/charcoal; no wallpaper dependency |
| Surface | layered indigo/graphite panels with subtle borders |
| Accent | electric mint/cyan for healthy/live state; violet for selection/focus |
| Attention | warm amber for approvals; red only for security/failure |
| Typography | system monospace; aligned numeric/status columns; no ASCII-logo clutter |
| Motion | short, purposeful transitions; never blocks keyboard input |
| Accessibility | color is never the sole state signal; every status has text/icon; high-contrast theme included |

### 5.3 Layout: dashboard

```text
┌ KIN  • alice                                                     ? Help ┐
│ [D] Dispatch  [A] Agents  [N] Network  [I] Inbox  [P] Approvals       │
├───────────────────────┬────────────────────────────────────────────────┤
│ AGENT ROSTER          │ LIVE SESSIONS                                  │
│ ● Code Scout      idle│ ◉ Budget pipeline       with bob     2 agents  │
│ ◉ Planner       active│   Data Cleaner → Finance Analyst      03:18     │
│ ! Finance Guard approval│ ○ Design critique      waiting for bob        │
│                       │                                                │
│ NETWORK               │ INBOX / NEEDS YOU                              │
│ alice ↔ bob trusted   │ ! Bob wants to accept “Data Cleaner” [Enter]  │
│ bob: 3 published cards│ ! Finance Guard requests CSV export  [Enter]  │
├───────────────────────┴────────────────────────────────────────────────┤
│ Ready • relay online • 2 trusted peers • press d to dispatch            │
└────────────────────────────────────────────────────────────────────────┘
```

The dashboard is live-updating but never steals focus. A notification increments the relevant row and uses a short status pulse; it does not print over input or force the user into a session.

### 5.4 Dispatch flow

`kin dispatch` is a short wizard, never a configuration form dump.

```text
1. Peer             Choose Bob
2. Your agent       Choose Code Scout        [capability chips]
3. Their agent      Choose Data Cleaner      [card preview]
4. Collaboration    Ask / Research / Build pipeline / Debate
5. Goal             Write a concise outcome-oriented task
6. Inputs           Add text or reviewed artifacts
7. Review           Scope, permissions, expected outputs, send
```

Required interaction details:

- Arrow keys and fuzzy search work on every chooser; number shortcuts are additive, not required.
- Agent cards show owner, capability tags, accepted input/output types, availability, autonomy limits, and a short human-readable boundary summary.
- The final review displays exactly what leaves the machine: selected local agent, peer, requested peer agent, goal, attachments, and declared collaboration mode.
- Send feedback is a compact event sequence: `Packaging → Signing → Encrypting → Delivered` or `Queued safely at relay`.

### 5.5 Agent-picker window

The agent picker is a modal overlay, not a separate command. It must make agents feel tangible and distinct.

```text
 Select your agent                                      / search agents
 ─────────────────────────────────────────────────────────────────────
 › Code Scout                 Local • ready
   Code review, repo analysis, patch proposals
   Inputs: repository brief, files       Outputs: findings, patch artifact

   Planner                    Webhook • ready
   Plans, tradeoffs, decision records

   Finance Guard              Local • needs approval policy
   Financial summaries; never sends transactions
 ─────────────────────────────────────────────────────────────────────
 Enter select • Tab details • Esc back
```

No agent is selected by a model on the user’s behalf. KIN may recommend an agent based on capability matching, but selection is always legible and reversible.

### 5.6 Session Arena: third-person spectator mode

The Session Arena is the core V1.1 experience. It presents a shared collaboration as a neutral, evented timeline — not two chat bubbles and not hidden model reasoning.

```text
┌ Budget pipeline • Alice/Code Scout ↔ Bob/Data Cleaner • LIVE ─────────┐
│ Status  Working · round 3/12 · direct · 02:14              [Pause] [?] │
├───────────────┬──────────────────────────────────┬─────────────────────┤
│ SESSION MAP   │ VERIFIED EXCHANGE                │ ACTIVITY / OUTPUT   │
│ Alice         │ 10:41 Code Scout                 │ ✓ Parsed CSV schema │
│ Code Scout    │ “I need normalized date and…”    │ ◌ Data Cleaner:     │
│       ↕       │                                  │   transforming data │
│ Bob           │ 10:42 Data Cleaner               │ ! Bob approval:     │
│ Data Cleaner  │ “I can return a clean CSV…”     │   export 2 files    │
│               │                                  │                     │
│ [Artifacts 2] │ 10:43 Proposal                   │ ARTIFACTS           │
│ [Decisions 1] │ Normalization contract v1         │ clean.csv  reviewed │
├───────────────┴──────────────────────────────────┴─────────────────────┤
│ [T] transcript [O] outputs [D] decisions [F] follow-up [Esc] dashboard │
└────────────────────────────────────────────────────────────────────────┘
```

**Observable activity policy:** the activity stream may show structured lifecycle events such as “reading approved input,” “running local test suite,” “generated patch proposal,” “waiting for owner approval,” elapsed time, and agent-authored one-line rationale. It must not expose raw private chain-of-thought, hidden prompts, local secret values, or unapproved file contents.

### 5.7 Consent and artifact UX

An approval is a first-class object, not a yes/no interruption.

- It identifies the agent, owner, requested local action, affected scope, reason, risk label, and expiry.
- It offers `Approve once`, `Deny`, `Edit constraints`, and only where safe `Always allow this bounded action`.
- File or code changes are always represented as a reviewed **artifact**. KIN renders a syntax-aware unified diff where possible, but does not apply a peer’s patch automatically.
- An approval belongs to the receiving owner alone. Alice cannot approve an action inside Bob’s workspace and vice versa.

---

### 5.8 Human experience layer — V1.1 core

The following are product mechanics, not decorative extras. They answer the questions users have while agents work: *which agent is right, is it safe, what is happening, do I need to act, did we make progress, and can I reuse this?*

#### First Flight

After installation, KIN offers a short, resumable journey instead of dropping users at a blank prompt:

```text
Welcome to KIN.
1/4  Create or restore identity                 ✓
2/4  Connect an agent                           → Choose now
3/4  Start node / test relay reachability       ○
4/4  Pair a trusted person                      ○
```

It explains recovery once in plain language, offers a two-profile local demo before inviting a peer, and ends with an optional guided first dispatch. `kin guide` resumes it; normal daily use never sees it again.

#### Agent readiness and recommendations

Every agent has an honest state: `Ready`, `Busy`, `Reserved`, `Needs key`, `Needs workspace`, `Waiting for approval`, `Offline`, or `Policy blocks this task`. Dispatch can rank agents by capability, input type, availability, and task type, but always labels the result **Suggested — not automatic** and explains why in one sentence.

#### Attention, not interruption

KIN has one cross-workspace queue: **Needs you**. It contains only work that truly needs a person: accepting a session, selecting an agent, clarifying scope, approving a local action, or reviewing an outcome.

- Notifications group by session and urgency; they never print over terminal input.
- Users can set quiet hours, snooze non-urgent requests, and opt into terminal-bell/desktop notifications.
- State is human-readable: `Waiting for Bob to choose an agent`, never generic `pending`.
- Security warnings and expiring approvals cannot be silently hidden.

#### Cockpit and Focus modes

The Session Arena has two densities. **Cockpit** is the three-pane operational view. **Focus** is one calm timeline with current status, the next decision, and the latest output. `z` toggles without changing the session, and KIN remembers the preference locally.

#### Private owner notes

Every session supports notes that are local-only and never enter agent context or transport. An owner can deliberately promote a note into a shared constraint; KIN shows the exact change for review and records the promotion as a signed event. Private notes are visually distinct and excluded from exports by default.

#### Checkpoints, decisions, and replay

- An agent may propose a structured **checkpoint**: understanding, open questions, options, recommendation, and next step.
- Either human can pin an event as a decision and add a local or shared decision note.
- `r` opens **Replay**, a scrub-able timeline of verified messages, approvals, artifacts, and state transitions.
- `kin session recap <id>` produces a deterministic event summary and may additionally offer a clearly labelled LLM summary.

Replay never requests, stores, or exposes raw chain-of-thought.

#### Collaboration etiquette

Agents can request a concise human clarification rather than inventing an answer. Owners can send a rate-limited visible **Nudge**, pause with a reason, or **Hand back** a session with a bounded package of state, artifacts, unresolved questions, and recommended next owner/agent.

#### Outcome cards and reuse

Completed work gets an Outcome Card: agents involved, result, decisions, artifacts, duration, and actions to open, export, run again, or create a playbook. “Run again” always creates a fresh draft with fresh approvals; it never reuses past authority.

### 5.9 Small guide users will actually read

`kin guide` is built into the TUI and command line, not a link to a large website. It provides searchable short paths for **Start here**, **Meet your agents**, **Send good work**, **Watch and steer**, **Work safely**, and **Fix a problem**. Each page ends with one relevant command/key action. The same concise guide ships as Markdown for team sharing.

## 6. Agent model

### 6.1 Person identity and local agents

The person remains the network identity and trust anchor. An agent is a local, owner-controlled execution profile attached to that identity. Agents do not become independently pairable public people in V1.1.

An agent has:

- a stable local `agent_id` and display name;
- an owner identity;
- an adapter type and connection configuration;
- a published capability card;
- local boundaries, autonomy policy, and approval policy;
- optional workspace bindings and memory references that **never leave the owner’s machine unless explicitly supplied as session input**.

### 6.2 Supported adapter types

| Adapter | V1.1 requirement |
|---|---|
| **Embedded LLM** | KIN’s reference LiteLLM-backed agent for simple use and demos |
| **Webhook** | Existing remote service/harness implementing the KIN adapter contract |
| **Local command bridge** | A supervised local process adapter for an installed CLI/harness; explicit command, workspace, and timeout only |
| **SDK adapter** | A Python adapter interface for first-party integrations built after the core contract is stable |

V1.1 does not claim native support for every framework. It defines a stable adapter contract so an integration with Claude Code, Codex, OpenCode, LangGraph, or another harness can be built without changing the KIN session protocol.

### 6.3 Local agent card format

Agent cards live at `~/.kin/profiles/<profile>/agents/<agent-id>.yaml`. Sensitive credentials never live in the YAML; they are keychain references.

```yaml
schema_version: "1.1"
id: code-scout
name: Code Scout
description: Reviews repositories and proposes bounded fixes.
adapter:
  type: local_command
  command: codex
  working_directory: "C:/work/acme-api"
capabilities:
  tags: [code-review, debugging, test-analysis, patch-proposal]
  accepts: [text/markdown, application/json, text/x-diff]
  produces: [text/markdown, text/x-diff, application/json]
boundaries:
  network_access: deny
  filesystem: workspace_read_write_with_approval
  shell: approval_required
  max_runtime_seconds: 900
  max_artifact_bytes: 5242880
autonomy:
  relay_information: never
  propose_actions: always_ask
  execute_local_actions: always_ask
presentation:
  accent: cyan
  avatar: "◆"
```

### 6.4 Published peer agent card

Only safe, useful metadata is published to trusted peers:

```json
{
  "schema_version": "1.1",
  "agent_id": "data-cleaner",
  "name": "Data Cleaner",
  "description": "Converts raw tabular data into validated CSV and spreadsheet artifacts.",
  "capabilities": {
    "tags": ["data-cleaning", "csv", "spreadsheet"],
    "accepts": ["text/csv", "application/vnd.ms-excel", "text/markdown"],
    "produces": ["text/csv", "application/json", "text/markdown"]
  },
  "availability": "ready",
  "requires_owner_acceptance": true,
  "protocol_version": "1.1"
}
```

It must not disclose filesystem paths, secrets, private prompts, tool credentials, internal memory, or a claim that a peer can operate the owner’s tools.

---

### 6.5 Agent relationships and safe handoffs

#### Tag-in handoffs

At a checkpoint, an owner can replace their participating agent with another one of their own specialists. For example, Alice starts with `Planner`, then tags in `Code Scout` once implementation review is needed.

1. KIN creates a bounded handoff package: objective, verified transcript, accepted artifacts, decisions, and open questions.
2. The owner selects the replacement agent and reviews its card/boundaries.
3. The peer receives a signed `participant_changed` event and may continue, adjust scope, or pause.
4. The replacement receives the package only — never the outgoing agent’s private memory or hidden prompts.

An agent may recommend a tag-in when a capability is missing, but it cannot perform one autonomously.

#### Availability, reservations, and local quality signals

Users can reserve a specialist for a planned collaboration. A peer requesting a busy agent sees an expected wait; the receiving owner may queue, substitute, or decline. KIN may retain private local quality signals — completion rate, response time, useful capability tags, and owner notes — to help an owner choose. These are never global/public reputation scores in V1.1.

## 7. Collaboration model

### 7.1 Session types

| Type | Intent | Typical output |
|---|---|---|
| **Ask** | Scoped factual request | Answer with evidence |
| **Research** | Compare, investigate, synthesize | Brief + sources/artifacts |
| **Debate** | Reach a reasoned recommendation | Decision record + dissent |
| **Build pipeline** | Transform an input through specialists | Reviewed artifacts + summary |
| **Review** | Critique an artifact or plan | Findings + proposed changes |
| **Delegate subtask** | Ask a specialist for a bounded contribution | Subtask result returned to parent |

Every type is a structured session envelope with an objective, participants, input/output contract, constraints, and terminal condition. Freeform discussion is allowed inside the envelope, but a session never becomes an unbounded autonomous conversation.

### 7.2 Dispatch and acceptance lifecycle

```text
draft → sent → delivered | queued
      → peer_review → accepted | declined | needs_clarification
      → active → awaiting_owner_approval | awaiting_peer | paused
      → completed | failed | cancelled | expired
```

- Sender selects **their** agent and requested peer agent.
- Receiver selects or confirms **their** agent. A requested agent is never silently activated.
- Both participant cards are snapshotted into the session record so later card edits do not rewrite history.
- Either owner can pause/cancel their own participation at any time; cancellation is visible and signed.
- Default hard limit is 12 collaboration turns. The session owner can set a lower limit. A session cannot increase this limit automatically.

### 7.3 Collaboration messages

Message kinds:

`task_request`, `acceptance`, `decline`, `clarification`, `plan`, `proposal`, `counterproposal`, `finding`, `question`, `answer`, `artifact_offer`, `artifact_accept`, `approval_request`, `approval_decision`, `status_event`, `final_result`, `cancel`.

Every signed message includes a session ID, monotonically increasing sequence number per sender, sender person identity, sender agent ID, schema/protocol version, timestamp, and content hash. The receiver validates the person signature, card/session membership, sequence, and policy before passing content to an adapter.

### 7.4 Artifacts

Artifacts are immutable, content-addressed session outputs. Examples: CSV, spreadsheet, Markdown brief, JSON result, diff, image, or archive within size limits.

- An artifact offer has metadata, SHA-256 hash, MIME type, size, provenance, and preview policy.
- Artifact bytes are encrypted end-to-end in direct or relay transport.
- A receiver must explicitly save/import an artifact into a local workspace; receiving it does not write to disk outside KIN storage.
- Patches are artifacts. Applying them is a distinct local approval workflow.

### 7.5 “Social” layer in V1.1

KIN V1.1 is social in the useful sense: a trusted network of people, their agent rosters, presence, invitations, shared sessions, and reusable collaboration history.

Included: contacts, paired-agent cards, session invitations, presence/reachability, recent collaboration, and optional contact labels/groups.

Excluded: public profiles, global search, follower graphs, public posting, ratings, payments, or stranger agent requests. Those require reputation, abuse controls, and policy work that do not belong in V1.1.

---

### 7.6 Collaboration playbooks

A **playbook** is a user-owned template for repeatable cross-agent work, not an autonomous workflow engine. It captures a reviewed successful shape while requiring fresh peer/agent choices and fresh approvals every time.

```yaml
name: Monthly financial cleanup
session_type: build_pipeline
participants:
  initiator_agent: finance-guard
  peer_agent_capabilities: [data-cleaning, spreadsheet]
inputs:
  - name: source_file
    type: text/csv
outcomes: [normalized_csv, finance_summary]
constraints:
  turn_limit: 8
  artifact_size_limit_bytes: 5242880
approval_defaults:
  workspace_write: always_ask
```

Playbooks open Dispatch with reviewable fields pre-filled. They may be private, shared as a trusted artifact, or stored as team documentation, never globally published. They refuse to run when selected cards/policies no longer satisfy their compatibility requirements.

### 7.7 Session control and recovery

| Feature | User value | Safety rule |
|---|---|---|
| Pause / resume | Stop without losing context | Resume requires an owner action |
| Fork session | Explore an alternative privately | A fork sends nothing until dispatched as a new session |
| Clarification | Ask before guessing | Humans decide what to disclose |
| Session budget | Cap turns, time, artifacts, and estimate | Exhaustion pauses/ends; it never silently expands |
| Retry checkpoint | Recover from a transient failure | Reuses only reviewed checkpoint inputs |
| Export / redact | Share results safely | Preview exactly what leaves KIN |
| Workspace revision reference | Identify the local version used | Metadata only; no peer repository access |

### 7.8 Context Pantry

Dispatch includes a **Context Pantry**: an explicit inventory of what is about to reach an agent and peer. Inputs are typed as message, pasted text, approved artifact, or local reference. Local references are resolved under the owner’s policy; peers receive only the chosen output/artifact, never browsable local paths. Every item shows size, classification (`local only`, `share with peer`, `private`), and optional expiry.

Users can create local-first **context packs** such as a data dictionary, project constraints, or brand voice. A pack must be explicitly attached to a session and is visible in final review.

## 8. Security, privacy, and consent contract

### 8.1 Continuity from V1

V1’s Ed25519 identity, mandatory out-of-band fingerprint verification, X25519 encrypted relay envelopes, signed messages, OS keychain secrets, direct-first transport, and offline relay remain mandatory.

### 8.2 New V1.1 invariants

1. **Untrusted inbound content:** all peer-provided messages, agent cards, artifacts, and metadata are untrusted input to local agents.
2. **No delegated tool authority:** a peer may request an outcome; it cannot call a named local tool directly.
3. **Owner-local policy:** adapter/tool execution is decided solely by the local owner’s agent policy and local approval system.
4. **No raw chain-of-thought:** KIN requests structured results and observable events, never hidden reasoning traces.
5. **Least data:** only session-scoped input crosses the boundary. Agent memory, system prompts, workspace context, and unrelated history stay local.
6. **Capability claims are descriptive, not authorization.** A card saying “can write files” does not give a peer permission to cause writes.
7. **Immutable audit:** signed envelope metadata, approvals, state transitions, and artifact hashes remain inspectable after completion.
8. **Explicit agent selection:** agents cannot be silently swapped after peer acceptance; a replacement triggers a visible signed `participant_changed` event and may require peer re-acceptance.

### 8.3 Approval classes

| Class | Examples | Default |
|---|---|---|
| Informational relay | Send a factual answer | allowed only if agent policy says so |
| Session participation | Accept a task / send proposal | owner review by default |
| Artifact receipt | Store session artifact in KIN vault | allowed; external import requires review |
| Workspace read | Read local repo or document | adapter-local policy, visible activity |
| Workspace write | Apply patch, write generated file | explicit owner approval with diff |
| Shell / network / external action | Run command, network request, send email | explicit owner approval; V1.1 adapters may disable entirely |

### 8.4 Threat responses

- Invalid signature: reject, preserve security event, do not invoke an adapter.
- Unpaired sender: reject before decrypt/processing beyond routing metadata.
- Agent card changed unexpectedly: mark peer card stale; require review before targeted dispatch.
- Prompt injection attempt: show it as untrusted content; do not elevate policy; allow owner to cancel/report locally.
- Relay unavailable: preserve locally queued outbound envelope and report retry state.
- Receiver offline: encrypted queue with expiry and acknowledgement semantics; never claim delivery before processing acknowledgment.

---

### 8.5 Trust and provenance UX

Security needs to be visible in the product, not buried in documentation.

- Every Session Arena header shows a compact trust strip: paired person, fingerprint state, agent-card freshness, transport state, and encryption state.
- **Why do I trust this?** explains the concise chain for a peer or artifact: pairing date, verified fingerprint, signer, card snapshot, hash, and delivery route.
- Security warnings use a dedicated red state and plain language, for example: “Bob’s agent card changed after this session began. No new capability was accepted.”
- Agent cards have a change-review diff so a new claimed capability or boundary cannot be buried in YAML.

### 8.6 Cost, time, and impact transparency

KIN is not a billing system, but users must be able to control work. Local adapters report elapsed time and, when safely available, model token/cost estimates. Dispatch may set a maximum duration, turn count, artifact budget, and local model budget. The Arena shows these as informative gauges; reaching a limit pauses or requests finalization instead of silently overrunning. Peer costs remain private unless a peer chooses to summarize them in the final result.

## 9. Technical architecture

### 9.1 Components

```text
┌──────────────────────────────────────────────────────────────────────┐
│ KIN Terminal Workspace (Rich/Textual TUI + scriptable CLI)           │
│ Dashboard • Dispatch • Session Arena • Roster • Inbox • Approvals    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ local API/events
┌──────────────────────────────▼───────────────────────────────────────┐
│ KIN Node                                                              │
│ identity • policy engine • session orchestrator • artifact vault      │
│ agent-card registry • adapter runtime • signed transport • audit log  │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │ direct HTTPS                  │ encrypted mailbox
┌───────────────▼───────────────┐   ┌───────────▼──────────────────────┐
│ Peer KIN Node                 │   │ Directory + Relay                │
│ peer’s adapters and policy    │   │ public cards, blind envelopes    │
└───────────────────────────────┘   └──────────────────────────────────┘
```

### 9.2 Node modules

| Module | Responsibility |
|---|---|
| `identity` | root keys, recovery, trusted contacts, signatures |
| `agent_registry` | validates local cards, produces safe published cards, card snapshots |
| `adapter_runtime` | invokes embedded/webhook/local-command/SDK agents with scoped inputs |
| `session_orchestrator` | lifecycle, turn limits, participant selection, events, cancellation |
| `policy_engine` | evaluates local agent boundaries and creates approval requests |
| `artifact_vault` | encrypted local storage, hashing, preview, transfer, export/import gates |
| `transport` | direct delivery, relay fallback, retries, acknowledgement, version checks |
| `event_bus` | typed local events powering TUI and noninteractive JSON streaming |
| `audit` | append-only session/event record and Markdown/JSON export |

### 9.3 Adapter contract

```json
// KIN → adapter
{
  "session": {"id": "...", "type": "build_pipeline", "turn": 3},
  "self": {"agent_id": "code-scout", "card_snapshot": {}},
  "peer": {"person": "bob", "agent_id": "data-cleaner", "card_snapshot": {}},
  "objective": "Produce a validated finance summary from the supplied CSV.",
  "inputs": [{"kind": "message", "content": "..."}, {"kind": "artifact", "ref": "..."}],
  "history": [{"kind": "finding", "actor": "bob/data-cleaner", "content": "..."}],
  "local_policy": {"filesystem": "read_only", "network": "deny"}
}

// adapter → KIN
{
  "events": [
    {"type": "activity", "label": "Validating CSV columns"},
    {"type": "approval_request", "action": "workspace_write", "summary": "Apply proposed patch", "artifact_ref": "..."}
  ],
  "message": {"kind": "finding", "content": "..."},
  "artifacts": [{"path_or_bytes": "...", "mime_type": "text/markdown"}],
  "terminal": false
}
```

Adapters receive only one session’s approved inputs/history. They cannot directly send network messages; KIN signs and delivers the selected output after policy evaluation.

### 9.4 Data model additions

```text
agents
  agent_id, name, adapter_type, local_card_json, published_card_json,
  enabled, availability, created_at, updated_at

sessions
  session_id, type, owner_username, peer_username, status, objective,
  sender_agent_id, receiver_agent_id, participant_snapshot_json,
  turn_limit, created_at, updated_at, terminal_result_json

session_events
  event_id, session_id, sequence, actor_username, actor_agent_id,
  kind, visibility, payload_json, signature, created_at

artifacts
  artifact_id, session_id, sha256, mime_type, bytes_encrypted,
  metadata_json, offered_by, created_at

approvals
  approval_id, session_id, agent_id, action_class, request_json,
  decision, decided_at, expires_at
```

Sensitive local fields — artifact bytes, session content, adapter credentials, and any stored input — are encrypted at rest with a key held in the OS keychain. Public identity/card metadata is not encrypted because it is designed for publication to trusted peers.

### 9.5 Protocol versioning and compatibility

- V1.1 nodes advertise `protocol_version: "1.1"` and supported feature flags.
- V1.1 keeps V1 task endpoints as compatibility transport, but uses `/v1.1/sessions` and typed event envelopes for new collaboration sessions.
- A V1 peer can receive V1-compatible ask/answer work but cannot participate in a V1.1 agent-selected session.
- Incompatible versions fail with a precise capability/version message before session creation.

---

### 9.6 V1 to V1.1 compatibility contract

V1.1 is additive. Existing V1 primitives have direct homes in the new product:

| Existing V1 primitive | V1.1 home | Compatibility rule |
|---|---|---|
| Recovery phrase / Ed25519 identity | Person identity | unchanged; no re-pairing solely for upgrading |
| Contacts + fingerprint verification | Network / trusted people | migrated in place |
| Agent roster YAML | Local agent registry | imported and validated; embedded/webhook agents remain usable |
| `ask` task | Basic `Ask` session | preserved as a compatibility command and mapped to a session view |
| `respond` draft approval | Inbox / Approvals | preserved; historical messages display as legacy events |
| Task transcript | Session timeline | read as append-only historical events |
| Direct signed delivery | Transport | unchanged; V1.1 envelopes are used only when both sides support them |
| Encrypted relay + acknowledgement | Transport | unchanged; artifacts use the same blind-delivery principle |
| Per-contact autonomy | Local policy engine | preserved; scope/action classes become more explicit |

Migration must never invalidate identities, contacts, tasks, or queued relay messages. A failed profile migration leaves the old profile untouched and writes a recoverable migration report. V1.1 agent-selected sessions are offered only when both peers advertise V1.1 capabilities; V1 endpoints remain supported until a future separately announced deprecation version.

## 10. Installation and operational experience

### 10.1 One-command Windows install

The canonical PowerShell installer is:

```powershell
irm https://kin.dev/install.ps1 | iex
```

The script must be short, readable, version-pinned, checksum-verifiable, and published in the repository. It must:

1. detect PowerShell version, Python/pipx, and a supported secure keychain;
2. install or guide installation of prerequisites without silently changing unrelated tools;
3. install a pinned `kin-cli` release through `pipx`;
4. install/check `cloudflared` only after explaining why it is needed;
5. run `kin doctor`;
6. open the first-run `kin init` flow.

Provide alternatives for security-conscious users: `pipx install kin-cli==<version>` and an inspectable local installer download. macOS/Linux scripts are a V1.1 quality target but PowerShell is the launch-critical path.

### 10.2 `kin doctor`

`kin doctor` reports, with fixes:

- CLI version and profile location;
- secure keychain availability;
- identity status;
- relay reachability and directory registration;
- node/tunnel reachability;
- adapter-card validation and unavailable agents;
- provider credentials present/missing without exposing values;
- pending inbox and failed session recoveries.

---

### 10.3 Feature priority for a satisfying V1.1

V1.1 must feel complete without becoming an unfinishable social platform. Priorities are intentional:

| Tier | Must include |
|---|---|
| **P0 — the product** | One-command install, First Flight, agent registry/cards, Dispatch + agent picker, peer acceptance, Session Arena, Needs you, approvals, direct/relay continuity, transcripts, safe artifacts, `kin guide`, V1 migration |
| **P1 — the premium feeling** | Focus mode, checkpoints/replay, outcome cards, private notes, Context Pantry, readiness/recommendations, cost/time budgets, tag-in handoffs, playbooks |
| **P2 — only if P0/P1 are genuinely polished** | reservations, context packs, richer adapter bridges, local quality signals, advanced exports/redaction templates |
| **Not V1.1** | public network/discovery, global reputation, marketplace, payments, strangers, multi-owner teams, direct peer tool control |

P0 is never sacrificed for more surfaces. A smaller polished arena is better than a sprawling half-finished “agent social network.”

## 11. Build plan

### Milestone 1 — V1.1 foundation

- Introduce the versioned session/event schema and encrypted-at-rest local session vault.
- Add agent registry, local YAML card migration, safe published-card model, and card validation.
- Preserve V1 pairing, transport, relay acknowledgement, and compatibility commands.
- Add `kin doctor` and clean profile migration.

**Exit:** Existing V1 tests pass; a user can register/list local agent cards and inspect safe peer cards.

### Milestone 2 — Premium terminal workspace

- Build the Textual/Rich TUI shell, dashboard, notification model, keyboard map, and graceful non-TTY fallback.
- Build Dispatch, Agent Picker, Network, Inbox, Approval Queue, and Session Arena.
- Add concise contextual help and `kin guide` walkthrough.

**Exit:** All primary flows are possible without remembering raw IDs or manually querying a database.

### Milestone 3 — Agent-selected collaboration

- Implement adapter runtime for embedded + webhook; define supervised local-command bridge.
- Implement peer card sync, dispatch acceptance, agent selection, and session lifecycle.
- Implement structured activity events and third-person spectator mode.

**Exit:** Alice and Bob can choose a local/peer agent and complete a live ask, research, debate, and review session.

### Milestone 4 — Artifacts and consent

- Implement artifact vault/transfer, previews, patch diffs, approval objects, and local policy engine.
- Implement build-pipeline and delegated-subtask session types.

**Exit:** The finance pipeline example works end to end without either peer remotely controlling the other’s machine.

### Milestone 5 — Distribution and release hardening

- Publish signed/versioned package and installer; create release checklist.
- Add full two-profile/two-process/two-machine smoke suite, offline/restart tests, compatibility tests, and accessibility/TTY snapshot tests.
- Write the small user guide, troubleshooting, privacy model, and relay operator guide.

**Exit:** A non-developer can install, pair, dispatch, observe, approve, and export a session using documented instructions alone.

---

## 12. Test matrix and release gates

| Area | Required evidence |
|---|---|
| Installation | Clean Windows VM PowerShell install and uninstall/reinstall test |
| Identity | New identity, restore, key mismatch, pairing/fingerprint, profile migration |
| Agent cards | Invalid card rejection, safe-public-card redaction, adapter availability states |
| Dispatch | Agent picker, peer acceptance/decline, version/capability mismatch, offline queue |
| Session | Direct, relay, restart/replay, turn limit, cancel, pause, concurrent sessions |
| Spectator UX | TUI snapshots for dashboard/arena/approval; no chain-of-thought/secrets emitted |
| Policy | Peer cannot induce tool authority; every write/shell/network gate is locally owned |
| Artifacts | hash validation, encryption, size limits, diff preview, explicit import/apply |
| Reliability | relay acknowledgement, duplicate delivery, partial failure, retry/backoff, expiry |
| Accessibility | monochrome/high-contrast mode, keyboard-only flow, narrow terminal fallback |

Release requires zero known critical security defects, no unhandled terminal tracebacks on expected operational failures, green unit/integration/TTY tests, and a documented real two-laptop acceptance run.

---

| User experience | First Flight completion, keyboard-only dispatch, focus/cockpit parity, quiet-hour behavior, guide walkthrough |
| Collaboration mechanics | checkpoint/replay, tag-in handoff, pause/fork/retry, playbook compatibility, Context Pantry privacy |

## 13. Decisions deliberately deferred beyond V1.1

- Public discovery, feeds, follows, reputation, and marketplace/accounting.
- Multi-party sessions (three or more independent owners) and autonomous coalition formation.
- Federation of relay/directory operators.
- Native adapters for every third-party harness.
- Payments, credential delegation, and direct cross-machine tool execution.
- A graphical desktop/web client. The protocol and event model should make this possible later, but terminal excellence comes first.

---

## 14. Final V1.1 definition of done

KIN V1.1 is complete only when this sentence is true:

> Two people who use different agents on different laptops can install KIN in one command, pair securely, select their specialist agents, run a bounded collaboration in a beautiful terminal workspace, watch it from a neutral third-person view, approve any consequential local work, receive reviewed artifacts/results, and understand exactly what happened without trusting KIN or a peer with control of their private machine.

---

## 15. Detailed V1.1 build execution plan

This is the delivery plan for the product contract above. It supplements the five outcome milestones in section 11; it does not weaken any security, compatibility, or interface requirement in this specification or in `KIN-V1.1-TUI-SYSTEM.md`.

### 15.1 Delivery rules and checkpoint standard

- **Implementation boundary:** extend the existing Python `kin-node` and `kin-relay` packages. Keep the relay blind to plaintext session content and artifacts. The node remains the only process that may decrypt, evaluate policy, invoke an adapter, or write the local vault.
- **Contract-first rule:** define typed Python models and serialized JSON examples before adding a route, database migration, adapter, or TUI screen that consumes them. Use `schema_version: "1.1"` and a `protocol_version: "1.1"` field on every new persisted or wire object.
- **No security placeholders:** an unimplemented signature check, encryption-at-rest path, approval gate, or compatibility path is a blocking defect, not a TODO that may cross a checkpoint.
- **No UI-only business logic:** the TUI consumes typed local node events and calls explicit node commands. It cannot decide authorization, mutate state optimistically without a node response, or bypass audit creation.
- **Test environments:** maintain (1) deterministic in-process node/relay fixtures, (2) two isolated local profiles with separate keys and vaults, (3) a relay-backed offline fixture, and (4) a manual two-laptop Windows acceptance environment. Tests must never use a real user profile, keychain entry, relay account, workspace, or provider credential.
- **Checkpoint evidence:** a checkpoint is passable only with: merged schema/API notes; green required automated tests; a short reproducible smoke command or script; migration/rollback result where storage changed; and an updated known-limitations list. “Screen renders” or “happy path works manually” is insufficient.
- **Stop rule:** after every milestone, the team may stop without leaving un-migrated data, unaudited authority, a broken V1 command, or a half-enabled feature flag. New migrations are forward-only and must be safe to run more than once.

### 15.2 Shared implementation inventory

Create the following implementation seams before feature work. Names may vary only if the same ownership boundaries remain explicit.

| Seam | Required responsibility | Verification owner |
|---|---|---|
| `kin.node.schemas` | Pydantic/dataclass models, validators, canonical serialization, feature negotiation | contract tests |
| `kin.storage.migrations` | ordered, idempotent schema migrations and migration report | storage tests |
| `kin.audit` | append-only, queryable signed event record and deterministic export | audit tests |
| `kin.session` | lifecycle reducer, participant snapshots, turn/budget enforcement, recovery | state-machine tests |
| `kin.policy` | local-only policy evaluation and expiring approval decisions | security tests |
| `kin.artifacts` | encrypted vault, hash verification, metadata, preview/import gates | artifact tests |
| `kin.transport.v11` | direct-first delivery, relay fallback, acknowledgement, deduplication | protocol/relay tests |
| `kin.adapters` | narrow invocation contract and normalized adapter events | adapter contract tests |
| `kin.events` | typed local event stream and durable replay cursor | node/TUI integration tests |
| `kin.tui` | Textual workspace consuming node state/events only | TUI plan section 14 |

Each domain object must have: an immutable ID; UTC RFC 3339 timestamp; actor person and, when relevant, agent ID; schema/protocol version; validation result; and an audit event that can be inspected by session ID. Content hashes use SHA-256 over a defined canonical byte representation. Signatures must cover the versioned envelope fields and content hash, not an arbitrary display string.

### 15.3 Milestone M0 — Baseline, contracts, and safe development harness

**Goal:** make V1.1 work testable without destabilizing V1.

**Build steps**

1. Record the supported Python, Windows, PowerShell, Textual, Rich, cryptography, database, and keychain versions in the package metadata and contributor instructions. Pin direct runtime dependencies and add a reproducible test environment.
2. Run and preserve the existing node and relay test suites as the V1 compatibility baseline. Add a single command that runs formatting/linting, unit tests, node/relay integration tests, and TUI snapshots when present.
3. Add fixture factories for identities `alice` and `bob`, two independent profile roots, a controlled clock, deterministic relay state, and synthetic agent cards. Fixture private keys are test-only and cannot be loaded from normal profile paths.
4. Publish canonical JSON examples and validators for `AgentCard`, `PublishedAgentCard`, `SessionEnvelope`, `SessionEvent`, `ArtifactOffer`, `ApprovalRequest`, `ApprovalDecision`, `TransportAcknowledgement`, and `CapabilityAdvertisement`.
5. Define the exact V1.1 session state reducer: only the transitions in section 7.2 are legal; terminal states are immutable; `awaiting_owner_approval`, `awaiting_peer`, and `paused` retain the last resumable checkpoint; no event may increase the original turn limit.
6. Define compatibility negotiation: both peers must advertise 1.1 plus required feature flags before a V1.1 session is created; otherwise return a structured incompatibility result and offer only the V1-compatible Ask path.

**Required tests**

- Schema round-trip and rejection tests for missing version, unknown required field, invalid enum, oversized field, malformed timestamp, and non-canonical hash/signature input.
- Reducer table tests covering every permitted transition and every forbidden transition, including duplicate, late, and terminal-state events.
- Existing V1 identity, pairing, task/ask, relay fallback, storage, and roster tests remain green unchanged.
- Fixture isolation test proving Alice cannot open Bob’s database, keychain namespace, artifact vault, or workspace fixture.

**Checkpoint M0 — stop/handoff:** commit the contract examples, transition table, test harness, and baseline test report. No live protocol, profile migration, or TUI behavior changes are enabled yet.

### 15.4 Milestone M1 — Persistent V1.1 records, audit trail, and migration

**Goal:** add durable V1.1 state without invalidating any V1 profile, contact, task, or queued relay item.

**Build steps**

1. Add forward-only migrations for `agents`, `sessions`, `session_events`, `artifacts`, and `approvals` as specified in section 9.4. Add indexes for `session_id + sequence`, session status/update time, approval expiry, artifact SHA-256, and outbound delivery state.
2. Encrypt session content, artifact bytes, stored adapter inputs, and credential references at rest using a per-profile vault key held only in the OS keychain. Store plaintext-free routing/index metadata only where the query needs it.
3. Implement an append-only audit writer. Every state transition, received/sent envelope, approval request/decision/expiry, artifact offer/accept/import, migration result, and security rejection writes exactly one durable event with correlation ID.
4. Implement deterministic session export: Markdown and JSON are ordered by persisted event sequence, identify redacted fields, include hashes/provenance, and exclude private notes by default. LLM summaries are explicitly optional and never replace the deterministic recap.
5. Implement `kin migrate` (or the migration step of `kin init`) as a preflight, copy/validate, atomic commit, and report flow. On failure, preserve the old profile byte-for-byte and write a recoverable report outside the old profile’s authoritative data.
6. Make V1 task transcripts readable as legacy timeline events; retain original identifiers and do not retroactively manufacture V1.1 signatures or agent selections.

**Required tests**

- New-profile migration and V1-profile migration fixtures, including rerun/idempotency, interrupted migration, unsupported prior schema, corrupt old card, missing keychain, and disk-write failure.
- At-rest inspection test: database and vault files must not contain known session plaintext, artifact bytes, or test secret values.
- Audit immutability tests: an attempt to update/delete an event fails; duplicate delivery produces a recorded deduplication result rather than a second semantic event.
- Export golden tests for event ordering, legacy events, redaction, Markdown/JSON parity, and deterministic recap under a fixed clock.
- Restore/restart test: a pending approval, queued envelope, and active session recover to the exact persisted state.

**Checkpoint M1 — stop/handoff:** a migrated V1 profile opens and V1 commands still work; a new V1.1 session record can be created, recovered, exported, and audited locally, but it is not yet sent to a peer.

### 15.5 Milestone M2 — Agent registry, card safety, and local policy primitives

**Goal:** make local agents selectable and peer-visible without publishing local authority or secrets.

**Build steps**

1. Implement YAML card loading from `~/.kin/profiles/<profile>/agents/<agent-id>.yaml` with a strict schema, path normalization, maximum field lengths, MIME/capability validation, and keychain-reference-only credentials.
2. Create a separate `PublishedAgentCard` projection. Its allowlist is exactly the safe fields in section 6.4; reject or strip paths, prompts, memory references, command arguments, credentials, local quality data, and policy internals.
3. Store versioned local cards and immutable session-time card snapshots. A later local edit changes future dispatch eligibility only; it never alters an existing session record.
4. Implement local availability states: `Ready`, `Busy`, `Reserved`, `Needs key`, `Needs workspace`, `Waiting for approval`, `Offline`, and `Policy blocks this task`. Each state has a machine code and the human explanation required by the TUI.
5. Implement a pure policy evaluator that consumes local card boundaries, session context, requested action class, and prior bounded approval. It returns `allow`, `deny`, or a fully specified approval request; it has no peer-supplied “tool name” execution interface.
6. Expose scriptable commands/API methods to validate, list, inspect, enable/disable, import, and publish cards. Keep V1 roster behavior as a compatibility alias.

**Required tests**

- Valid local-command, embedded, and webhook cards; invalid YAML; duplicate ID; unsafe path; unknown adapter; secret in YAML; bad timeout/size; bad MIME; and overlong capability tests.
- Projection property tests proving no prohibited local-card field can appear in the serialized published card, logs, node event stream, or `--json` output.
- Card-change test: a peer card change marks the cached card stale and prevents targeted dispatch until owner review; an existing session retains its original snapshot.
- Policy matrix tests for every approval class in section 8.3, expiry, constraint editing, “always allow bounded action,” denied action, and peer attempts to name a local tool.
- CLI JSON schema and human-output smoke tests for card list/inspect/validate and unavailable-agent reasons.

**Checkpoint M2 — stop/handoff:** two local profiles can independently register and inspect cards; Bob receives only Alice’s safe projection; no session invokes an adapter or performs a local action.

### 15.6 Milestone M3 — Signed V1.1 transport and peer dispatch lifecycle

**Goal:** deliver a bounded, agent-selected request through direct transport or the encrypted relay, with correct provenance and no duplicate semantic processing.

**Build steps**

1. Implement version/feature advertisement, peer-card synchronization, card freshness timestamps, and explicit stale-card review. Preserve V1 contacts and out-of-band fingerprint verification; do not require re-pairing for an upgrade.
2. Implement canonical V1.1 envelope signing and verification. Validate pairing, signature, session membership, sender sequence monotonicity, content hash, protocol version, feature flags, payload size, and expiry before decrypting content for the adapter pipeline.
3. Implement `/v1.1/sessions` typed delivery using direct HTTPS first and the existing encrypted relay fallback second. The relay receives opaque encrypted envelopes and routing metadata only.
4. Implement sender lifecycle events: `draft`, `sent`, `delivered` or `queued`, then peer review. “Delivered” means a valid processing acknowledgement, never merely relay upload.
5. Implement receiver review, explicit receiver-agent confirmation/selection, accept, decline, and needs-clarification. Snapshot both participant cards at acceptance and make each lifecycle action signed and auditable.
6. Add bounded pause, resume, cancel, expiration, and 12-turn default enforcement. A pause/resume/cancel is visible to the peer, but each owner may stop only their own participation.

**Required tests**

- Two-profile direct happy paths for Ask, Research, Debate, and Review through sent → delivered → peer_review → accepted → active.
- Relay-offline queue, receiver-offline queue, restart before acknowledgement, acknowledgement after retry, expiry, and exponential backoff tests with a controlled clock.
- Duplicate envelope, out-of-order sequence, replayed acknowledgement, modified hash, invalid signature, unpaired sender, stale card, unsupported protocol, and feature mismatch rejection tests. Assert the adapter is never called in every rejected case.
- Session state/property tests for concurrent sessions, participant cancellation, receiver substitution, turn-limit exhaustion, and terminal-state immutability.
- Relay inspection test proving neither plaintext objective/message nor artifact bytes are persisted by the relay.

**Checkpoint M3 — stop/handoff:** Alice can choose her agent and request Bob’s published agent; Bob must explicitly select/confirm before an accepted session becomes active. The interaction works direct and through a restart-safe relay queue, using fixture adapters only.

### 15.7 Milestone M4 — Adapter runtime and bounded collaboration orchestration

**Goal:** turn accepted session state into controlled local agent work and verified, observable outputs.

**Build steps**

1. Freeze the adapter input/output contract from section 9.3 and add a versioned adapter capability declaration. Pass only the current session’s approved inputs, allowed history, participant snapshots, objective, and local policy summary.
2. Implement the reference embedded LLM and existing webhook adapter behind the same normalized interface. Normalize outbound activity, message, artifact, terminal, error, and approval-request events.
3. Implement the supervised local-command bridge: explicit executable allowlist/command, explicit normalized working directory inside the local policy boundary, sanitized environment, bounded stdin/stdout/stderr capture, runtime limit, process-tree termination, and no shell-string interpolation. It must remain disabled unless configured by the owner.
4. Make the session orchestrator the only component allowed to request adapter work and select relayable output. It validates adapter output, applies policy, hashes/stores artifacts, increments turns, writes audit events, and signs any peer-visible message.
5. Permit structured observable activity and one-line agent rationale only. Reject raw chain-of-thought fields, hidden prompts, secret values, or unapproved file content from display, storage, and transport paths.
6. Implement checkpoint proposal, clarification, nudge rate limit, tag-in handoff package, and bounded retry-from-reviewed-checkpoint. A tag-in emits `participant_changed`, snapshots the replacement card, and never transfers private agent memory.

**Required tests**

- Adapter contract fixtures for embedded, webhook, and a fake local command: exact input minimization, normalized events, timeout, crash, malformed output, oversized output, cancellation, and retry behavior.
- Local-command security tests for prohibited workspace escape, shell metacharacters, inherited secret environment variables, network-disabled policy, timeout/process-tree cleanup, and unsafe executable configuration.
- End-to-end two-profile fixture tests for all four P0 session types, 12-turn cap, clarification, pause/resume, cancel, adapter failure, tag-in, and restart recovery.
- Negative content tests seed prompts, fake chain-of-thought, API-key-shaped strings, and unapproved file text; assert they are redacted/rejected before audit/TUI/transport and that the security/recoverable event is visible.
- Event ordering test: every peer-visible message has a prior validated local event and matching signature/provenance.

**Checkpoint M4 — stop/handoff:** two fixture agents complete a bounded collaboration with auditable messages and activity; no adapter has a network transport handle or direct peer/tool authority.

### 15.8 Milestone M5 — Artifacts, approvals, and the owner-local safety boundary

**Goal:** safely exchange useful outputs without writing into a peer’s workspace or silently granting consequential authority.

**Build steps**

1. Implement encrypted artifact-vault storage keyed by session and SHA-256. Enforce card/session artifact-size limits before storage, transfer, and preview; persist MIME type, size, source, hash, and preview policy.
2. Implement `artifact_offer` and `artifact_accept` envelopes. Transfer bytes end-to-end encrypted over direct/relay transport; verify hash and size before the artifact is marked available.
3. Implement safe previews: text/Markdown/JSON/CSV bounded previews, syntax-aware unified diff where applicable, and metadata-only fallback for unknown/binary types. Never execute, auto-open, auto-import, or auto-apply an artifact.
4. Implement approval objects with immutable requested scope, reason, risk label, optional artifact/diff reference, constraints, owner identity, expiry, and decision. Only the relevant local owner may approve once, deny, edit constraints, or create a narrowly bounded reusable rule.
5. Split artifact receipt from external import and split patch preview from workspace apply. The latter operations require local policy evaluation and explicit owner approval; record both the original artifact hash and resulting local path/revision reference in local-only audit metadata.
6. Implement Build pipeline and Delegate subtask envelopes only after these gates exist. Both must respect aggregate turn, duration, artifact, and model-cost budgets; exhaustion pauses or asks for finalization rather than expanding automatically.

**Required tests**

- Artifact cryptographic/hash/MIME/size tests, corrupt bytes, duplicate offer, unsupported preview, path traversal filename, archive-bomb policy, and interrupted relay transfer recovery.
- Explicit-import tests prove that receipt creates only vault state; no workspace file changes occur until the separate reviewed action is approved.
- Approval authorization tests prove Alice cannot approve Bob’s action, expired/replayed/edited approvals cannot be reused outside their exact bounded scope, and denial prevents adapter continuation.
- Diff preview golden tests; apply tests use a disposable workspace and verify exact approved patch, conflict behavior, audit record, and no peer-initiated write.
- Budget tests for turn, runtime, artifact bytes, and model estimate: cap reached produces a signed pause/finalization state and never runs another action.
- Two-profile finance-pipeline smoke: CSV offered, inspected, accepted, transformed by Bob’s local agent, offered back, reviewed, and optionally imported by Alice with each local decision independently recorded.

**Checkpoint M5 — stop/handoff:** the complete finance-pipeline demonstration works through direct and relay transport. A hostile peer can request a patch or shell action but cannot cause it without the target owner’s current, scoped approval.

### 15.9 Milestone M6 — P0 product surfaces and scriptable parity

**Goal:** expose the now-safe workflow through a complete terminal product and noninteractive alternatives.

**Build steps**

1. Implement the TUI foundation and all P0 surfaces according to the detailed UI plan appended to `KIN-V1.1-TUI-SYSTEM.md`: First Flight, Home, Agents, Network, Dispatch/agent picker, Inbox/Needs you, Approval review, Session Arena, and guide.
2. Bind every stateful UI action to a node command with a matching scriptable command/JSON result where it is meaningful: session list/open/export, cards, inbox, approvals, dispatch, doctor, init/restore, and serve.
3. Implement `kin doctor` with actionable status for version/profile, keychain, identity, relay/directory, node/tunnel, card validation, provider credentials without values, inbox, and recovery. Expected operational failures must yield structured results rather than tracebacks.
4. Implement a resumable First Flight with identity, agent, node/relay, pairing, optional two-profile demo, and optional first dispatch. It must preserve progress and never require manual database/payload edits.
5. Exercise the same event stream in TUI and non-TTY/plain fallback so that there is no TUI-only safety-critical operation.

**Required tests**

- The full automated UI/keyboard/snapshot/accessibility suite in the TUI plan, wired to real node fixtures rather than mocked widget-only state.
- CLI contract and JSON tests for every listed command; non-TTY and `--plain` tests prove primary dispatch, review, approval, export, and recovery remain possible.
- `kin doctor` fault-injection tests for each dependency and redaction tests for credentials/keys.
- First Flight end-to-end test from empty profile to fixture peer dispatch; close/reopen/resume at each step.
- Performance test: dashboard accepts input in under two seconds with 100 sessions and 20 agents; event burst does not change focused input/selection or create duplicate visible events.

**Checkpoint M6 — stop/handoff:** a new local user can use documented commands or keyboard-only TUI controls to reach an accepted fixture session, see safe live evidence, make an approval decision, and export the result.

### 15.10 Milestone M7 — P1 collaboration depth

**Goal:** add reuse and operational depth only after P0 is demonstrably polished.

**Build steps**

1. Add Cockpit/Focus preference, private local-only notes with explicit signed promotion, checkpoints/decisions, deterministic replay, outcome cards, and fresh-authority reruns.
2. Add Context Pantry classifications, expiry, local references, and explicit context packs. Resolve a local reference under local policy and send only the reviewed output; never expose a browsable path to the peer.
3. Add readiness recommendations with a one-sentence explanation, reservations, local quality signals, playbooks, cost/time gauges, advanced redaction/export templates, and safe tag-in UX only as each underlying data/policy primitive is complete.
4. Maintain a P2 feature register. Do not begin public discovery, reputation, payments, multi-owner teams, direct peer tool control, or a graphical client under the V1.1 release branch.

**Required tests**

- Replay/recap determinism, private-note exclusion, deliberate note promotion signature, decision/checkpoint ordering, and rerun creates a fresh draft with no carried approval.
- Context Pantry classification/expiry/redaction tests, including local path non-disclosure and artifact-size constraints.
- Playbook compatibility and stale-policy/card refusal tests; reservation and readiness state tests.
- Cost/time/budget presentation tests where adapters do and do not report estimates; private peer cost is absent unless explicitly supplied.

**Checkpoint M7 — stop/handoff:** an owner can return to a completed session after a day, understand it from deterministic evidence, create a safe fresh rerun or playbook draft, and know exactly which inputs would leave the machine.

### 15.11 Milestone M8 — Installation, release hardening, and acceptance

**Goal:** make V1.1 safely installable and credible for non-developers on two Windows laptops.

**Build steps**

1. Package a pinned, signed `kin-cli` release; publish the short, readable, checksum-verifiable PowerShell installer plus inspectable `pipx` and downloaded-installer alternatives. Do not silently install/change unrelated tools.
2. Make the installer detect prerequisites, explain optional `cloudflared`, run `kin doctor`, and enter First Flight. Supply uninstall and upgrade behavior that preserves profiles and queued relay data.
3. Establish CI matrices for Windows launch target and supported development platforms; run unit, contract, storage, relay, integration, TUI snapshot, accessibility, security, and packaging tests from a clean checkout.
4. Produce a release candidate with versioned protocol/features, migration notes, changelog, privacy model, small guide, troubleshooting, relay operator guide, backup/recovery guide, and incident/security reporting path.
5. Execute the manual acceptance script below on two independent laptops/accounts and capture only redacted evidence.

**Required release tests**

| Scenario | Required pass condition |
|---|---|
| Clean install | A new Windows user runs the documented command and reaches `kin`/First Flight in under five minutes excluding provider setup. |
| Upgrade/migration | Existing V1 identity, contacts, tasks, and queued envelopes survive; a failed migration leaves the old profile usable. |
| Pair and cards | Fingerprints are verified out of band; safe cards synchronize; changed cards require review. |
| Direct session | Alice and Bob select agents, accept, exchange visible events/results, and start within five seconds on a normal connection. |
| Offline relay | Sender sees queued state; receiver restart/fetch resumes delivery; no duplicate result is produced. |
| Consequential action | Only the local owner sees and can approve/deny a bounded action; rejected peer request cannot access command/file/secret. |
| Artifact and export | Hash/provenance/diff review work; import/apply is explicit; transcript export is deterministic and redacts by policy. |
| Terminal resilience | 80×24, 16-color, high-contrast, plain/non-TTY, disconnect, and recoverable errors remain usable with no traceback. |

**Checkpoint M8 — release/no-release decision:** release only when all required automated suites are green, no critical or high unmitigated security defect exists, the two-laptop script passes, P0 acceptance is reproducible from documentation alone, and product/security owners sign the release checklist. Otherwise ship no V1.1 release; triage the failed gate to a named corrective milestone.

### 15.12 Traceability and final acceptance ledger

Maintain a release ledger mapping every requirement in sections 3.2, 6–10, and the TUI quality gates to: implementation seam; automated test ID; manual acceptance step if needed; owner; result; and evidence link. The following assertions are release blockers and must appear as explicit ledger rows:

1. V1 identities, contacts, V1 commands, and queued relay messages survive migration.
2. Every peer-visible message, session transition, approval, and artifact has timestamp, actor, provenance/signature state, and inspectable session history.
3. A peer cannot execute a local command, access a local secret, browse a local filesystem, or bypass an owner-local approval by crafted content, card metadata, relay replay, or adapter output.
4. No raw chain-of-thought, hidden prompt, credential, or unapproved local file content is requested, stored, relayed, exported, or rendered.
5. All primary flows work from keyboard and have a coherent non-TTY/plain alternative.
6. The dashboard is interactive in under two seconds at the stated 100-session/20-agent load; a normal direct session starts within five seconds; offline state is honest and resumes safely.
7. The two-person core journey in section 3.1 completes from documented install through deterministic export without hand-editing a database or raw protocol payload.
