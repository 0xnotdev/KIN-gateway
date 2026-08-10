# GATE-002 — Licensing authority confirmation

Date: 2026-08-10

Repository: `0xnotdev/KIN-gateway`

Imported KIN provenance is recorded separately in `UPSTREAM_KIN_V1_1_SNAPSHOT.md`.

## Founder confirmation

The repository owner/founder explicitly confirmed that they are the sole copyright holder of all original KIN source code imported into KIN Gateway, or otherwise have sufficient authorization to license every imported contribution under the Apache License 2.0, and that there are no third-party contributions whose rights prevent them from doing so.

This confirmation resolves the ownership/authority question that blocked selection of a project license. It does not replace the dependency-license audit: third-party dependencies remain under their own terms.

## Approved project license

Apache License 2.0 (`Apache-2.0`) is approved for the code distributed from this repository at the CP0 boundary.

The release tree must contain:

- root `LICENSE` with the canonical Apache License 2.0 text;
- root `NOTICE` with project attribution and third-party-license pointer;
- Python project metadata declaring SPDX expression `Apache-2.0` and including `LICENSE`/`NOTICE` as license files;
- ADR 0002 recording the licensing decision.

## Remaining GATE-002 proof

GATE-002 is not complete merely because authority was confirmed. Before marking it complete and creating `v0.0.1-cp0`, rerun the final dependency/project license audit against the licensed tree and verify that project-owned KIN packages no longer appear as `UNKNOWN` because of missing project metadata. Then rerun the required CP0 regression/contract checks, verify both worktrees are clean, and record the final evidence.
