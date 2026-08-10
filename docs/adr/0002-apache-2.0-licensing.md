# ADR 0002 — Apache-2.0 licensing for KIN Gateway

- Status: Accepted
- Date: 2026-08-10

## Context

KIN Gateway imports the KIN V1.1 source snapshot and builds the new external-agent gateway layer on top of it. The imported repository did not previously declare a project license, which blocked public redistribution and the CP0 release tag.

The repository owner explicitly confirmed on 2026-08-10 that they are the sole copyright holder of all original KIN source code imported into KIN Gateway, or otherwise have sufficient authorization to license every imported contribution under the Apache License 2.0, and that there are no third-party contributions whose rights prevent that licensing.

## Decision

KIN Gateway, including the imported KIN V1.1 source contained in this repository and the gateway modifications, is licensed under the Apache License, Version 2.0.

The repository root contains the canonical `LICENSE` text and a `NOTICE` file. Python package metadata declares SPDX license expression `Apache-2.0` and includes `LICENSE` and `NOTICE` as license files.

Third-party dependencies remain governed by their own licenses. The dependency inventory for the CP0 baseline is maintained in `docs/baseline/GATE-002-DEPENDENCY-LICENSES.md` and must continue to be regenerated/reviewed at release boundaries.

## Consequences

- Public source redistribution is permitted under Apache-2.0, subject to its terms.
- Copyright, license, patent, trademark, and attribution notices that apply to distributed source must be preserved as required by the license.
- Modified files distributed as derivative works must satisfy Apache-2.0 redistribution requirements.
- This decision does not relicense third-party dependencies under Apache-2.0.
- Future commercial or hosted components may use separate licensing only if their code and distribution boundaries are explicitly documented; this ADR governs the code released from this repository unless superseded by a founder-approved ADR.
- Any future contribution workflow must avoid importing code whose terms are incompatible with this repository's distribution obligations.

## CP0 release gate

Satisfied on 2026-08-10. Fresh Python 3.11.9 and 3.12.13 installations report
`License-Expression: Apache-2.0` for `kin-cli`, `kin-gateway`, and `kin-relay`;
each distribution also includes `LICENSE` and `NOTICE`. The exhaustive inventories
are under `docs/baseline/evidence/gate-002/`, and the complete licensed-tree
regression matrix is recorded in `docs/baseline/GATE-002-BASELINE.md`.
