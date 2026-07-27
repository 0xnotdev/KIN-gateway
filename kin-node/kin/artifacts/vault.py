"""Encrypted artifact vault storage module (§15.8 M5 Phase 1)."""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass

from kin.storage.vault import decrypt_bytes, encrypt_bytes


def _iso_now(now: datetime.datetime | None = None) -> str:
    """Canonical ISO 8601 UTC timestamp helper ending in 'Z'."""
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    res = now.isoformat()
    if res.endswith("+00:00"):
        res = res[:-6] + "Z"
    elif not res.endswith("Z"):
        res = res + "Z"
    return res


class ArtifactNotFoundError(Exception):
    """Raised when the requested artifact_id does not exist in storage."""


class ArtifactTooLargeError(Exception):
    """Raised when an artifact exceeds maximum byte limits before storage."""


class ArtifactCorruptedError(Exception):
    """Raised when decryption fails or the decrypted payload SHA-256 hash drifts."""


class ArtifactIdConflictError(Exception):
    """Raised when an artifact_id already exists in storage with a differing SHA-256 hash."""


@dataclass(frozen=True)
class ArtifactMetadata:
    """Typed metadata summary for an encrypted vault artifact."""

    artifact_id: str
    session_id: str
    sha256: str
    mime_type: str
    size_bytes: int
    offered_by: str
    preview_policy: str
    created_at: str
    source: str = "adapter_output"


def store_artifact(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    session_id: str,
    raw_bytes: bytes,
    mime_type: str,
    offered_by: str,
    preview_policy: str,
    max_bytes: int,
    source: str = "adapter_output",
    now: datetime.datetime | None = None,
    artifact_id: str | None = None,
) -> ArtifactMetadata:
    """Computes SHA-256 directly, enforces max_bytes, encrypts raw_bytes, and persists metadata and ciphertext."""
    if len(raw_bytes) > max_bytes:
        raise ArtifactTooLargeError(
            f"Artifact size {len(raw_bytes)} bytes exceeds limit of {max_bytes} bytes."
        )

    sha = hashlib.sha256(raw_bytes).hexdigest()

    if artifact_id is not None:
        cur = conn.cursor()
        cur.execute(
            "SELECT sha256 FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        )
        row = cur.fetchone()
        if row is not None:
            stored_sha = row[0]
            if stored_sha == sha:
                return get_artifact_metadata(conn, artifact_id)
            else:
                raise ArtifactIdConflictError(
                    f"Artifact ID '{artifact_id}' already exists with different sha256 (stored: {stored_sha}, new: {sha})."
                )
    else:
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"

    now_str = _iso_now(now)
    enc_bytes = encrypt_bytes(vault_key, raw_bytes)

    meta_payload = {
        "size_bytes": len(raw_bytes),
        "preview_policy": preview_policy,
        "source": source,
    }

    conn.execute(
        """\
        INSERT INTO artifacts (
            artifact_id, session_id, sha256, mime_type,
            bytes_encrypted, metadata_json, offered_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            session_id,
            sha,
            mime_type,
            enc_bytes,
            json.dumps(meta_payload),
            offered_by,
            now_str,
        ),
    )
    conn.commit()

    return ArtifactMetadata(
        artifact_id=artifact_id,
        session_id=session_id,
        sha256=sha,
        mime_type=mime_type,
        size_bytes=len(raw_bytes),
        offered_by=offered_by,
        preview_policy=preview_policy,
        created_at=now_str,
        source=source,
    )


def load_artifact_bytes(
    conn: sqlite3.Connection,
    vault_key: bytes,
    artifact_id: str,
) -> bytes:
    """Fetches, decrypts, and verifies SHA-256 hash integrity of a stored artifact blob."""
    cur = conn.cursor()
    cur.execute(
        "SELECT sha256, bytes_encrypted FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found.")

    stored_sha, bytes_encrypted = row

    try:
        decrypted = decrypt_bytes(vault_key, bytes_encrypted)
    except Exception as e:
        raise ArtifactCorruptedError(
            f"Artifact '{artifact_id}' decryption failed: {e}"
        ) from e

    if decrypted is None:
        raise ArtifactCorruptedError(f"Artifact '{artifact_id}' decrypted payload is None.")

    computed_sha = hashlib.sha256(decrypted).hexdigest()
    if computed_sha != stored_sha:
        raise ArtifactCorruptedError(
            f"Artifact '{artifact_id}' SHA-256 hash mismatch: expected {stored_sha}, computed {computed_sha}."
        )

    return decrypted


def get_artifact_metadata(
    conn: sqlite3.Connection,
    artifact_id: str,
) -> ArtifactMetadata:
    """Fetches artifact metadata without requiring vault_key or querying bytes_encrypted."""
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT artifact_id, session_id, sha256, mime_type, metadata_json, offered_by, created_at
        FROM artifacts WHERE artifact_id = ?
        """,
        (artifact_id,),
    )
    row = cur.fetchone()
    if not row:
        raise ArtifactNotFoundError(f"Artifact '{artifact_id}' not found.")

    art_id, session_id, sha, mime_type, meta_json, offered_by, created_at = row

    size_bytes = 0
    preview_policy = "none"
    source = "adapter_output"

    if meta_json:
        try:
            meta_dict = json.loads(meta_json)
            size_bytes = meta_dict.get("size_bytes", meta_dict.get("size", 0))
            preview_policy = meta_dict.get("preview_policy", "none")
            source = meta_dict.get("source", "adapter_output")
        except json.JSONDecodeError:
            pass

    return ArtifactMetadata(
        artifact_id=art_id,
        session_id=session_id,
        sha256=sha,
        mime_type=mime_type,
        size_bytes=size_bytes,
        offered_by=offered_by,
        preview_policy=preview_policy,
        created_at=created_at,
        source=source,
    )
