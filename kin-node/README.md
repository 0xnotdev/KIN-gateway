# KIN V1.1

KIN is a keyboard-first personal-agent collaboration network. Each person runs
their own local node and retains their own identity, agent cards, policy,
approvals, private notes, artifacts, and audit history. Peer-visible traffic is
signed; relay fallback is end-to-end encrypted; a peer never inherits local tool
authority.

## Install on Windows

From PowerShell, inspect and run the pinned installer documented in
[`../docs/v1.1/INSTALL-WINDOWS.md`](../docs/v1.1/INSTALL-WINDOWS.md). A release
is valid only when its Git tag is signed and its wheel matches the published
`SHA256SUMS` entry.

After installation:

```powershell
kin --version
kin doctor --plain
kin tui
```

`kin tui` enters resumable First Flight for a new profile. The full two-computer
journey is in
[`../docs/v1.1/TWO-LAPTOP-ACCEPTANCE.md`](../docs/v1.1/TWO-LAPTOP-ACCEPTANCE.md).

## Core safety contract

- Ed25519 identity and signed V1.1 envelopes; X25519 relay encryption.
- Fingerprints must be compared out of band before trust is recorded.
- Direct delivery is attempted first; opaque relay fallback is safe across
  disconnects and restarts.
- Consequential actions are approved only by the owner of the executing node,
  for an exact scope and expiry.
- Private notes stay local unless their exact text is deliberately promoted as
  a newly signed peer-visible message.
- Exports are deterministic and policy-redacted. Hidden reasoning, credentials,
  and unapproved local paths are excluded.

## Scriptable operation

Every primary TUI flow has a plain or JSON CLI route. Discover the full surface
with `kin --help`; the principal commands are `dispatch`, `inbox`, `session`,
`approval`, `agent`, `pair`, `fetch`, `serve`, `doctor`, and `migrate`.

Profiles are isolated with `kin --profile NAME ...` and live under
`~/.kin/profiles/NAME`. Run one profile per person/system. Never copy a live
profile to create a second identity.

## Development and verification

```powershell
cd kin-node
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pytest -q -m smoke

cd ..\kin-relay
python -m pip install -e ".[dev]"
python -m pytest -q
```

The default suite excludes the real-process smoke marker; run both commands.
Any HTTP route added under `kin/node/routes.py` must have a real FastAPI
`TestClient` test. Release builds are produced only by
`../scripts/build_release.ps1` from a clean, signed version tag.

## Release and operations documentation

- [Quick start](../docs/v1.1/QUICKSTART.md)
- [Migration](../docs/v1.1/MIGRATION.md)
- [Privacy model](../docs/v1.1/PRIVACY.md)
- [Troubleshooting](../docs/v1.1/TROUBLESHOOTING.md)
- [Relay operator guide](../docs/v1.1/RELAY-OPERATOR.md)
- [Backup and recovery](../docs/v1.1/BACKUP-RECOVERY.md)
- [Security and incident reporting](../SECURITY.md)
- [Release checklist](../docs/v1.1/RELEASE-CHECKLIST.md)

Protocol authority remains
[`../KIN-V1.1-MASTER-SPEC.md`](../KIN-V1.1-MASTER-SPEC.md) and
[`../system-design-v1.1.md`](../system-design-v1.1.md).

