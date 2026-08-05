"""Classified, expiring Context Pantry packs with opaque local references."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable
import uuid

from pydantic import BaseModel, ConfigDict, Field

from kin.storage.vault import decrypt_field, encrypt_field


MAX_CONTEXT_ITEM_BYTES = 5 * 1024 * 1024


class PantryValidationError(ValueError):
    """Safe dispatch-blocking error that never contains local filesystem data."""


class ReviewedContextItem(BaseModel):
    """Peer-visible wire projection; deliberately has no path/reference fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.1"
    item_id: str
    kind: str
    classification: str = "share_with_peer"
    content: str
    size_bytes: int = Field(ge=0)
    expires_at: str | None = None


class PantryItemSpec(BaseModel):
    """Serializable local pack item; attaching it remains an explicit caller action."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    size_bytes: int = Field(ge=0)
    classification: str
    expiry: str | None = None
    item_id: str
    content: str | None = None
    local_ref_id: str | None = None
    reviewed: bool = False


class StoredContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_id: str
    name: str
    items: list[PantryItemSpec]


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PantryValidationError("Context expiry must include a UTC timezone.")
    return parsed.astimezone(timezone.utc)


def register_local_reference(
    conn: sqlite3.Connection,
    vault_key: bytes,
    path: Path,
    *,
    expires_at: str | None = None,
) -> str:
    """Store one exact file path encrypted and return a non-browsable opaque ID."""
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise PantryValidationError("The selected local reference is unavailable.") from exc
    if not resolved.is_file():
        raise PantryValidationError("The selected local reference is not a readable file.")
    ref_id = f"ctxref_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn.execute(
        """INSERT INTO context_pantry_refs
               (ref_id, encrypted_path, size_bytes, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (ref_id, encrypt_field(vault_key, str(resolved)), resolved.stat().st_size, expires_at, now),
    )
    conn.commit()
    return ref_id


def create_context_pack(
    conn: sqlite3.Connection,
    vault_key: bytes,
    *,
    name: str,
    items: Iterable[Any],
) -> StoredContextPack:
    """Persist a local-first pack without attaching or transmitting it."""
    specs = [
        PantryItemSpec(
            kind=getattr(item, "kind"),
            size_bytes=getattr(item, "size_bytes"),
            classification=getattr(item, "classification"),
            expiry=getattr(item, "expiry", None),
            item_id=getattr(item, "item_id", "") or f"ctx_{uuid.uuid4().hex}",
            content=getattr(item, "content", None),
            local_ref_id=getattr(item, "local_ref_id", None),
            reviewed=False,
        )
        for item in items
    ]
    pack = StoredContextPack(
        pack_id=f"ctxpack_{uuid.uuid4().hex}",
        name=name.strip() or "Context pack",
        items=specs,
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn.execute(
        """INSERT INTO context_packs (pack_id, name, items_json_enc, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (pack.pack_id, pack.name, encrypt_field(vault_key, pack.model_dump_json()), now, now),
    )
    conn.commit()
    return pack


def attach_context_pack(
    conn: sqlite3.Connection,
    vault_key: bytes,
    pack_id: str,
) -> list[PantryItemSpec]:
    """Return a detached copy for explicit draft attachment; every shared item needs re-review."""
    row = conn.execute("SELECT items_json_enc FROM context_packs WHERE pack_id = ?", (pack_id,)).fetchone()
    if row is None:
        raise PantryValidationError("Context pack not found.")
    stored = StoredContextPack.model_validate_json(decrypt_field(vault_key, row[0]) or "{}")
    return [item.model_copy(update={"reviewed": False}) for item in stored.items]


def build_reviewed_context_pack(
    conn: sqlite3.Connection,
    vault_key: bytes,
    items: Iterable[Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Resolve only owner-reviewed peer-shareable items into the signed wire pack."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pack: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        classification = getattr(item, "classification", None)
        if classification in {"local_only", "private"}:
            continue
        if classification != "share_with_peer":
            raise PantryValidationError(f"Context item {index + 1} has an invalid classification.")
        if not bool(getattr(item, "reviewed", False)):
            raise PantryValidationError(f"Context item {index + 1} must be reviewed before it can be shared.")
        expiry = getattr(item, "expiry", None)
        if expiry and current >= _parse_utc(expiry):
            raise PantryValidationError(f"Context item {index + 1} expired and cannot be shared.")

        kind = getattr(item, "kind", "")
        content = getattr(item, "content", None)
        item_id = getattr(item, "item_id", None) or f"ctx_{index + 1}"
        effective_expiry = expiry
        if kind == "local_reference":
            ref_id = getattr(item, "local_ref_id", None)
            if not ref_id:
                raise PantryValidationError(f"Context item {index + 1} has no valid local reference.")
            row = conn.execute(
                "SELECT encrypted_path, expires_at FROM context_pantry_refs WHERE ref_id = ?",
                (ref_id,),
            ).fetchone()
            if row is None:
                raise PantryValidationError(f"Context item {index + 1} is unavailable; select it again.")
            effective_expiry = expiry or row[1]
            if effective_expiry and current >= _parse_utc(effective_expiry):
                raise PantryValidationError(f"Context item {index + 1} expired and cannot be shared.")
            try:
                resolved = Path(decrypt_field(vault_key, row[0]) or "")
                if not resolved.is_file():
                    raise OSError("not a file")
                content = resolved.read_text(encoding="utf-8")
            except Exception as exc:
                raise PantryValidationError(
                    f"Context item {index + 1} could not be read; select it again."
                ) from exc

        if not isinstance(content, str) or not content:
            raise PantryValidationError(f"Context item {index + 1} has no shareable content.")
        content_size = len(content.encode("utf-8"))
        if content_size > MAX_CONTEXT_ITEM_BYTES:
            raise PantryValidationError(
                f"Context item {index + 1} exceeds the {MAX_CONTEXT_ITEM_BYTES}-byte size limit."
            )
        reviewed = ReviewedContextItem(
            item_id=item_id,
            kind=kind,
            content=content,
            size_bytes=content_size,
            expires_at=effective_expiry,
        )
        pack.append(reviewed.model_dump(mode="json"))
    return json.loads(json.dumps(pack, ensure_ascii=False))
