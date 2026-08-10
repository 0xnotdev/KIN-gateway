# KIN Gateway — Scope and Checkpoint Tracker

> **Status:** CP0 implementation in progress
>
> **Last reviewed:** 2026-08-10
>
> **Source plan:** `docs/planning/deep-research-report.md`

## Current verified state

| Item | Status | Evidence |
|---|---|---|
| Research and design plan | Complete | `docs/planning/deep-research-report.md`, 2,231 lines. |
| `kin-gateway` source repository | Present / GATE-001 complete | `D:\KIN Gateway\new\kin-gateway`; origin `https://github.com/0xnotdev/KIN-gateway.git`; imported source commit `58258fb037ea49f23d8e572ad7cd9df59ef5e388`. |
| Immutable KIN V1.1 source snapshot | Complete | Reference clone `D:\KIN Gateway\original\kinto-main`; source commit/tag/tree/checksum recorded in `UPSTREAM_KIN_V1_1_SNAPSHOT.md`. |
| Gateway package and contract tests | In progress | Root `pyproject.toml`, `kin_gateway/`, and `tests/contract/`; official A2A direct and proxied JSON-RPC tests pass on Python 3.11/3.12. |
| Gateway CI and deployment assets | Not started | Imported CI still covers KIN V1.1; gateway-specific jobs and deployment assets remain. |
| Customer interviews, design partners, pilots | Not recorded | Targets exist, but no execution evidence exists here. |

Research, design, GATE-001 source preservation, and the original regression baseline are complete. CP0 gateway implementation is in progress.

## Scope governance

This document is the architectural and product-scope authority for v0.1.

Implementation agents may:

- Implement existing scoped requirements.
- Fix defects.
- Add tests necessary to prove existing requirements.
- Make internal refactors that preserve documented contracts.

Implementation agents may not, without an ADR and an explicit founder-approved amendment to this document:

- Add product capabilities or new external protocols.
- Weaken a locked invariant or change public schemas/authorization semantics.
- Move functionality between checkpoints or begin deferred work.
- Add customer-specific behavior to the core product.

When implementation convenience conflicts with a locked invariant, the invariant wins. The execution hierarchy is `scope.md` -> ADRs -> milestone -> issue -> failing test -> implementation -> passing test -> acceptance artifact. This document is not a daily engineering diary; update status and evidence without casually rewriting architectural intent.

## Product definition and scope boundaries

KIN Gateway exposes an organization's existing AI agent to customers, suppliers, and partners through standard A2A interfaces while enforcing organization-local identity mapping, Partner Grants, task policy, approval, revocation, and reconstructable evidence.

It complements existing IdPs and API gateways. It is not a new agent protocol, agent runtime, generic agent IAM, marketplace, personal-agent network, or full IAM replacement.

### Locked product invariants

| ID | Invariant | Required proof |
|---|---|---|
| INV-01 | A2A is the public agent-to-agent protocol; each release pins and documents an explicitly supported compatibility profile. | `A2A_COMPATIBILITY.md` plus official SDK/TCK contract coverage. |
| INV-02 | Counterparty needs no KIN install, SDK, or proprietary protocol. | Vanilla-client test. |
| INV-03 | Data plane stays in the customer's trust domain. | Deployment/config review. |
| INV-04 | KIN consumes OIDC/OAuth/mTLS; it is not an identity issuer. | Verified principal mapping. |
| INV-05 | Request body claims never establish identity or authority. | Forged-claim negative tests. |
| INV-06 | Authorization is deterministic; no LLM decides ALLOW/DENY. | Pure/replayable policy tests. |
| INV-07 | External tokens never become upstream or tool credentials. | Credential-separation test. |
| INV-08 | Shadow mode cannot alter upstream or caller traffic. | Response/status/SSE equivalence tests. |
| INV-09 | Enforce mode fails closed if required policy state fails. | Resilience tests. |
| INV-10 | Protected upstream is not externally bypassable. | Direct-origin/network-policy test. |
| INV-11 | Evidence is tamper-evident, never called tamper-proof. | Canonical hash-chain verification. |
| INV-12 | Prompts/artifacts are off by default; secrets never log. | Redaction/canary tests. |
| INV-13 | Every object/query is tenant scoped. | Cross-tenant negative/property tests. |
| INV-14 | Hosted control plane follows paid demand. | CP5 commercial gate. |
| INV-15 | External caller credentials are not forwarded upstream by default. KIN verifies them, evaluates policy, then uses customer-local upstream identity. | Upstream credential contract and credential-separation tests. |
| INV-16 | Data-plane and admin-plane access are separated. The admin plane is private/loopback by default and authenticated with bootstrap operator token or mTLS before enterprise SSO/RBAC exists. | Listener, network, and admin-auth negative tests. |

### Locked build scope

- Transparent A2A v1 JSON-RPC, REST, and SSE proxy.
- Mirrored protected Agent Card with no upstream leak.
- OIDC/JWT mapping and optional mTLS principal binding.
- Partner relationships, versioned grants, deterministic policy, shadow mode, and revocation.
- External task sessions, ownership isolation, approval, evidence, and Action Guard.
- Invitation URL, developer CLI/scanner, OTel/JSON/webhook export, Docker, and Kubernetes.

### Explicitly deferred

| Area | Disposition |
|---|---|
| Marketplace, public discovery, reputation, payments | Deferred pending a real network effect. |
| Proprietary counterparty protocol | Rejected; conflicts with interoperability. |
| Generic IAM replacement or agent runtime | Rejected; integrate with existing platforms. |
| Broad MCP gateway and LLM-based autonomous DLP | Deferred until design-partner demand. |
| Personal-agent networking, fingerprints, P2P pairing/relay | Removed from commercial path; legacy only. |
| Textual TUI and network UI | Diagnostic only; no product investment. |
| Hosted management plane and federation | CP5 only, after commercial proof. |

### Core model and enforcement tiers

```text
Organization -> PartnerRelationship -> ExternalPrincipal -> PartnerGrant -> ExternalTaskSession -> PolicyDecision / Approval / EvidenceEvent
```

| Object | Locked semantic meaning |
|---|---|
| `PartnerRelationship` | Durable relationship between two organizations. |
| `PartnerGrant` | Durable, versioned authority template governing access under that relationship. |
| `ExternalTaskSession` | One actual A2A task executed under a specific immutable Partner Grant version. |
| `ActionAuthorization` | One consequential structured action evaluated within an External Task Session. |

Do not introduce an overlapping `ExternalTaskGrant`. A task-specific temporary grant is allowed only if it represents genuinely separate, temporary authority and its relationship to `PartnerGrant` is documented by ADR.

| Tier | Customer integration | Enforceable scope |
|---|---|---|
| Transparent Gateway | No protected-agent code change. | Principal, partner, endpoint/method, ownership, expiry, budgets, rates, coarse approval, artifacts, revocation, evidence. |
| Action Guard | Local callback, SDK, sidecar, or tool/API gateway. | Structured business action, amount, data label, consequential approval, delegation, purpose constraints. |

The transparent gateway must not claim it can infer business actions or amounts securely from arbitrary natural-language traffic. Deep action policy requires structured data through Action Guard or an equivalent local boundary.

### Upstream credential contract (v0.1)

The required flow is:

```text
external token -> KIN verifies identity -> KIN evaluates policy -> KIN uses customer-local upstream identity -> internal agent
```

v0.1 supports only these upstream modes: a private unauthenticated local upstream, a static customer-owned service credential, or a configurable customer-owned bearer/header credential loaded from secret storage. Raw external-credential passthrough is disabled by default. If an explicit compatibility mode eventually permits passthrough, it must be marked unsafe, narrowly scoped, time-limited where possible, and audited. Token exchange and workload federation are later work, not v0.1 dependencies.

### Admin-plane minimum (pre-CP2)

Data-plane A2A routes and administrative routes use separate listeners or an equivalently enforced network boundary. By default, the admin plane binds to loopback or a customer-private network and requires a bootstrap operator token or mTLS. Grant creation/revocation, policy activation, approval administration, upstream configuration, and evidence export must never be unauthenticated. Enterprise admin SSO/RBAC remains CP4.

## Repository strategy and code disposition

The original KIN V1.1 source remains immutable. The distinct `kin-gateway` repository imports source commit `58258fb037ea49f23d8e572ad7cd9df59ef5e388`, and tag `kin-v1.1-import` anchors that exact upstream point. `UPSTREAM_KIN_V1_1_SNAPSHOT.md` records the Git tree and reproducible archive checksum.

The earlier uploaded-archive checksum `f2c58a556d3f1c98ff5c79ac2b4489c4ef08c262d915ad52b240bc7088c331aa` remains historical research metadata; it is not asserted to be the checksum of the GitHub import.

| Existing KIN primitive | Gateway disposition |
|---|---|
| Signing, encryption/vault, sessions, policy, approvals, artifacts/hashes, audit/export/replay | Keep and elevate. |
| Agent registry/selection and embedded/webhook/SDK adapters | Keep and modify for upstream and Action Guard roles. |
| Person/contact/pantry/playbook concepts | Modify into organization, partner, disclosure-package, and grant-template concepts. |
| KIN-specific Agent Card, fingerprints, pairing, P2P, relay, session modes, proposals | Hide, remove from product UX, or retain as legacy only. |
| Textual TUI, dispatch/network UI | Stop commercial investment; developer diagnostics only. |

Create a new layer around the import rather than refactoring the imported codebase first:

```text
kin_gateway/
  app.py
  a2a/          # card, proxy, streaming, compatibility, task bridge
  auth/         # oidc, jwt, mtls, principal mapping
  partners/     # models, grants, invitations
  policy/       # model, evaluator, obligations
  approvals/    # service, web; Slack/Teams later
  actions/      # Action Guard
  evidence/     # models, writer, hash chain, export
  shadow/       # observer, report
  upstream/     # client, credentials
  storage/      # base, SQLite, PostgreSQL
  telemetry/    # OTel, SIEM, redaction
  security/     # SSRF, replay, limits, content
tests/          # unit, integration, contract, security, fuzz, load, e2e
deploy/         # docker, helm, kubernetes, terraform
```

## Checkpoint dashboard

| Checkpoint | Duration | Status | Technical exit gate | Customer exit gate |
|---|---:|---|---|---|
| CP0 — Foundation + Transparent A2A | 2 weeks | Blocked on license authority | Unmodified A2A client -> KIN -> unmodified upstream; exact v0.1 compatibility profile and its required tests pass. | None; CP0 is purely technical. |
| CP1 — Identity + Grants + Shadow | 2 weeks | Planned | Verified principal, deterministic decision, revoke under 5 seconds, shadow non-interference. | Five qualified practitioner demos and two design partners commit staging traffic. |
| CP2 — Approval + Evidence + Pilot UX | 3–4 weeks | Planned | Hash-bound approval, Action Guard, evidence chain, counterparty flow. | Paid-pilot-ready build with no KIN counterparty install. |
| CP3 — Production Hardening | 4 weeks | Planned | PostgreSQL, HA-ready data plane, security/load/chaos/deploy gates. | Real limited-production customer need. |
| CP4 — Enterprise Integrations | 4–6 weeks | Deferred | IdP, approval, SIEM, and RBAC integration coverage. | Demand from active customers. |
| CP5 — Platform Scale | 6–8 weeks | Deferred | Signed policy distribution, partition, and tenant safety. | At least five paying organizations request central management. |

**Progression rule:** a checkpoint passes only when its technical gate and customer-evidence gate are both met. Finished code is insufficient by itself.

## CP0 — Foundation and Transparent A2A

**Objective:** preserve provenance, prove an isolated green baseline, and proxy standard A2A traffic without changing client or upstream agent.

| ID | Deliverable | Status | Completion evidence |
|---|---|---|---|
| GATE-001 | Immutable gateway clone | Complete | Original reference clone untouched; source commit/tree/archive hash recorded; import tag `kin-v1.1-import`; provenance document committed in gateway repository. |
| GATE-002 | Reproducible baseline and license audit | Blocked | Python 3.11/3.12 baselines are green and dependency inventory exists; imported KIN packages/repository have no declared license, so redistribution awaits owner-approved licensing. |
| GATE-003 | Architectural invariants ADR | Complete | `docs/adr/0001-gateway-architecture-invariants.md` locks A2A, local authority, credential separation, admin boundary, and scope governance. |
| GATE-004 | A2A SDK/TCK harness and profile | Complete | Pinned 265-case collection is hash-locked and exhaustively classified; the selected live-network profile passes 68/68 through KIN (Agent Card 9/9, JSON-RPC 7/7, HTTP+JSON 52/52), with complete diagnostic/accounting evidence and upstream TCK/SDK defects preserved. |
| GATE-005 | `AgentCardMirror` | Complete | Strict URL parsing, explicit private-host trust, all-answer DNS validation plus connection pinning, same-origin redirects, total-time/byte limits, SDK validation, approved-skill/public-interface projection, upstream security/signature stripping, private-reference checks, deterministic source/public hashes, ETag, and TTL cache are contract-tested. |
| GATE-006 | JSON-RPC proxy | Complete | Unmodified official client -> KIN -> unmodified official A2A 1.0 reference server returns the same task on Python 3.11/3.12; unsupported versions stop before upstream. |
| GATE-006A | Upstream credential broker v0.1 | Complete | The async `UpstreamCredentialProvider.headers_for(RequestContext)` seam has exactly `NoCredentialProvider`, `StaticHeaderCredentialProvider`, and `SecretBackedCredentialProvider`; external authority is absent from the context, secret failures stop before upstream, and replacement/canary tests pass. |
| GATE-006B | Admin-plane security boundary | Complete | Public and admin surfaces are separate FastAPI applications with `:8080` and loopback `:9090` defaults; every `/admin/*` request requires a constant-time bootstrap token check or serving-stack-verified mTLS peer certificate; negative forwarding/logging tests pass. |
| GATE-007 | REST and SSE proxy | Complete | Official HTTP+JSON send/get/list/cancel and JSON-RPC/HTTP+JSON streaming pass through KIN; status/query/body/protocol headers, SSE bytes/IDs/order/terminal events, backpressure, disconnect, origin failure, subscription routes, and inter-event timeout are contract-tested on Python 3.11/3.12. |
| GATE-008 | Task-session bridge | Complete | Each handled A2A request creates the exact nine-field observer-only `ExternalTaskSession`; deterministic credential-independent hashing, distinct session IDs, buffered task-ID observation, stream lifecycle outcomes, and fail-open observer isolation are contract-tested without importing the legacy KIN session engine or mutating A2A output. |
| GATE-014 | Demo fixture | Complete | A one-command loopback fixture proves the official SDK client receives equivalent completed `inventory.lookup` state/artifacts directly and through KIN over JSON-RPC and HTTP+JSON; mirrored-card hashes and machine-readable evidence are recorded. |
| GATE-015 | Practitioner demos | Planned | Five qualified AI/A2A practitioners view the slice and feedback is recorded. |

**Required tests:** direct JSON-RPC and REST baseline; proxy equivalence; SSE framing/order/cancellation; standard A2A card validation/rewriting; SSRF coverage for loopback, RFC1918, link-local, metadata IP, redirects, DNS rebinding, and oversized cards; deterministic request hash; upstream credential-mode and no-passthrough tests; admin-listener/admin-auth negative tests; imported KIN regression suite; imported/dependency license audit.

**CP0 exit artifacts:** import provenance and tag; baseline and license reports; ADR; `A2A_COMPATIBILITY.md`; demo fixture; public mirrored Agent Card; exact profile/TCK evidence; upstream credential contract; admin-plane setup guide.

**Out of CP0:** identity enforcement, Partner Grants, approval, web UI, chat integrations, multitenancy, hosted management plane, and production HA.

### Required `A2A_COMPATIBILITY.md` v0.1 profile

The compatibility document is a versioned release artifact, not a vague claim of “A2A support.” For v0.1 it must name the target profile as **A2A 1.0**, pin the SDK/TCK versions, and contain this matrix with an explicit test identifier for every supported item and an explicit reason for every unsupported item.

| Dimension | v0.1 contract |
|---|---|
| Discovery | Serve mirrored public Agent Card at the standard well-known location; validate/cache/hash the upstream card; never reveal private upstream URL or secrets. |
| Bindings | JSON-RPC and HTTP+JSON/REST proxying; gRPC is unsupported. |
| Task operations | Forward supported upstream task submission, retrieval/status, and cancellation operations; enforce task ownership once CP1 is enabled. |
| Streaming | Preserve upstream SSE event order, terminal event, disconnect, cancellation, and error semantics; no event synthesis or reordering. |
| Authorization denial | REST returns HTTP 403 with an A2A-compatible error payload; JSON-RPC returns the binding-correct protocol-compliant authorization error; no response reveals whether an unauthorized task/resource exists. |
| Agent Card | Mirror approved descriptive fields, interfaces, public skills, input/output modes, and configured security requirements only. |
| Caller authentication | OIDC bearer JWT and optional mTLS principal binding once CP1 is enabled; no KIN-specific caller authentication. |
| Unsupported v0.1 | gRPC, unpinned legacy compatibility, features not supported by the protected upstream, and any TCK case not listed as supported. |

Any later A2A 1.x upgrade updates this document, the pinned compatibility profile, the contract suite, and the mirrored-card behavior in the same release. No TCK test may be silently skipped.

## CP1 — Identity, Grants, Policy, Revocation, and Shadow

**Objective:** verify the caller, match a durable Partner Grant, make deterministic policy decisions, revoke quickly, and safely observe before enforcement.

| ID | Deliverable | Status | Completion evidence |
|---|---|---|---|
| GATE-009 | `PartnerGrant v0` schema | Planned | YAML/JSON validates; canonical hash/version; expiry/revoke state represented. |
| GATE-010 | Red policy tests | Planned | ALLOW, DENY, unknown, expired, revoked, and limit tests fail before evaluator integration. |
| GATE-011 | OIDC/JWT verifier | Planned | Strict issuer/audience/algorithm/JWKS/expiry/client/`azp` validation yields verified principal. |
| CP1-01 | mTLS mapping | Planned | Trusted certificate binding maps or rejects principals predictably. |
| CP1-02 | Partner relationships | Planned | Partner organization and relationship lifecycle is stored and grant-referenced. |
| CP1-03 | Deterministic evaluator | Planned | `ALLOW`, `DENY`, `REQUIRE_APPROVAL`, reason codes, obligations, grant/policy versions. |
| CP1-04 | Enforce interceptor | Planned | Unmatched, expired, or revoked request is denied before upstream receipt. |
| GATE-012 | Shadow evaluator/report | Planned | Every applicable request produces `would_*`; traffic remains unchanged. |
| CP1-05 | Fast revocation | Planned | State is durable/rechecked and effective in under five seconds. |
| CP1-06 | Task ownership isolation | Planned | Read/status/cancel binds to principal, grant, and tenant; guessed IDs fail. |
| GATE-013 | Evidence v2 prototype | Planned | Identity, task, grant, decision, policy version enter a chained record. |

**Policy properties:** default deny; explicit deny precedence; expired/revoked grants never allow; purpose comes from server-side grant rather than prompt; limits are deterministic; delegation maximum is zero unless granted; decisions retain immutable policy/grant versions.

**Security tests:** algorithm confusion and `alg:none`; issuer/audience/client mix-up; malformed/stale JWT/JWKS; forged body claims; token replay; revocation during task/stream; cross-principal task guessing; response/SSE equivalence in shadow.

**CP1 exit:** known principal allows, unknown denies, revoked grant blocks in under five seconds, and shadow forwards unchanged; OIDC/mTLS guide, threat model, policy suite, and shadow report exist; five qualified practitioner demos are completed and recorded; at least two design partners commit real staging traffic.

**Shadow gate:** operate at least five business days or 500 representative tasks. Review every `would_deny` and `would_require_approval`. Enforce only after no known legitimate high-value workflow is misclassified, no security-critical corpus case is incorrectly allowed, and policy replay is reproducible.

## CP2 — Approval, Evidence, Action Guard, and Pilot UX

**Objective:** deliver a usable paid-pilot package that gates structured consequential actions, creates independently verifiable evidence, and onboards a counterparty without KIN software.

| ID | Deliverable | Status | Completion evidence |
|---|---|---|---|
| CP2-01 | Coarse approval service | Planned | Policy can create pending approval with class, TTL, decision, and approver record. |
| CP2-02 | One-time web approval | Planned | Signed link binds session, exact request/action hash, grant/policy version, and expiry. |
| CP2-03 | Approval replay/race safety | Planned | Changed request invalidates approval; callbacks are idempotent; revoke/change races are deterministic. |
| CP2-04 | Action Guard API | Planned | Local agent/tool submits structured action/resource/attributes and gets decision/obligations. |
| CP2-05 | Mature task bridge | Planned | Task/context/cancel/status and request/result/artifact hashes correlate to session. |
| CP2-06 | Evidence event model | Planned | Ordered actor, decision, version, artifact, previous-hash, and event-hash fields. |
| CP2-07 | Hash writer and verifier | Planned | JCS/RFC 8785 plus SHA-256 chain; verifier detects edit, removal, and reorder. |
| CP2-08 | Evidence export | Planned | Tenant-scoped JSON export applies retention/redaction and includes evidence root. |
| CP2-09 | Optional invitation flow | Planned | Partner/grant invite can verify existing identity and endpoint with no KIN account; it is never required for authorization or connectivity. |
| CP2-10 | Developer CLI/scanner | Planned | Init, inspect, wrap, grant, evidence, and doctor commands are documented/tested. |
| CP2-11 | Pilot docs/contract outline | Planned | Demo, runbook, evidence schema, onboarding docs, and counsel-reviewable outline exist. |

Default evidence stores identity result, decision, policy/grant versions, protocol metadata, request/response hashes, structured action fields, approval events, and artifact hashes. Raw content is disabled by default or explicit 30-day retention; metadata defaults to 365 days. Content deletion uses cryptographic erasure plus a `content_deleted` tombstone, not a broken audit chain.

**Required no-invitation path:** customer admin enters the partner issuer and client ID, activates a Partner Grant, and the counterparty's existing A2A client calls the protected endpoint. No invitation, website, KIN account, KIN endpoint registration, or counterparty KIN software may be required. Invitations are only a convenience for coordinated identity exchange.

**CP2 exit:** demonstrate ALLOW, DENY, REQUIRE_APPROVAL, revoke, and replay; changing request/action hash invalidates approval; CLI verifies evidence independently; the no-invitation path works for a real counterparty with no KIN installation; pilot binary, runbook, and contract-outline artifacts exist.

**Pilot scope limit:** one customer, one protected agent, one external organization, one IdP, one Partner Grant family, one approval mechanism, one OTel/SIEM path, staging plus limited production, and 30 days. No customer-specific product fork.

### v0.1 paid-pilot definition of done

v0.1 is not releasable as a paid-pilot build until every item below is proven and linked from the release record:

| Requirement | Required evidence |
|---|---|
| Original preservation | Original KIN V1.1 is bit-for-bit untouched; separate clone/import provenance, checksum, commit, and tag are recorded. |
| Reproducible baseline and licensing | Clean supported Python environments reproduce the baseline; imported and dependency licenses are audited for reuse/distribution. |
| A2A interoperability | Unmodified A2A client and unmodified upstream server work through KIN for every operation in `A2A_COMPATIBILITY.md`. |
| Local upstream authority | External caller credentials do not reach the upstream by default; one approved v0.1 customer-local upstream credential mode is configured and tested. |
| Admin-plane safety | Administrative operations are on a private/loopback boundary and authenticated by bootstrap token or mTLS. |
| External identity | OIDC principal mapping works for the pilot's issuer, audience, and client/subject selector. |
| Partner policy | PartnerGrant ALLOW, DENY, expiry, task ownership, and revoke work; revoked traffic never reaches upstream. |
| Shadow safety | Shadow decisions record `would_*` result without changing request, response, status, or stream behavior. |
| Structured action control | One Action Guard action produces `REQUIRE_APPROVAL` under a real or safe-simulated policy. |
| Approval integrity | Approval is bound to exact hash, session, and policy/grant version; replay and changed-input attempts fail. |
| Evidence integrity | Evidence verification detects modification, removal, and reordering of chained events. |
| Secret and content hygiene | Secret-canary tests show no credentials in logs; raw prompts/artifacts remain off by default. |
| Reproducible customer deployment | Customer-side deployment plus documented customer-controlled emergency bypass/rollback procedure works from documentation; it explicitly states that bypass temporarily disables KIN enforcement. |
| Counterparty friction | Counterparty installs nothing; the no-invitation path succeeds with its existing A2A client. |
| Market proof | At least one real design partner agrees to run the build in staging or an agreed pilot environment. |

## CP3 — Production Hardening

**Objective:** make the self-hosted data plane credible for constrained production. Do not call it broadly enterprise-ready until every security, reliability, and deployment gate is met.

| ID | Deliverable | Status | Completion evidence |
|---|---|---|---|
| CP3-01 | PostgreSQL and migrations | Planned | Tenant-scoped production storage; N-1 -> N expand/contract migration tests. |
| CP3-02 | Artifact/object storage | Planned | Encrypted customer or S3-compatible storage with retention and hash addressing. |
| CP3-03 | KMS/secrets adapter | Planned | No production secrets in repo/config; rotation path tested. |
| CP3-04 | Hardened container | Planned | Non-root, pinned dependencies, no build tooling, explicit writable mounts, probe/drain, SBOM/digest. |
| CP3-05 | Helm/Kubernetes deployment | Planned | HA deployment, limits/probes, NetworkPolicy blocks bypass, upgrade instructions. |
| CP3-06 | Stateless/HA behavior | Planned | Restart preserves committed decisions; last-known-good policy survives management outage. |
| CP3-07 | Limits and upstream hardening | Planned | Bounded request/artifact/stream/concurrency/time plus redirect/DNS/SSRF defenses. |
| CP3-08 | Backup and DR | Planned | Backup/restore/evidence verification runbook is rehearsed. |
| CP3-09 | Load, chaos, and security suites | Planned | Soak, restart, failure, fuzz, and red-team tests run before release. |
| CP3-10 | Release and rollback | Planned | Signed artifact, canary gates, rollback triggers, and incident runbook. |
| CP3-11 | Customer-controlled break-glass bypass | Planned | Productized bypass is time-limited, authenticated, locally/customer controlled, reason-required, loudly audited, high-severity alerting, automatically expires, and is exercised; KIN cannot activate it remotely. |

| Target metric | Target |
|---|---:|
| Cached policy decision p99 | <5 ms |
| Added p95 latency at 100 RPS, small request | <25 ms |
| Added streaming time-to-first-byte | <50 ms |
| Gateway-attributable error delta | <0.1% under reference load |
| Concurrent SSE streams | 1,000 in reference C4 environment |
| Revocation propagation | <5 seconds |
| Paid-pilot availability | 99.5% |
| Mature availability after HA | 99.9% |

Required failure behavior: enforce mode fails closed when required policy state is unavailable; shadow forwards but alerts; consequential work does not proceed if required evidence cannot commit; restart does not corrupt committed decisions; gateway keeps last-known-good policy during management-plane outage. The CP2 emergency bypass is a documented customer-operated routing/rollback procedure, not a product feature. CP3-11 productizes it as a customer-controlled, time-limited, authenticated, reason-required exception with high-severity evidence, alerting, automatic expiry, and no remote KIN activation.

**CP3 exit:** eight-hour soak/benchmark report; restart and chaos evidence; no known critical/high security findings; image/SBOM/Helm/deployment/backup/rollback artifacts; defined SLOs and security review; real limited-production customer need.

## CP4 — Enterprise Integrations (gated)

Start only because active customers need these integrations, not because a generic enterprise feature checklist suggests them.

| Item | Status | Exit evidence |
|---|---|---|
| Microsoft Entra template | Deferred | End-to-end template, guide, and supported identity-flow test. |
| Okta template | Deferred | Equivalent verified guide and test. |
| Slack and Teams approvals | Deferred | Secure signed interaction reuses one-time approval abstraction. |
| SIEM mappings | Deferred | At least one real SIEM mapping with redaction verified. |
| Admin SSO/RBAC | Deferred | Least-privilege admin, policy, approver, auditor, operator roles; privileged-action audit. |
| Configurable retention/security package | Deferred | Data flow, retention, DPA inputs, subprocessors, incident/responsibility model. |

**CP4 exit:** two real enterprise IdPs, one SIEM, and one approval channel are used in a pilot or production environment.

## CP5 — Platform Scale (strictly gated)

Start only when at least five paying organizations explicitly request central management. Hosted management must improve operations without removing customer-local enforcement authority.

| Item | Status | Exit evidence |
|---|---|---|
| Hosted management plane and tenancy model | Deferred | Tenant-isolated control API and validated authorization model. |
| Signed policy bundles | Deferred | ID, version, hash, signature, activation, rollback, local verification. |
| Multi-gateway distribution | Deferred | Gateways retain/enforce last-known-good policy through outage. |
| Partition/config-version tests | Deferred | No cross-tenant leakage under property and partition testing. |
| MCP/Action Guard extensions and federation receipts | Deferred | Specific proven customer demand, not speculative platform work. |
| Disaster recovery | Deferred | Control-plane/regional outage recovery test and runbook. |

## Security, quality, and operations tracker

| Threat | Required control |
|---|---|
| Identity spoofing/JWT confusion | Exact issuer/audience/algorithm/key validation; configured principal map; optional sender constraint. |
| Confused deputy/prompt injection | Policy outside model; external token cannot become local authority; Action Guard, approval, quarantine. |
| Stale policy/delegation/task hijack | Per-request validity, revoke, max-depth-zero default, actor chain, task-principal-grant binding. |
| Approval replay/race | Exact hash/session/version/TTL binding; idempotent callback handling. |
| Data/artifact attack | Structured labels, type/size/MIME/hash/quarantine; never auto-execute. |
| SSRF/header smuggling/bypass | URL/IP/DNS/redirect protections, strict header normalization, private upstream/NetworkPolicy. |
| Audit/log/tenant attack | Canonical hash chain, redaction, tenant key/query scope, PostgreSQL RLS later. |
| DoS/supply chain | Limits/timeouts/rates; locked dependencies, SBOM, signed release, vulnerability gates. |

### Required test layers

| Layer | Scope |
|---|---|
| Unit | Policy, selectors, validity, limits, redaction, canonicalization, hashing, Agent Card rewrite. |
| Property | Deny monotonicity, expiry/revoke never allow, delegation never loosens, changed approval input changes hash, deterministic evidence root, shadow non-interference. |
| Integration | Auth -> grant -> policy -> proxy -> evidence, storage, approval, revocation, migration. |
| Contract | Unmodified A2A clients/servers across JSON-RPC, REST, streaming, supported compatibility. |
| Security/fuzz | JWT, SSRF, HTTP, task isolation, replay, secret logging, artifacts, cards, SSE, policy/admin inputs. |
| Load/chaos/E2E | Streams, restart, policy/evidence/database failure, limits, HA, real IdP and counterparty. |

### CI/CD minimum

| Stage | Required checks |
|---|---|
| Pull request | Format/lint/type, imported regression, gateway unit/contract, auth/security, fuzz smoke, dependency audit, container/SBOM, ephemeral E2E. |
| Main | All PR checks plus integration matrix, image scan/signing, staging deployment. |
| Release candidate | Load test, security corpus, N-1 migration, rollback rehearsal, manual release gate. |

Keep Python 3.11 and 3.12 initially; do not mix the product pivot with an unnecessary runtime migration.

### Data and observability requirements

| Data | Development/pilot | Paid production direction |
|---|---|---|
| Grants/config and session/evidence metadata | SQLite | PostgreSQL |
| Artifacts | Encrypted filesystem/vault | Customer or S3-compatible object store |
| Keys | OS keyring | KMS/HSM/cloud secret integration |
| Policy cache | In process | Versioned local cache and signed configuration |
| Observability | Console | Customer OTel backend; JSON/webhook initially |

Telemetry must include tenant, partner, grant/version, principal, target agent, session/task, decision/reason, approval, action, labels, and artifact hash. It must never include bearer/refresh tokens, private keys, authorization codes, credentials, raw prompts, or full artifacts by default.

Use expand/contract migrations. Roll out via shadow/canary, 5%, 25%, then 100%. Roll back on gateway 5xx/timeouts/stream deltas, policy errors, or evidence-store errors that affect consequential operations.

## Commercial validation and kill gates

### Target customer and pilot

Target a Director or Head of AI Platform/Emerging Technology at a 1,000–20,000 employee B2B company with a live A2A-capable or equivalent agent, a real external agent connection intended for production inside 90 days, and security/IAM review between prototype and production.

Record for every prospect: protected agent, counterparty, production date, identity owner, security approver, platform champion, present authorization controls, need for partner-specific policy/approval/revocation/evidence, existing Entra/Okta/Kong/AWS adequacy, staging willingness, counterparty friction, and paid-pilot potential.

| Horizon | Pass condition | Stop or reshape condition |
|---|---|---|
| Days 1–10 | 20 interviews; 15 active external-agent projects; five security/IAM reviewers; >=8 material pain; >=5 bespoke controls; >=3 staging commitments. | Fewer than five report severe pain or none has deployment inside 90 days. |
| Days 11–20 | CP0/CP1 slice proves vanilla caller -> KIN -> vanilla server with allow, deny, revoke, and shadow. | Transparent/no-modification contract cannot be preserved. |
| Days 21–30 | Two customers route repeated real tasks; one security owner says KIN removes required custom work. | Product is seen as undifferentiated gateway plumbing. |
| Day 60 | Three design partners; two staging; one enterprise IdP; >=500 shadow decisions; approval exercised; zero counterparty installs. | Existing stack is sufficient, custom code is needed per pilot, or traffic is too rare. |
| Day 90 | >=1 limited-production connection; >=1 paid $10K+ annualized commitment; security approval; second partner/agent expansion signal. | No paid commitment despite real use or no repeatability. |

Pilot pass requires one real external counterparty, at least 100 representative tasks or two weeks recurring use, zero KIN installation by the counterparty, security-approved enforcement, median new-partner setup under one hour, no customer-specific KIN fork, and a paid commitment.

### Explicit thesis abandonment thresholds

- Fewer than five of 20 qualified interviews report a severe recurring external-agent authorization/control problem.
- Fewer than three of 10 organizations with real external-agent pilots accept KIN in staging.
- At least 70% say Entra, Okta, Kong, cloud, or API gateway already solves the need.
- Customers need only ordinary authentication and scopes, not partner/purpose/action/evidence controls.
- Fewer than three of five serious pilots need more than OAuth, gateway, and logging.
- Median KIN-specific counterparty work remains above 30 minutes after one redesign, or more than 20% refuse because of KIN-specific integration.
- Typical customer sees fewer than 10 meaningful external tasks per week after 60 days and considers it occasional.
- No $10K+ annualized commitment arrives by day 90 despite real use.
- Every second customer needs custom gateway logic, or no early customer expands to a second agent/partner.
- Standards or incumbents broadly adopt the required purpose/action/data/delegation/evidence semantics, or customers judge inline-gateway risk greater than its benefit.

## Immediate ordered backlog

1. **GATE-001 — Import immutable source.** Obtain KIN V1.1, create clone, record checksum/provenance, commit, and tag.
2. **GATE-002 — Reproduce baseline and audit licenses.** Prove clean Python 3.11/3.12 install and original tests before gateway changes; inventory imported and dependency licenses before reuse or redistribution.
3. **GATE-003 — Record architectural invariants ADR.** Lock boundaries before modules drift.
4. **GATE-004 — Add A2A direct fixtures/TCK harness and profile.** Prove vanilla reference client/server before KIN insertion and define the v0.1 `A2A_COMPATIBILITY.md` contract.
5. **GATE-005 through GATE-008 — Build transparent slice.** Agent Card mirror, JSON-RPC, upstream credential broker, admin-plane boundary, REST/SSE, and task-session bridge.
6. **GATE-009 through GATE-013 — Use red tests first.** Add grants, identity, policy, revoke, shadow, and evidence prototype.
7. **GATE-014 — Create repeatable demo.** Demonstrate normal result, revoked denial, and shadow `WOULD_DENY`.
8. **GATE-015 — Run five qualified practitioner demos.** Record feedback as CP1 customer evidence before CP2 feature work.

### First demo acceptance flow

```text
Unmodified external A2A client
  -> KIN Gateway
  -> verified OIDC principal
  -> matching PartnerGrant
  -> unmodified A2A agent
  -> normal result + evidence record

Same client after grant revocation
  -> binding-correct authorization denial
     REST: HTTP 403 + A2A-compatible error payload
     JSON-RPC: protocol-compliant authorization error
  -> upstream never receives request
  -> evidence record

Same traffic in shadow
  -> KIN records WOULD_DENY and reason
  -> upstream/caller traffic remains unchanged
  -> operator can inspect report and evidence
```

## Update protocol

For every future work item, update the exact row rather than adding only a narrative note. Set its status, link the implementation location, test command/result, artifact, and related ADR/assumption. Mark a checkpoint complete only after every exit condition is proven. Record code evidence and customer evidence separately, then add a dated entry below. Do not expand deferred scope without an ADR and an updated commercial and test gate.

## Change log

| Date | Change | Evidence |
|---|---|---|
| 2026-08-10 | Added upstream credential separation: external bearer is removed and a customer-local secret-referenced header is applied at the protected-upstream boundary. | `kin_gateway/upstream/credentials.py`; `tests/contract/test_upstream_credentials.py` |
| 2026-08-10 | Established green Python 3.11/3.12 baselines, recorded the missing project-license blocker, accepted ADR 0001, pinned A2A 1.0/SDK 1.1.2, and completed the first JSON-RPC gateway red/green slice. | `docs/baseline/`; `docs/adr/0001-gateway-architecture-invariants.md`; `A2A_COMPATIBILITY.md`; `tests/contract/` |
| 2026-08-10 | Completed GATE-001: cloned both supplied repositories, imported exact KIN source history into the gateway repository, tagged `kin-v1.1-import`, and recorded commit/tree/archive provenance. CP0 is now in progress. | `UPSTREAM_KIN_V1_1_SNAPSHOT.md`; Git tag and repository remotes |
| 2026-08-10 | Final consistency pass: added scope governance; renamed planned capability heading; aligned CP1 customer gate; specified binding-correct authorization denials; separated CP2 emergency routing/rollback from CP3 productized break-glass. Scope is frozen for v0.1 implementation. | Scope final review |
| 2026-08-10 | Applied architecture-control review: locked PartnerGrant semantics; made CP0 technical-only; added upstream credential and admin-plane contracts; added pinned A2A compatibility profile; made invitations optional; added v0.1 definition of done, license audit, and customer-controlled break-glass bypass. | Scope review update |
| 2026-08-10 | Tracker created after complete review of `deep-research-report (1).md`; workspace recorded as pre-build. | Workspace inventory |
