# Product Requirements Document — V1

> **Implementation precedence:** where this PRD conflicts with `system-design-v1.1.md`, the system design is the current V1 protocol source of truth.
**Product name:** KIN
**Author:** You + Claude (acting as tech lead / pair engineer)
**Status:** Draft for review — REVISED: communication layer only, no tools
**Date:** 2026-07-15

---

## 1. One-line vision

KIN is a terminal application — run it the way you'd run Claude Code, opencode, or Codex — where your personal agent lives in your terminal. KIN instances on two different people's machines can connect and have real, negotiated conversations to collaborate on simple tasks. V1 proves the communication/negotiation layer works genuinely end to end between two independent systems. Tool integrations (calendar, APIs) are explicitly deferred — the hard, valuable part right now is the conversation layer itself.

## 2. Problem statement

Today, personal AI agents (assistants, copilots) are single-player. Yours can reason and act for you; it cannot converse with your mom's, your friend's, or a colleague's agent to jointly work something out. Every cross-person coordination task still requires a human to relay information manually between two isolated AI assistants, or between two humans directly. There is no consumer product where a user can explicitly connect their agent to another specific, known person's agent, and have the two agents actually converse, negotiate, and collaborate on a bounded task — visibly and with consent.

Industry protocol work (A2A, MCP, NANDA, ACP) solves the plumbing between agents in **enterprise/vendor** contexts. Almost none of it is aimed at **two individuals who know each other** connecting their personal agents the way they'd add a contact. V1's job is to prove that the conversation/negotiation layer itself — the actual hard part — works genuinely between two independent systems. Everything an agent might *do* with a conclusion (book something, update a calendar) is a downstream integration problem, deliberately out of scope for now.

## 3. Target users — V1 pilot (REVISED SCOPE)

**Concrete pilot setup:** Two physical laptops, each running KIN as a terminal application (like Claude Code, opencode, or Codex) — separate codebase, separate process, separate machine, real network between them (not localhost). No shared database, no shared state. This is as real as cross-system interoperability gets without provisioning cloud infrastructure.

**Scope change (twice now — and both are correct calls):** V1 = exactly 2 agents, 2 independent systems, **communication/negotiation layer, plus a bounded, read-only, human-gated tool-call extension — no autonomous or write-capable remote execution**. No calendar, no external APIs, no data access beyond what a human types into their own terminal. The entire point of V1 is proving that two independently-built KIN instances can hold a real, useful, negotiated conversation and jointly land on an outcome — purely through dialogue.

| Persona | System | What the agent has access to |
|---|---|---|
| **You** (Principal Agent) | System A — your KIN instance | Whatever you tell it in your terminal session |
| **Second real person** (e.g. a friend, sibling — TBD) | System B — their KIN instance | Whatever they tell it in their terminal session |

Both are **real, independently running terminal apps** that only know how to talk to each other through the agreed protocol/interface. Multi-party negotiation (3+ agents) is deferred well past V1.

## 4. Core use cases (V1, fully real, cross-system, no tools — pure conversation/negotiation)

### UC-1: Negotiated agreement
> *"Ask the other side's agent to agree on X with me"* — e.g. picking a number/option/plan out of a small set of candidates, where each human has a stated preference their agent must advocate for, and the two agents go back and forth until they converge (or clearly report they couldn't).
Tests: multi-turn negotiation, proposal/counter-proposal, knowing when to stop and report a result.

### UC-2: Scoped information exchange
> *"Ask the other agent something specific, get back only what's relevant, relay it to me."*
Your agent asks a bounded question; the other agent decides what's in-scope to answer (a lightweight consent check, even without a full permission system yet) and responds; your agent relays the answer back to you, not the raw exchange.
Tests: request/response over the protocol, an explicit boundary on what gets shared.

### UC-3 (V2 — deferred): Multi-party / tool-integrated collaboration
Real calendar/tool access and 3+ agent group negotiation. Deferred until UC-1 and UC-2 are solid between exactly 2 independent systems — that's the real engineering challenge right now, not breadth.

V1's job: make the *conversation layer itself* — turn-taking, negotiation, knowing when you're done — genuinely robust between two independent systems that share nothing but the protocol.

## 5. Functional requirements

- **FR1 — Identity & pairing:** Each KIN instance has its own cryptographic identity (a local key pair), generated on first run — not a central account system we control. Two instances that have never met pair once via a one-time code (`/pair` to generate, `/pair <code>` to join), brokered by a minimal external pairing service that only ever sees pairing metadata (code, public key, tunnel URL) — never conversation content. After pairing, each side is saved locally as a **contact**, and all further communication is direct and peer-to-peer.
- **FR2 — Graduated autonomy (minimal V1 version):** Two levels only, configurable per contact: **"always ask"** (default — any outcome, proposal, or reply needs your explicit confirmation before it's sent) vs. **"auto-relay pure info"** (the agent may autonomously answer a scoped factual question and relay a received answer back to you, but may not commit to, agree to, or finalize anything on its own). This is the direct answer to "what does my agent do while I'm offline" — it can inform, never commit, until a richer permission model exists (see vision-roadmap.md).
- **FR3 — Agent-to-agent negotiation:** Agents can exchange structured proposals/counter-proposals over multiple turns to reach an outcome (not just single request/response).
- **FR4 — Human-in-the-loop, fully interactive:** Both humans can watch their own agent's side of the conversation live in their own terminal, and can jump in and redirect their agent mid-negotiation — not just approve/reject at the end.
- **FR5 — Full transcript visibility:** Every human can see the actual conversation their agent had with another agent — no black-box negotiation.
- **FR6 — CLI/terminal interface:** KIN runs as a terminal application, similar in spirit to Claude Code/opencode/Codex — a REPL-style session. Behavior: when your agent is working (including talking to another KIN instance), the exchange **streams live** in your terminal rather than a blocking spinner, and you can interrupt to redirect, matching the Claude-Code interaction model. Failures, refusals, or dropped connections are shown verbatim — the agent never silently swallows or hides an outcome. Commands are **hybrid**: explicit slash commands for meta/control actions (`/pair`, `/contacts`, `/ask <contact> "<question>"`), plus natural language for actual work, where the agent itself decides when a natural instruction implies reaching out to another KIN instance.
- **FR7 — Group (3+) negotiation:** deferred past V1 (see use cases). The protocol should not actively prevent it later, but V1 only needs to prove the 2-party case.
- **FR8 — Thread/task model:** One persistent thread per contact (i.e., per paired connection). Multiple tasks can exist within that thread over time (each with its own lifecycle: submitted → working → input-required → completed/failed), but V1 does not need multiple simultaneous *contacts* — just one paired connection, potentially handling several tasks across its history.
- **FR9 — Relay message retention:** If a message is sent while the recipient is offline, the relay holds it, encrypted, for a fixed window (7 days) — if the recipient never comes online within that window, the message expires and is deleted. No indefinite storage of undelivered content.
- **FR10 — Recovery phrase confirmation:** After showing the 12-word recovery phrase once, KIN requires the user to re-type back 2 randomly-selected words before proceeding — a cheap check that they actually captured it, not just a "shown and hoped for the best" step.
- **FR11 — Negotiation termination:** A fixed round limit (default 10 exchanges) hard-stops any negotiation with no agreement; either agent core may also end it earlier if it detects the exchange isn't converging. The human always sees the specific reason a negotiation ended.
- **FR12 — Agent roster & selection (V1 addition):** A user may configure multiple named agents (YAML-defined, each with its own model/personality/tool allowlist) and select which one handles a given task or reply, via an interactive picker or --agent flag. Zero or one configured agent preserves original V1 single-agent behavior exactly.

## 5a. Build sequencing (walking skeleton first)

- **Milestone 0 — Walking skeleton:** the simplest possible real flow — Terminal 1's agent asks Terminal 2's agent a specific question, gets an answer, relays it back. Single request/response, no negotiation loop. Purpose: prove the protocol, the network boundary (2 real laptops via tunnel), and both terminal UIs actually work end to end before any complex logic exists.
- **Milestone 1 — Negotiation:** build the multi-turn proposal/counter-proposal loop (UC-1) on top of the now-proven pipe from Milestone 0.

## 6. Non-functional requirements (these are what separate a toy from production-grade)

- **Security & privacy (highest priority):** This product moves personal data (a mother's calendar, a friend's budget) between parties. Every cross-agent message must be authenticated (this agent really is controlled by this person), scoped (only what's permitted leaves the boundary), and logged (auditable). This gets its own design pass before we write networking code — not bolted on later.
- **Consent-by-default:** Nothing irreversible happens without a human checkpoint in V1. Autonomy expands only after trust in the system is earned (yours, not just the agents').
- **Observability:** Every negotiation is traceable end-to-end — which agent said what, when, and why a decision was reached. Multi-agent systems fail in confusing, non-obvious ways; we design for debuggability from day one.
- **Reliability:** LLM calls and tool calls fail, time out, or hallucinate. The system needs retries, timeouts, and a clear failure path (agent says "I couldn't reach Mom's agent," not silent failure).
- **Small-scale first, correct first:** V1 targets ~5 agents, not internet scale. We are not building for load we don't have yet — that's a classic over-engineering trap.

## 7. Explicit non-goals for V1 (out of scope — write this down so we don't scope-creep)

- ❌ No public agent directory / discovery of strangers' agents (connections are explicit invites only)
- ❌ No autonomous payments or money movement (AP2/x402-style commerce is a possible V2+, not V1)
- ❌ No general-purpose "any agent talks to any agent" open network
- ❌ No building our own transport/wire protocol from scratch (we build on A2A-style task exchange concepts + MCP-style tool access, as agreed)
- ❌ No unrestricted, write-capable, or autonomously-approved remote tool execution — cross-node tool calls are limited to a fixed allowlist of read-only tools (see system-design-v1.md §4.4a) and always require explicit human approval on the receiving side.
- ❌ No mobile app yet — a working backend + simple web interface is enough to prove the concept
- ❌ No support for restoring the same identity on two live devices simultaneously (undefined/unsupported behavior for V1)

## 8. Success criteria for V1 ("done" means)

1. You can add a real connection (e.g., a family member), set permission scopes, and your agent successfully negotiates and completes UC-1 end to end with a real calendar.
2. UC-2 and UC-3 work with real people's agents, not scripted stand-ins.
3. Every negotiation transcript is visible and auditable by the humans involved.
4. Nothing happens that a human didn't explicitly authorize, at the granularity they chose.
5. The system survives a failure (an agent unreachable, a bad LLM response) without doing something wrong silently.

## 9. Where existing standards fit (detail deferred to System Design doc)

- **A2A-style task/negotiation exchange** between agents — we adopt the *concepts* (Agent Cards, task lifecycle, structured proposals) rather than reinventing them.
- **MCP-style tool access** — each personal agent reaches its own calendar/tools through an MCP-shaped interface.
- **Identity** — even at pilot scale, we design a real (if simplified) verifiable identity model per connection, because retrofitting trust later is much harder than designing it in from the start.

Full architecture, tech stack, and data model come next, in the System Design doc.

## 10. Open questions for you before we move to System Design

- Confirm or rename the working title.
- Confirm the persona set (real people who'll actually participate, even if just you + one willing family/friend to start, with 2-3 more added shortly after).
- Any use case here that doesn't match what you pictured?
