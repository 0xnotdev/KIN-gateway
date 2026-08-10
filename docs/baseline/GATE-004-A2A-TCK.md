# GATE-004 A2A SDK and TCK Evidence

## Pinned profile

- A2A specification: `a2aproject/A2A@v1.0.0`
- A2A Python SDK: `a2a-sdk==1.1.2`
- A2A TCK repository: `https://github.com/a2aproject/a2a-tck.git`
- A2A TCK commit: `5996b79f9cefa6fc390980e383e358a66fb9e49e`
- TCK runtime used for evidence: Python 3.11.9
- TCK collection: 265 cases
- collection SHA-256: `63fa842e4fa0b35e9570e79fe313d0aed07118964ed863b8d03583fa0e3cd18c`

`tests/contract/tck-manifest.yaml` is JSON-compatible YAML. It contains the exact 68 supported node IDs plus ordered, count-locked exclusion rules. `scripts/verify_tck_manifest.py` checks the Git commit, collection count/hash, supported IDs, every exclusion count, every unmatched case, and supported-case status in the full diagnostic JUnit report.

## Live topology

```text
pinned TCK client
        |
        v
KIN gateway 127.0.0.1:18080
        |
        v
unmodified a2a-sdk 1.1.2 inventory agent 127.0.0.1:18081
```

The TCK discovers only KIN's public Agent Card. That card advertises JSON-RPC at `/a2a/jsonrpc` and HTTP+JSON at `/a2a/rest`. The private reference Agent Card is fetched, validated, filtered, hashed, and rewritten by the same `AgentCardMirror` used in contract tests.

## Results

### Selected supported profile

- 68 passed
- 0 failed
- 0 skipped
- Agent Card: 9/9
- JSON-RPC: 7/7
- HTTP+JSON: 52/52

The green selected-profile reports are in `docs/baseline/evidence/gate-004/supported-profile/`.

### Full diagnostic accounting

- raw pytest result: 69 passed, 67 failed, 121 skipped, 2 expected-failed, 6 errors;
- manifest-selected passes: 68;
- expected-unsupported: 108;
- tracked TCK/SDK defects: 89;
- unaccounted: 0.

The raw result is not presented as full A2A TCK conformance. Its purpose is to prove that every pinned case was seen and classified. The complete HTML/JSON/JUnit reports and exact per-node accounting are in `docs/baseline/evidence/gate-004/full-diagnostic/`.

## Material upstream limitations

### `TCK-JSONRPC-ENDPOINT-PATH`

The pinned TCK `JsonRpcClient` constructs an `httpx.Client` from the Agent Card interface URL but calls `POST "/"`. For a standards-valid non-root interface such as `http://gateway/a2a/jsonrpc`, URL resolution discards `/a2a/jsonrpc` and sends to the origin root. KIN does not add a root alias because the frozen profile and released SDK use the full advertised interface URL. Raw endpoint-aware TCK JSON-RPC cases and all official-SDK contract tests remain green.

### `TCK-GENERATED-SUT-NOT-PINNED`

The TCK's generated Python SUT declares an unresolved sibling source at `../../../a2a-python` and does not pin a companion commit. Its generated imports do not work with released `a2a-sdk` 0.3.0, 0.3.26, 1.0.0, or 1.1.2: the code combines `a2a.server.apps` and `a2a.types.a2a_pb2_grpc` layouts that do not coexist in those releases. TCK scenario-specific artifact, history, input-required, and multi-stream tests therefore cannot be reproduced from the pinned TCK repository alone. KIN's reference fixture intentionally remains the released 1.1.2 `inventory.lookup` agent rather than importing an unpinned SDK source tree.

### Released SDK behavior outside the selected profile

The released SDK strictly rejects the TCK's two SHOULD-level unknown-field probes and accepts its wrong-Content-Type REST probe instead of returning 415. These remain tracked and visible. Optional `Last-Modified` is not selected; deterministic ETag and Cache-Control are selected and pass. gRPC, push delivery/configuration, extended Agent Cards, and implicit A2A 0.3 downgrade are explicitly outside CP0.

## Reproduce

From a clean TCK checkout at the pinned commit:

```powershell
.\scripts\run_cp0_tck.ps1 `
  -TckPath "C:\path\to\a2a-tck" `
  -Python "C:\path\to\kin-gateway-python.exe"
```

The runner uses `uv sync --python 3.11`, validates the commit and manifest, starts both fixture listeners hidden, waits for public discovery, executes exactly the selected node IDs, writes reports under `.artifacts/cp0-tck/`, and stops both listeners in a `finally` block.

## Release-freeze rerun

The selected profile was rerun on the Apache-2.0 licensed tree on 2026-08-10.
The manifest again verified all 265 collected cases with 68 supported, 108
expected-unsupported, 89 tracked defects, and zero unaccounted cases. All 68
selected cases passed in 19.01 seconds (Agent Card 9/9, JSON-RPC 7/7,
HTTP+JSON 52/52).
