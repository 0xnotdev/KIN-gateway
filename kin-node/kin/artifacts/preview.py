"""Safe artifact preview generation module (§15.8 M5 Phase 3)."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from kin.artifacts.vault import (
    ArtifactMetadata,
    get_artifact_metadata,
    load_artifact_bytes,
)

DEFAULT_MAX_PREVIEW_CHARS: int = 8000
DEFAULT_MAX_CSV_ROWS: int = 50

# List of archive/compressed MIME types that immediately return metadata_only
ARCHIVE_MIME_TYPES: set[str] = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-tar",
    "application/tar",
    "application/gzip",
    "application/x-gzip",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/rar",
    "application/x-bzip2",
    "application/x-compress",
}


@dataclass(frozen=True)
class ArtifactPreview:
    """Typed result representing a bounded, safe preview of an artifact."""

    preview_kind: Literal["text", "markdown", "json", "csv", "diff", "metadata_only"]
    content: str | None
    truncated: bool
    total_size_bytes: int
    rows_shown: int | None = None
    total_rows_estimate: int | None = None
    details: dict[str, Any] | None = None


def _is_diff_content(text: str) -> bool:
    """Check if the text content looks like a unified diff."""
    lines = text.lstrip().splitlines()[:10]
    has_minus = any(line.startswith("--- ") for line in lines)
    has_plus = any(line.startswith("+++ ") for line in lines)
    has_hunk = any(line.startswith("@@ ") for line in lines)
    return (has_minus and has_plus) or has_hunk


def generate_preview(
    metadata: ArtifactMetadata,
    raw_bytes: bytes,
    *,
    max_preview_chars: int = DEFAULT_MAX_PREVIEW_CHARS,
    max_csv_rows: int = DEFAULT_MAX_CSV_ROWS,
) -> ArtifactPreview:
    """Pure function generating a bounded, safe preview object from raw bytes and metadata."""
    total_size = len(raw_bytes)

    # 1. Rule out preview_policy == "deny" (per Q4)
    policy = (metadata.preview_policy or "").strip().lower()
    if policy == "deny":
        return ArtifactPreview(
            preview_kind="metadata_only",
            content=None,
            truncated=False,
            total_size_bytes=total_size,
        )

    # 2. Rule out archive/compressed MIME types ("archive-bomb policy")
    mime = (metadata.mime_type or "").strip().lower()
    if mime in ARCHIVE_MIME_TYPES:
        return ArtifactPreview(
            preview_kind="metadata_only",
            content=None,
            truncated=False,
            total_size_bytes=total_size,
        )

    # 3. UTF-8 decode check (if binary or invalid UTF-8 -> metadata_only)
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ArtifactPreview(
            preview_kind="metadata_only",
            content=None,
            truncated=False,
            total_size_bytes=total_size,
        )

    # 4. Determine preview kind and generate preview content
    # Check for diff MIME or content-sniffing fallback (per Q2)
    if mime in ("text/x-diff", "text/x-patch") or _is_diff_content(text):
        bounded_content = text[:max_preview_chars]
        truncated = len(text) > max_preview_chars
        return ArtifactPreview(
            preview_kind="diff",
            content=bounded_content,
            truncated=truncated,
            total_size_bytes=total_size,
        )

    # Check JSON
    if "json" in mime:
        try:
            val = json.loads(text)
            formatted = json.dumps(val, indent=2)
            bounded_content = formatted[:max_preview_chars]
            truncated = len(formatted) > max_preview_chars
            return ArtifactPreview(
                preview_kind="json",
                content=bounded_content,
                truncated=truncated,
                total_size_bytes=total_size,
            )
        except Exception:
            # Malformed JSON falls back to plain text
            pass

    # Check CSV
    if mime in ("text/csv", "application/csv") or mime.endswith("+csv"):
        try:
            f = io.StringIO(text)
            reader = csv.reader(f)
            rows = []
            row_count = 0
            for row in reader:
                row_count += 1
                if len(rows) < max_csv_rows:
                    rows.append(row)

            # Format rows as plain text CSV
            output_f = io.StringIO()
            writer = csv.writer(output_f)
            writer.writerows(rows)
            formatted_csv = output_f.getvalue()

            bounded_content = formatted_csv[:max_preview_chars]
            truncated = (row_count > max_csv_rows) or (len(formatted_csv) > max_preview_chars)
            return ArtifactPreview(
                preview_kind="csv",
                content=bounded_content,
                truncated=truncated,
                total_size_bytes=total_size,
                rows_shown=len(rows),
                total_rows_estimate=row_count,
            )
        except Exception:
            # Malformed CSV falls back to plain text
            pass

    # Check Markdown
    if mime in ("text/markdown", "text/x-markdown") or mime.endswith("+markdown"):
        bounded_content = text[:max_preview_chars]
        truncated = len(text) > max_preview_chars
        return ArtifactPreview(
            preview_kind="markdown",
            content=bounded_content,
            truncated=truncated,
            total_size_bytes=total_size,
        )

    # Default plain text
    bounded_content = text[:max_preview_chars]
    truncated = len(text) > max_preview_chars
    return ArtifactPreview(
        preview_kind="text",
        content=bounded_content,
        truncated=truncated,
        total_size_bytes=total_size,
    )


def get_artifact_preview(
    conn: sqlite3.Connection,
    vault_key: bytes,
    artifact_id: str,
    *,
    max_preview_chars: int = DEFAULT_MAX_PREVIEW_CHARS,
    max_csv_rows: int = DEFAULT_MAX_CSV_ROWS,
) -> ArtifactPreview:
    """Convenience wrapper that retrieves metadata + bytes from vault and runs generate_preview."""
    meta = get_artifact_metadata(conn, artifact_id)
    raw_bytes = load_artifact_bytes(conn, vault_key, artifact_id)
    return generate_preview(
        meta,
        raw_bytes,
        max_preview_chars=max_preview_chars,
        max_csv_rows=max_csv_rows,
    )
