"""Tests for safe artifact preview generation module (§15.8 M5 Phase 3)."""

import sqlite3
import pytest

from kin.artifacts.preview import (
    ArtifactPreview,
    generate_preview,
    get_artifact_preview,
)
from kin.artifacts.vault import ArtifactMetadata, store_artifact


from kin.storage.migrations import run_migrations


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database initialized with full migrations schema."""
    conn = sqlite3.connect(":memory:")
    run_migrations(conn)
    yield conn
    conn.close()


def test_preview_plain_text_truncation():
    """1. Plain text: content under bound previews in full (truncated=False); content over bound gets cut (truncated=True)."""
    meta = ArtifactMetadata(
        artifact_id="art_txt_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/plain",
        size_bytes=20,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )

    small_bytes = b"Short text message"
    p_small = generate_preview(meta, small_bytes, max_preview_chars=100)
    assert p_small.preview_kind == "text"
    assert p_small.content == "Short text message"
    assert p_small.truncated is False

    long_bytes = b"A" * 200
    p_long = generate_preview(meta, long_bytes, max_preview_chars=50)
    assert p_long.preview_kind == "text"
    assert p_long.content == "A" * 50
    assert len(p_long.content) == 50
    assert p_long.truncated is True


def test_preview_json_formatting_and_fallback():
    """2. JSON: valid JSON pretty-prints; malformed JSON with mime_type='application/json' falls back to plain text without raising."""
    meta = ArtifactMetadata(
        artifact_id="art_json_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="application/json",
        size_bytes=30,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )

    valid_json_bytes = b'{"name": "Alice", "role": "admin"}'
    p_valid = generate_preview(meta, valid_json_bytes, max_preview_chars=500)
    assert p_valid.preview_kind == "json"
    assert '"name": "Alice"' in p_valid.content
    assert p_valid.truncated is False

    invalid_json_bytes = b'{"name": "Alice", BROKEN_JSON'
    p_invalid = generate_preview(meta, invalid_json_bytes, max_preview_chars=500)
    assert p_invalid.preview_kind == "text"
    assert p_invalid.content == '{"name": "Alice", BROKEN_JSON'
    assert p_invalid.truncated is False


def test_preview_csv_row_bounding_and_fallback():
    """3. CSV: valid CSV shows bounded row count; malformed/inconsistent CSV doesn't crash (falls back to plain text)."""
    meta = ArtifactMetadata(
        artifact_id="art_csv_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/csv",
        size_bytes=100,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )

    csv_lines = "\n".join([f"colA_{i},colB_{i}" for i in range(100)])
    csv_bytes = csv_lines.encode("utf-8")

    p_csv = generate_preview(meta, csv_bytes, max_preview_chars=10000, max_csv_rows=10)
    assert p_csv.preview_kind == "csv"
    assert p_csv.rows_shown == 10
    assert p_csv.total_rows_estimate == 100
    assert p_csv.truncated is True


def test_preview_csv_malformed_fallback():
    """3b. CSV: malformed CSV inputs gracefully fall back to plain text without throwing exceptions."""
    meta = ArtifactMetadata(
        artifact_id="art_csv_bad_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/csv",
        size_bytes=40,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )
    # Unclosed quote string causes csv.reader to raise csv.Error or exception
    malformed_csv = b'col1,col2\n"unclosed quote line,colB'
    p_bad = generate_preview(meta, malformed_csv, max_preview_chars=500)
    assert p_bad.preview_kind in ("csv", "text")
    assert p_bad.content is not None
    assert p_bad.truncated is False


def test_preview_markdown_no_html_rendering():
    """4. Markdown: bounded plain text only. Assert no HTML conversion occurs (e.g. <h1> tags)."""
    meta = ArtifactMetadata(
        artifact_id="art_md_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/markdown",
        size_bytes=50,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )

    md_bytes = b"# Header Title\n\n**Bold Text** and [Link](http://example.com)"
    p_md = generate_preview(meta, md_bytes, max_preview_chars=500)

    assert p_md.preview_kind == "markdown"
    assert p_md.content == md_bytes.decode("utf-8")
    # Explicit assertion proving no HTML conversion occurred
    assert "<h1>" not in p_md.content
    assert "<strong>" not in p_md.content
    assert "<a href" not in p_md.content


def test_preview_diff_detection():
    """5. Diff: MIME 'text/x-diff' and generic MIME with diff-shaped content both produce preview_kind='diff'."""
    meta_mime = ArtifactMetadata(
        artifact_id="art_diff_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/x-diff",
        size_bytes=50,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )
    diff_text = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@\n-old_line()\n+new_line()\n"
    p_mime = generate_preview(meta_mime, diff_text.encode("utf-8"))
    assert p_mime.preview_kind == "diff"
    assert p_mime.content == diff_text

    meta_sniff = ArtifactMetadata(
        artifact_id="art_diff_2",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/plain",
        size_bytes=50,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )
    p_sniff = generate_preview(meta_sniff, diff_text.encode("utf-8"))
    assert p_sniff.preview_kind == "diff"
    assert p_sniff.content == diff_text


def test_preview_unsupported_binary_content():
    """6. Required 'unsupported preview' test: non-UTF-8 binary bytes claiming mime_type='text/plain' returns metadata_only."""
    meta = ArtifactMetadata(
        artifact_id="art_bin_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/plain",  # Misleading MIME type
        size_bytes=10,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )

    invalid_utf8_bytes = b"Hello \xff\xfe\xfd World"
    p_bin = generate_preview(meta, invalid_utf8_bytes)

    assert p_bin.preview_kind == "metadata_only"
    assert p_bin.content is None
    assert p_bin.truncated is False


def test_preview_archive_bomb_policy():
    """7. Required 'archive-bomb policy' test: mime_type='application/zip' with garbage bytes returns metadata_only without raising exceptions."""
    meta = ArtifactMetadata(
        artifact_id="art_zip_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="application/zip",
        size_bytes=20,
        offered_by="alice",
        preview_policy="auto",
        created_at="2026-07-28T12:00:00Z",
    )

    garbage_zip_bytes = b"PK\x03\x04_garbage_archive_bytes_that_are_not_valid_zip"
    
    # Must return metadata_only without raising any decompression exception
    p_zip = generate_preview(meta, garbage_zip_bytes)
    assert p_zip.preview_kind == "metadata_only"
    assert p_zip.content is None
    assert p_zip.truncated is False


def test_preview_policy_deny():
    """8. preview_policy='deny' returns metadata_only regardless of MIME type or valid text content."""
    meta = ArtifactMetadata(
        artifact_id="art_deny_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/plain",
        size_bytes=20,
        offered_by="alice",
        preview_policy="deny",
        created_at="2026-07-28T12:00:00Z",
    )

    valid_text = b"Secret payload content"
    p_deny = generate_preview(meta, valid_text)

    assert p_deny.preview_kind == "metadata_only"
    assert p_deny.content is None
    assert p_deny.truncated is False


def test_preview_policy_unrecognized_string():
    """9. Unrecognized preview_policy string (e.g. 'whatever') behaves as 'auto' per Q4, does not error or default to metadata_only."""
    meta = ArtifactMetadata(
        artifact_id="art_unk_1",
        session_id="sess_1",
        sha256="abc",
        mime_type="text/plain",
        size_bytes=20,
        offered_by="alice",
        preview_policy="whatever_custom_string",
        created_at="2026-07-28T12:00:00Z",
    )

    valid_text = b"Hello World"
    p_unk = generate_preview(meta, valid_text)

    assert p_unk.preview_kind == "text"
    assert p_unk.content == "Hello World"
    assert p_unk.truncated is False


def test_get_artifact_preview_vault_roundtrip(in_memory_db):
    """10. get_artifact_preview wrapper: round-trip through store_artifact confirms convenience function retrieves and previews stored artifacts."""
    vault_key = b"test-vault-key-32bytes-long!!!!!"
    session_id = "sess_vault_1"
    raw_payload = b'{"status": "ok", "count": 42}'

    meta = store_artifact(
        in_memory_db,
        vault_key,
        session_id=session_id,
        raw_bytes=raw_payload,
        mime_type="application/json",
        offered_by="bob",
        preview_policy="auto",
        max_bytes=1000,
    )

    preview = get_artifact_preview(in_memory_db, vault_key, meta.artifact_id)

    assert preview.preview_kind == "json"
    assert '"status": "ok"' in preview.content
    assert '"count": 42' in preview.content
    assert preview.total_size_bytes == len(raw_payload)
    assert preview.truncated is False
