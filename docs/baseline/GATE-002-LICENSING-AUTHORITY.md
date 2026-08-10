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

## GATE-002 completion proof

The final dependency/project audit and full CP0 regression were rerun against
the licensed tree in fresh Python 3.11.9 and 3.12.13 environments. Installed
metadata for `kin-cli`, `kin-gateway`, and `kin-relay` now reports
`Apache-2.0`; no installed distribution lacked a declared license signal. The
gateway 51-case suite, imported 1,617-case node suite plus 101 snapshots,
12-case relay suite, selected 68-case live TCK, and canonical demo all passed.

Evidence is recorded in `docs/baseline/GATE-002-BASELINE.md`,
`docs/baseline/GATE-002-DEPENDENCY-LICENSES.md`, and
`docs/baseline/evidence/gate-002/`. GATE-002 is complete.
