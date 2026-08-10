# ADR 0001: KIN Gateway Architecture Invariants

- Status: Accepted
- Date: 2026-08-10
- Authority: `scope.md`
- Applies to: v0.1 and all implementation work until superseded by an approved ADR and scope amendment

## Context

KIN V1.1 is a local-first personal-agent collaboration network. The gateway product preserves its useful policy, approval, session, artifact, cryptographic, audit, and replay primitives while replacing the public product path with a standards-compatible enforcement point for externally controlled agents.

The main architectural risk is implementation convenience silently changing the authority boundary. This ADR turns the frozen scope invariants into an implementation contract.

## Decision

1. A2A is the public agent-to-agent protocol. Every release pins an explicit compatibility profile in `A2A_COMPATIBILITY.md`.
2. A counterparty uses an unmodified standard A2A client and installs no KIN component or SDK.
3. The enforcement data plane runs inside the protected customer's trust domain.
4. KIN verifies existing OIDC/OAuth/mTLS identities; it does not issue external identity.
5. Request-body organization, purpose, or authority claims are untrusted unless independently bound to server-side configuration.
6. Authorization is deterministic and reproducible. An LLM never makes an ALLOW, DENY, or REQUIRE_APPROVAL decision.
7. External caller credentials do not become protected-agent or local-tool credentials.
8. Shadow mode records decisions but does not alter the upstream request or caller response.
9. Enforce mode fails closed for new protected work when required policy state is unavailable.
10. The protected upstream is not directly reachable from the external path in production deployments.
11. Evidence is described and tested as tamper-evident, not tamper-proof.
12. Raw prompts and artifacts are not retained by default; credentials and secrets are never logged.
13. Every persisted object, cache key, query, and administrative operation is tenant scoped.
14. Hosted management, federation, MCP expansion, reputation, payments, and other deferred features require their checkpoint gate and an approved scope amendment.
15. External caller credentials are not forwarded upstream by default. KIN uses a customer-owned upstream identity selected by local configuration.
16. Data-plane and admin-plane access are separated. The bootstrap admin plane is private by default and authenticated before enterprise SSO/RBAC is introduced.

## Authority flow

```text
external caller credential
  -> KIN transport authentication
  -> ExternalPrincipal mapping
  -> PartnerRelationship and PartnerGrant lookup
  -> deterministic policy decision
  -> customer-local upstream credential selection
  -> protected customer agent
```

The external credential proves who initiated the request. It never grants the protected agent's local authority.

## v0.1 upstream credential modes

v0.1 supports only:

1. Private, unauthenticated local upstream reachable only from KIN.
2. Static customer-owned service credential loaded from secret storage.
3. Configurable customer-owned bearer or header credential loaded from secret storage.

Raw external-credential passthrough is disabled. Token exchange and workload federation are later compatibility work.

## Domain semantics

- `PartnerRelationship` is a durable relationship between organizations.
- `PartnerGrant` is a durable, versioned authority template governing that relationship.
- `ExternalTaskSession` is one actual A2A task under one immutable Partner Grant version.
- `ActionAuthorization` is one structured consequential action within that task.

An `ExternalTaskGrant` must not be introduced unless it represents distinct task-specific temporary authority and is approved by ADR.

## Consequences

- A generic transparent proxy is insufficient; identity, grant, evidence, and credential separation are first-class modules.
- Deep business-action policy requires Action Guard or another structured local enforcement boundary.
- Admin endpoints cannot share an unauthenticated public listener with A2A routes.
- Every supported A2A operation needs both interoperability and authorization/ownership tests.
- Policy-store failure, evidence-store failure, and customer emergency bypass have explicit operational behavior.
- Internal refactoring is permitted only when these observable contracts remain unchanged.

## Change control

Implementation agents may not weaken this ADR. A change requires a new ADR that identifies the affected invariant, migration and security consequences, test changes, and a founder-approved amendment to `scope.md`.
