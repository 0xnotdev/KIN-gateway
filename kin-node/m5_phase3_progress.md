# Milestone M5, Phase 3 Progress Report: Safe Artifact Previews

## Executive Summary
Milestone M5 Phase 3 (Safe Artifact Previews) has been fully implemented and verified. The module `kin/artifacts/preview.py` introduces a pure preview engine (`generate_preview`) and a vault convenience wrapper (`get_artifact_preview`).

## Implementation Summary
- **Module `kin/artifacts/preview.py`**:
  - Implements `ArtifactPreview` dataclass with fields `preview_kind`, `content`, `truncated`, `total_size_bytes`, `rows_shown`, `total_rows_estimate`, `details`.
  - Implements `generate_preview(metadata, raw_bytes, *, max_preview_chars=8000, max_csv_rows=50)`:
    - `preview_policy == "deny"` forces `metadata_only` without reading/decoding raw payload.
    - Archive/compressed MIME types (`application/zip`, `application/x-tar`, `application/gzip`, etc.) return `metadata_only` immediately ("archive-bomb policy").
    - UTF-8 decode failure returns `metadata_only` immediately.
    - Diff detection via MIME types (`text/x-diff`, `text/x-patch`) and secondary content-sniffing fallback (`--- `, `+++ `, `@@ ` headers).
    - JSON detection with pretty-printing formatting and fallback to plain bounded text if malformed.
    - CSV detection with row bounding (`max_csv_rows`) and row count estimation, falling back to plain bounded text if malformed.
    - Markdown detection providing plain bounded text (explicitly verified to avoid HTML conversion/rendering).
    - Plain text fallback for generic text types.
  - Implements `get_artifact_preview(conn, vault_key, artifact_id, *, max_preview_chars=8000, max_csv_rows=50)` convenience function that loads metadata and bytes from the vault and executes `generate_preview`.
- **Package `kin/artifacts/__init__.py`**:
  - Re-exports `ArtifactPreview`, `generate_preview`, and `get_artifact_preview`.

## Audit & Design Decisions
1. **Configurable Bounds**: Defaults set to `DEFAULT_MAX_PREVIEW_CHARS = 8000` and `DEFAULT_MAX_CSV_ROWS = 50`.
2. **Diff Detection Strategy**: Primary MIME check (`text/x-diff`, `text/x-patch`) + secondary content-sniffing fallback (checking for `--- `, `+++ `, `@@ ` headers in generic text).
3. **Cross-Artifact Diff Scope**: Deferred to Phase 5. Single-artifact diff formatting handled in Phase 3 when raw content is diff-shaped.
4. **`preview_policy` Semantics**: `"deny"` forces `metadata_only`. `"auto"` (and any unrecognized/other string value) evaluates for richest safe preview.

## Verification & Test Results
- **Scoped Suite Run**: `py -3.11 -m pytest tests/test_artifacts_preview.py -v` $\rightarrow$ 10 passed in 0.13s.
- **3x Full Suite (Flag Set: `$env:KIN_UNSAFE_TEST_KEYRING="1"`)**:
  - Run 1: `1140 passed, 1 deselected, 1 warning in 61.67s`
  - Run 2: `1140 passed, 1 deselected, 1 warning in 61.05s`
  - Run 3: `1140 passed, 1 deselected, 1 warning in 59.49s`
- **3x Full Suite (Flag Unset: `Remove-Item Env:\KIN_UNSAFE_TEST_KEYRING`)**:
  - Run 1: `1140 passed, 1 deselected, 1 warning in 60.00s`
  - Run 2: `1140 passed, 1 deselected, 1 warning in 59.62s`
  - Run 3: `1140 passed, 1 deselected, 1 warning in 59.97s`

## Git Commit
Commit created with message: `"feat(m5): implement Phase 3 safe artifact preview module and tests"`
