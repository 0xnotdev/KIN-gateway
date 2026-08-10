# GATE-002 Reproducible Baseline

## Source under test

- Import tag: `kin-v1.1-import`
- Source commit: `58258fb037ea49f23d8e572ad7cd9df59ef5e388`
- Host: Windows, PowerShell
- Test date: 2026-08-10
- Node test environment variable: `KIN_UNSAFE_TEST_KEYRING=1`

The baseline was run after the immutable import and before any gateway application code was added. The only commit after the import tag contained planning/provenance documentation.

## Environments

| Environment | Interpreter | Installation |
|---|---|---|
| Python 3.11 | CPython 3.11.9 | Editable `kin-node[dev]` and `kin-relay[dev]` from pinned project metadata. |
| Python 3.12 | CPython 3.12.13 | Editable `kin-node[dev]` and `kin-relay[dev]` from pinned project metadata. |

Workspace-local environments were created outside the Git repository under `D:\KIN Gateway\.venvs` so the source tree remained clean.

## Results

| Python | Package | Result | Duration |
|---|---|---:|---:|
| 3.11.9 | `kin-node` | 1,617 passed; 9 deselected; 101 snapshots passed | 173.42 s |
| 3.11.9 | `kin-relay` | 12 passed | 3.71 s |
| 3.12.13 | `kin-node` | 1,617 passed; 9 deselected; 101 snapshots passed | 168.81 s |
| 3.12.13 | `kin-relay` | 12 passed | 3.69 s |

All four processes exited with status zero.

## Final CP0 regression

The same imported suites were rerun after the complete CP0 gateway
implementation, TCK harness, and canonical demo were in place. They retained
the exact baseline counts on both supported interpreters:

| Python | Package | Final CP0 result |
|---|---|---:|
| 3.11.9 | `kin-node` | 1,617 passed; 9 deselected; 101 snapshots passed |
| 3.11.9 | `kin-relay` | 12 passed |
| 3.12.13 | `kin-node` | 1,617 passed; 9 deselected; 101 snapshots passed |
| 3.12.13 | `kin-relay` | 12 passed |

All four final-regression processes exited with status zero. The immutable
reference clone was separately checked afterward and remained clean at source
commit `58258fb037ea49f23d8e572ad7cd9df59ef5e388` and tree
`808d495e70f7d03ac75f2ecaff50b29280fed494`.

## Licensed-tree freeze regression

After Apache-2.0 metadata was applied to all three project distributions, new
environments at `D:\KIN Gateway\.venvs\cp0-license-311` and
`D:\KIN Gateway\.venvs\cp0-license-312` reproduced the final matrix:

| Python | Suite | Freeze result | Duration |
|---|---|---:|---:|
| 3.11.9 | Gateway contract | 51 passed | 3.06 s |
| 3.12.13 | Gateway contract | 51 passed | 3.08 s |
| 3.11.9 | `kin-node` | 1,617 passed; 9 deselected; 101 snapshots passed | 158.12 s |
| 3.12.13 | `kin-node` | 1,617 passed; 9 deselected; 101 snapshots passed | 150.32 s |
| 3.11.9 | `kin-relay` | 12 passed | 0.98 s |
| 3.12.13 | `kin-relay` | 12 passed | 1.00 s |
| 3.11.9 | Selected live A2A TCK | 68 passed | 19.01 s |
| 3.11.9 | Canonical direct/proxy demo | Both bindings equivalent | Pass |

All processes exited zero. The known dependency warnings remained unchanged.

## Commands

```powershell
$env:KIN_UNSAFE_TEST_KEYRING='1'
& 'D:\KIN Gateway\.venvs\kin-gateway-311\Scripts\python.exe' -m pytest -q
& 'D:\KIN Gateway\.venvs\kin-gateway-312\Scripts\python.exe' -m pytest -q
```

Run the node commands from `kin-node`. Run the relay commands from `kin-relay` without the unsafe test keyring environment variable.

## Known baseline warning

Both packages emit one `StarletteDeprecationWarning` from `fastapi.testclient`: using `httpx` with `starlette.testclient` is deprecated in favor of `httpx2`. This is a dependency-level warning in the imported baseline, not a gateway regression. It does not fail the current suite.

## License audit status

The original import had no declared project license; that historical baseline is
why GATE-002 initially blocked release. The repository owner subsequently
confirmed authority over all imported contributions and approved Apache-2.0 in
ADR 0002. The freeze tree now contains root `LICENSE`/`NOTICE`, and installed
metadata for `kin-cli`, `kin-gateway`, and `kin-relay` reports `Apache-2.0` on
both supported interpreters.

The final exhaustive inventories and reproduction command are in
`docs/baseline/GATE-002-DEPENDENCY-LICENSES.md`. GATE-002 is complete.
