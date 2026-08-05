# KIN V1.1 Final Repository Readiness

Date: 2026-08-05
Branch: `codex/v11-final-release-readiness`
Authority: Master Spec §§3.2, 6–10, 15.11–15.12 and TUI System §§14.10–14.11

## Repository outcome

The V1.1 implementation and automated release-candidate assets are complete.
The release decision remains **NO RELEASE** until the signed publication and
physical two-laptop gates below are executed. This distinction is deliberate:
the repository can be acceptance-tested now, but an unpublished artifact cannot
truthfully be called an installable signed release.

## Final systemic defects found and closed

1. Package metadata still reported 0.1.0 and lacked production TUI entry points.
   Node/relay now report 1.1.0; `kin tui` and `kin-tui` are packaged.
2. Clean Windows wheel installation backtracked to an unsupported Rust source
   build. Runtime and development dependencies are now exact release pins.
3. First Flight existed as disconnected/dead render code. The production
   launcher now mounts a complete keyboard-only create/restore/card/relay/OOB
   pairing/demo/dispatch flow and persists completion.
4. Ordinary signed session messages were lost when direct and relay delivery
   were both temporarily unavailable. They now enter the encrypted durable
   outbound queue.
5. Relay polling and outbound retry had no production caller. Every served node
   now runs an immediate and five-second background synchronization lifecycle,
   including relay fallback during retry.
6. Safe tag-in was falsely documented as absent although a partial primitive
   existed. Arena now uses an owner-gated local-agent picker, shows boundaries,
   sends a signed `participant_changed`, caps the handoff transcript, and
   excludes every local-only event/private note.
7. SDK cards raised `NotImplementedError`; webhook cards read the wrong config
   attribute; adapter timeouts waited during executor cleanup. All four declared
   adapters now execute through the normalized boundary with tests.
8. Spinner release snapshots depended on wall-clock/frame timing. Their real
   mounted overlay references now pin both sources deterministically.
9. The installer checksum URL was circular: a post-build manifest cannot live in
   its pre-build signed tag. The installer now retrieves both immutable-version
   release assets (wheel and manifest), while the signed tag remains source
   authority.
10. The first exact dependency lock audit identified four advisories against
    `cryptography==46.0.7`. The release pin and Windows lock were advanced to the
    fully fixed `50.0.0` line before publication; the audit was rerun.
11. Three production identity writers still persisted protocol `0.1.0` while
    V1.1 capability negotiation required `1.1`. All release and identity
    surfaces now use the single constants in `kin.version`.
12. Fresh session objectives and approval request bodies could be written as
    plaintext despite the at-rest boundary. Every production writer now uses
    AES-256-GCM; one authenticated legacy-aware reader handles existing V1
    plaintext without ever masking wrong-key or damaged-ciphertext failures.

## Automated evidence

- Final default node suite: `1616 passed, 5 deselected in 159.33s`;
  `101 snapshots passed`.
- Final real-process smoke gate: `5 passed, 1616 deselected in 177.74s`.
- Relay suite: `12 passed in 0.79s`.
- Primary/reference snapshot matrix: `101 snapshots passed`.
- Phase B real-process relay/restart/expiry/artifact gate:
  `1 passed in 74.00s`, including explicit equal stored/computed SHA-256.
- Clean node and relay wheels build successfully; a fresh constrained Windows
  environment reports no broken requirements and exposes `KIN 1.1.0 (protocol
  1.1)` with `cryptography==50.0.0`.
- Three consecutive full TUI processes:
  - run 1: `1207 passed, 2 deselected in 95.88s`; `101 snapshots passed`;
  - run 2: `1207 passed, 2 deselected in 91.25s`; `101 snapshots passed`;
  - run 3: `1207 passed, 2 deselected in 91.27s`; `101 snapshots passed`.
- Focused final encrypted-storage/transport/CLI/history/TUI proof:
  `104 passed in 15.13s`.
- Exact dependency audit: `No known vulnerabilities found`.
- Bandit medium/high severity scan: no findings.

## Real / fixture boundary

- T8 smoke launches actual relay and node `subprocess.Popen` processes on real
  loopback ports. Alice and Bob use separate homes, databases, keys, and worker
  processes. Production background synchronization may consume a relay envelope
  before the explicit probe; evidence records which consumer won and still
  requires exactly one persisted event, ACK, and no duplicate.
- Cryptographic tests use real Ed25519/X25519 operations, encrypted SQLite
  payloads/artifacts, and separate profiles. HTTP is mocked only where a test is
  specifically isolating the external edge.
- Snapshot fixtures pin terminal capabilities and clocks but do not replace the
  real-process smoke boundary.

## External release gates — still open

1. Review/commit this diff, create signed tag `v1.1.0`, and verify it.
2. Run `scripts/build_release.ps1`; publish every artifact plus `SHA256SUMS` to
   the matching GitHub release.
3. Run `docs/v1.1/TWO-LAPTOP-ACCEPTANCE.md` on two independent Windows laptops
   and accounts, with no database/protocol edits and redacted evidence only.
4. Record product/security owner approval in `docs/v1.1/RELEASE-CHECKLIST.md`.

The installer and docs intentionally refuse to pretend those human authorities
have already happened.
