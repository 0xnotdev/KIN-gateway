# KIN V1.1 Boundaries and Release Gates

Updated: 2026-08-05.

There are no knowingly unfinished V1.1 product code paths represented as
available. The following are intentional architecture boundaries or external
release gates, not hidden implementation deferrals.

## Product boundaries

- KIN V1.1 supports exactly two independent owners per session. Public
  discovery, global reputation, payments, multi-owner teams, direct peer tool
  control, and a graphical client are outside V1.1 by specification.
- The relay stores routing metadata and opaque X25519 ciphertext. It cannot
  decrypt collaboration content. Relay availability is not required for local
  history or direct delivery; signed outbound envelopes enter the encrypted
  durable retry queue when both paths are unavailable.
- A secure OS credential backend is mandatory in production. The
  `KIN_UNSAFE_TEST_KEYRING` escape hatch is rejected unless explicitly enabled
  and is only for isolated tests.
- Local SQLite append-only triggers and peer signatures provide the V1.1 audit
  model. Root-level compromise of a device is outside the threat boundary.
- Advanced export templates are P2. V1.1 includes deterministic plain-text
  export, policy redaction, private-note exclusion, and signed-note promotion.

## Human and publication gates

The repository is a release candidate until all items below are complete:

1. Review and commit the final diff on a clean tree.
2. Create and verify signed tag `v1.1.0`.
3. Run `scripts/build_release.ps1`; upload both distributions and
   `SHA256SUMS` to the matching immutable GitHub release.
4. Execute `docs/v1.1/TWO-LAPTOP-ACCEPTANCE.md` on two independent Windows
   laptops/accounts and retain only redacted evidence.
5. Obtain the product and security owner signatures in
   `docs/v1.1/RELEASE-CHECKLIST.md`.

Until those external gates pass, the honest decision is **NO RELEASE**, even
when every automated suite is green. Development installs from the reviewed
checkout remain supported for acceptance testing.
