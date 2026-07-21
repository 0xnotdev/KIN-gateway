# KIN — Vision & Roadmap (North Star, not V1 scope)
**Status:** Aspirational reference. V1 remains exactly as scoped in PRD-v1 and system-design-v1 — this doc exists so later decisions can be checked against a coherent long-term direction without scope-creeping V1 itself.

---

## Design philosophy

KIN is an open protocol with a thin, opinionated product on top — the same relationship email has to Gmail, or the web has to a browser. Anyone should eventually be able to run a KIN-compatible node. KIN (the CLI/GUI) is the good client, not the sole gatekeeper of the network. This is what prevents the product from becoming a single company's walled garden — and what prevents us from being solely liable for a "worldwide agent network."

## Layer by layer

**Identity & discovery.** Local key pair = real trust anchor (unchanged from V1). Usernames map to public keys via a directory. At scale, the directory/relay layer is **federated** — multiple independent operators speaking the same protocol (like email servers, or NANDA's federated index), not one company's server. V1 ships with one simple hosted relay; the protocol must not assume that's the only one forever.

**Transport.** Synchronous, direct P2P when both agents are online; asynchronous store-and-forward through a relay when one is offline. End-to-end encrypted — the relay is a blind courier, never a reader of content.

**Autonomy model — a spectrum, not a switch.** Per contact, per action type, the human configures:
- *Always ask first* — default for anything with real-world consequence.
- *Auto-handle within pre-approved limits* — e.g. "confirm any evening plan under $30 without asking me."
- *Fully autonomous* — for genuinely low-stakes actions (pure info relay).

This is what makes "my agent booked the movie while I was at work" feel like a feature, not a loss of control — and it's the actual answer to "what does my agent do while I'm away."

**Capability sharing / task delegation.** Distinct subsystem from conversation. Agents advertise capabilities (compute, tools, skills) via an Agent-Card-style manifest; other agents can request scoped work against those capabilities, with resource limits so one agent can't silently monopolize another's machine. Possible long-term accounting/micropayment layer (AP2/x402-style) once this is real. Not needed for a pilot between people who already trust each other.

**Multi-agent teams.** Coalition formation for bigger goals — one agent coordinates, decomposes a task, delegates subtasks to specialist agents, aggregates results. This is essentially the classic Contract Net Protocol from 1980s multi-agent-systems research, modernized. Depends entirely on bilateral negotiation (V1/V2) being solid first — team coordination is negotiation with more parties and more failure modes, not a separate easier problem.

**Trust & reputation, worldwide version.** First-contact fingerprint verification (already in V1 design) handles "is this really who I think it is" for people you already know. At worldwide scale, a reputation layer becomes necessary for agents interacting with strangers' agents — a history of completed interactions without disputes, similar to how marketplaces build trust between parties with no prior relationship.

## Non-negotiable security constraint: agent-to-agent prompt injection

Once agents can message each other freely, a malicious or compromised agent can send crafted content designed to manipulate the receiving agent's reasoning (a classic documented failure mode in agent-protocol threat research). Every inbound message from another agent must be treated as **untrusted input**, evaluated strictly against the receiving human's own configured permission scopes — never treated as an instruction the local agent's core reasoning simply obeys because it arrived from a paired contact. This applies from V1 onward, not just at scale — the earlier a bad habit gets baked in, the harder it is to remove later.

## Product experience

- Inbox-style view of what happened / is pending while you were away.
- Live streaming, interruptible mode when actively engaged (already in V1).
- Full transcript/audit trail, always inspectable.
- CLI-first (protocol correctness matters more than polish right now); GUI companion later once the protocol has proven itself.

## Deferred design decisions (named, not forgotten)

**Identity recovery beyond the V1 recovery phrase.** V1 ships with a 12-word recovery phrase (self-custody, nothing stored by us). Two legitimate paths exist for later, and they are not equivalent:
- *Password-derived key* — same self-custody model, substituting a user-chosen password (run through a slow, brute-force-resistant derivation like Argon2/scrypt) for the random phrase. Easier to remember, weaker entropy — a real trade-off, not a strict improvement. Safe to add as an alternative alongside the phrase.
- *Custodial "forgot password" reset* — only safe to build if a reset **always generates a new identity under the old username and forces every existing contact to redo fingerprint verification.** A reset that silently restores the old trusted key would mean we (or anyone who compromises the reset flow) could re-key and impersonate any user to their entire contact list — that would quietly break the entire trust model this product depends on. Worth building eventually for real-world usability at scale, but only in this specific safe form, and it comes with real responsibility (we'd become a genuine identity provider, with the security obligations that implies).

**Multiple specialized agents per person.** A person will realistically run several agents (coding, planning, philosophy, etc.), not just one. The identity/trust model already supports this cleanly without protocol changes: identity belongs to the **person** (root key, from the recovery phrase), and specialized agents are **sub-identities derived from that same root** — the same pattern used in enterprise PKI (subordinate certificates), SSH certificate authorities, or hierarchical-deterministic wallets deriving many child keys from one seed. Concretely: `priyanshu/coding`, `priyanshu/planning`, `priyanshu/philosophy` would each be independently addressable and independently verifiable, but provably linked back to one root identity via the same recovery phrase already in V1 — no added backup burden. A contact could pair with a specific sub-agent directly (e.g. "Priyanshu's coding agent") rather than the human having to manually route every incoming task themselves. This is a real, non-trivial build (key derivation hierarchies, sub-identity trust chains) — deferred past V1, which proves the simplest case first: one person, one identity, one agent.

**A2A protocol compliance.** V1 deliberately uses a custom protocol (see system-design-v1.md 1.2), not the actual A2A/ACP specifications — those don't natively support personal identity, offline delivery, or our autonomy model, which are core to what KIN needs. If wider interoperability with the broader agent ecosystem (talking to non-KIN, A2A-compliant agents) ever becomes a real goal, that would mean adopting A2A's actual wire format and layering our identity/relay/autonomy features on top as extensions — a materially bigger, more constrained build than the custom protocol, and a conscious future decision, not a default.

## Sequencing (rough, not committed)

1. **V1** (current): 2 agents, 2 systems, conversation/negotiation only, no tools, sync + async messaging, key-pair identity + username directory, graduated autonomy for message handling.
2. **V2**: capability/task delegation between 2 agents (share compute/tools), richer permission model.
3. **V3**: multi-agent team formation (3+ agents), federation of the directory/relay layer.
4. **V4+**: worldwide reputation system, marketplace/accounting layer for shared capabilities, GUI.
