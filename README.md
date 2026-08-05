# KIN V1.1

KIN is a local-first, owner-controlled personal agent collaboration network. Two
people can pair identities out of band, choose their own agents, collaborate
through signed/encrypted sessions, review consequential actions locally, exchange
verified artifacts, and export a deterministic audit trail.

## Install on Windows

The supported non-developer path is the pinned, checksum-verifying PowerShell
installer documented in [docs/v1.1/INSTALL-WINDOWS.md](docs/v1.1/INSTALL-WINDOWS.md).
Until the signed `v1.1.0` GitHub release is published, use a reviewed checkout for
acceptance testing:

```powershell
cd kin-node
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\kin --version
.\.venv\Scripts\kin doctor --plain
.\.venv\Scripts\kin tui
```

Use a different profile/username on each computer. See the
[quick start](docs/v1.1/QUICKSTART.md),
[privacy model](docs/v1.1/PRIVACY.md), and
[two-laptop acceptance](docs/v1.1/TWO-LAPTOP-ACCEPTANCE.md).

## Repository layout

- `kin-node/`: CLI, TUI, local node, encrypted persistence, policy, adapters,
  transport, tests, and real-process smoke harnesses.
- `kin-relay/`: blind directory and store-and-forward encrypted mailbox.
- `install.ps1` / `uninstall.ps1`: versioned per-user installation lifecycle.
- `docs/v1.1/`: operator, migration, backup, privacy, troubleshooting, and
  acceptance documentation.

The release checklist is intentionally strict: green automation alone does not
replace signed artifacts, a physical two-laptop run, or product/security owner
approval. See [release readiness](kin-node/v11_release_readiness_progress.md).
