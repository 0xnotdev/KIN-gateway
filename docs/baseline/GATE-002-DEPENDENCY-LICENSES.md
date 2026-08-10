# GATE-002 Dependency and Project License Audit

Audit date: 2026-08-10

Release target: `v0.0.1-cp0`

## Result

**PASS.** The licensed release-candidate tree was installed into newly created
Python 3.11.9 and 3.12.13 environments. Every installed distribution exposed at
least one license-expression, legacy-license, or license-classifier signal, and
all project-owned packages exposed the required SPDX expression.

| Project package | Version | Python 3.11 | Python 3.12 | License files in installed metadata |
|---|---:|---|---|---|
| `kin-cli` | 1.1.0 | `Apache-2.0` | `Apache-2.0` | `LICENSE`, `NOTICE` |
| `kin-gateway` | 0.1.0.dev0 | `Apache-2.0` | `Apache-2.0` | `LICENSE`, `NOTICE` |
| `kin-relay` | 1.1.0 | `Apache-2.0` | `Apache-2.0` | `LICENSE`, `NOTICE` |

The root project and both independently installed imported subprojects declare
`license = "Apache-2.0"` and package content-equivalent canonical `LICENSE` and
`NOTICE` texts. This removes the pre-license `UNKNOWN` metadata for `kin-cli`,
`kin-gateway`, and `kin-relay` while keeping standalone distributions complete.

## Environments and exhaustive evidence

| Interpreter | Installed distributions | Distributions with no declared license signal | Gate |
|---|---:|---:|---|
| CPython 3.11.9 | 105 | 0 | Pass |
| CPython 3.12.13 | 102 | 0 | Pass |

The machine-readable inventories preserve every distribution's name, version,
SPDX expression, legacy license value, license classifiers, declared license
files, and project URLs:

- `docs/baseline/evidence/gate-002/license-audit-python311.json`
- `docs/baseline/evidence/gate-002/license-audit-python312.json`

The different inventory counts are interpreter/environment dependency details,
not missing KIN packages. Both environments contain and pass all three required
project-package checks.

## Packaging verification

All three projects were built as wheels and source distributions using their
declared `setuptools==83.0.0` and `wheel==0.47.0` backend requirements. Direct
inspection of each final wheel confirmed:

| Distribution | SPDX expression | `License-File` headers | Embedded license files |
|---|---|---|---|
| `kin_gateway-0.1.0.dev0` | `Apache-2.0` | `LICENSE`, `NOTICE` | `LICENSE`, `NOTICE` |
| `kin_cli-1.1.0` | `Apache-2.0` | `LICENSE`, `NOTICE` | `LICENSE`, `NOTICE` |
| `kin_relay-1.1.0` | `Apache-2.0` | `LICENSE`, `NOTICE` | `LICENSE`, `NOTICE` |

This proves the independently buildable package artifacts are self-contained,
not merely labeled by editable-install metadata.

## Reproduce

Install the root project, `kin-node`, and `kin-relay` into a clean supported
environment, then run:

```powershell
python scripts\audit_cp0_licenses.py `
  --output .artifacts\license-audit.json
```

The standard-library audit exits non-zero unless all three KIN distributions
declare `License-Expression: Apache-2.0` and each installed distribution's
metadata contains both `LICENSE` and `NOTICE`.

## Boundary of the claim

Apache-2.0 governs the project-owned source in this repository; it does not
relicense third-party dependencies. The evidence records the license metadata
published by each installed dependency. A metadata inventory is not a legal
opinion about every possible downstream combination or distribution channel;
third-party notices and terms must continue to be reviewed at release
boundaries.
