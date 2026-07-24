"""Local Agent Card registry management, directory scanning, and lifecycle operations."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from kin.identity.resolver import ProfileContextResolver
from kin.schemas import AgentAvailability, AgentCard, PublishedAgentCard
from kin.storage.vault import encrypt_field
from kin.agent_registry.availability import compute_availability
from kin.agent_registry.loader import CardLoadError, is_v11_card_file, load_card_file


def get_agents_dir(resolver: ProfileContextResolver) -> Path:
    """Resolve active profile's agents directory using ProfileContextResolver."""
    return resolver.resolve_profile_path(resolver.active_profile, "agents")


def publish_card(card: AgentCard) -> PublishedAgentCard:
    """Construct safe public PublishedAgentCard projection field-by-field.

    Guaranteed not to leak adapter details, boundaries, autonomy, or presentation.
    """
    return PublishedAgentCard(
        schema_version="1.1",
        protocol_version="1.1",
        agent_id=card.id,
        name=card.name,
        description=card.description,
        capabilities=card.capabilities,
        availability=AgentAvailability.READY,
        requires_owner_acceptance=True,
    )


def scan_local_cards(
    agents_dir: Path,
    profile_name: str | None = None,
) -> tuple[list[AgentCard], list[CardLoadError], list[Path]]:
    """Scan directory for agent YAML files.

    Returns:
        (valid_cards, per_file_errors, legacy_v1_files_skipped)
    """
    valid_cards: list[AgentCard] = []
    per_file_errors: list[CardLoadError] = []
    legacy_v1_files_skipped: list[Path] = []

    if not agents_dir.is_dir():
        return valid_cards, per_file_errors, legacy_v1_files_skipped

    yaml_files = sorted(list(agents_dir.glob("*.yaml")) + list(agents_dir.glob("*.yml")))
    seen_ids: set[str] = set()

    for path in yaml_files:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            raw = None

        if not isinstance(raw, dict) or not is_v11_card_file(raw):
            legacy_v1_files_skipped.append(path)
            continue

        try:
            card = load_card_file(path, expected_agent_id=path.stem, profile_name=profile_name)
            if card.id in seen_ids:
                raise CardLoadError(
                    f"File '{path.name}': Duplicate agent ID '{card.id}' already claimed by an earlier file in scan."
                )
            seen_ids.add(card.id)
            valid_cards.append(card)
        except CardLoadError as err:
            per_file_errors.append(err)

    return valid_cards, per_file_errors, legacy_v1_files_skipped


def register_card(
    conn: sqlite3.Connection,
    vault_key: bytes,
    card: AgentCard,
    *,
    enabled: bool | None = None,
    profile_name: str | None = None,
) -> None:
    """Upsert AgentCard into local SQLite database with encrypted storage and version tracking."""
    now_str = datetime.now(timezone.utc).isoformat()
    local_card_json = encrypt_field(vault_key, card.model_dump_json())

    cur = conn.cursor()
    cur.execute("SELECT card_version, created_at, enabled FROM agents WHERE agent_id = ?", (card.id,))
    row = cur.fetchone()

    if row is not None:
        version = row[0] + 1
        created_at = row[1]
        target_enabled = row[2] if enabled is None else (1 if enabled else 0)
    else:
        version = 1
        created_at = now_str
        target_enabled = 1 if (enabled is True or enabled is None) else 0

    pub_card = publish_card(card)
    if profile_name is not None:
        pub_card.availability = compute_availability(card, profile_name, enabled=bool(target_enabled))

    published_card_json = pub_card.model_dump_json()

    if row is not None:
        cur.execute(
            """\
            UPDATE agents
            SET name = ?, adapter_type = ?, local_card_json = ?, published_card_json = ?,
                enabled = ?, availability = ?, updated_at = ?, card_version = ?
            WHERE agent_id = ?
            """,
            (
                card.name,
                card.adapter.type,
                local_card_json,
                published_card_json,
                target_enabled,
                pub_card.availability.value,
                now_str,
                version,
                card.id,
            ),
        )
    else:
        cur.execute(
            """\
            INSERT INTO agents (
                agent_id, name, adapter_type, local_card_json, published_card_json,
                enabled, availability, created_at, updated_at, card_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card.id,
                card.name,
                card.adapter.type,
                local_card_json,
                published_card_json,
                target_enabled,
                pub_card.availability.value,
                created_at,
                now_str,
                version,
            ),
        )
    conn.commit()


def list_cards(conn: sqlite3.Connection, include_disabled: bool = False) -> list[dict[str, Any]]:
    """List registered local agents with metadata and published card projection."""
    cur = conn.cursor()
    if include_disabled:
        cur.execute(
            """\
            SELECT agent_id, name, adapter_type, enabled, availability, card_version, updated_at, published_card_json
            FROM agents ORDER BY agent_id ASC
            """
        )
    else:
        cur.execute(
            """\
            SELECT agent_id, name, adapter_type, enabled, availability, card_version, updated_at, published_card_json
            FROM agents WHERE enabled = 1 ORDER BY agent_id ASC
            """
        )
    rows = cur.fetchall()
    result = []
    for row in rows:
        published_json = row[7]
        parsed_published = None
        if published_json:
            try:
                parsed_published = json.loads(published_json)
            except Exception:
                parsed_published = published_json

        result.append(
            {
                "agent_id": row[0],
                "name": row[1],
                "adapter_type": row[2],
                "enabled": bool(row[3]),
                "availability": row[4],
                "card_version": row[5],
                "updated_at": row[6],
                "published_card": parsed_published,
                "published_card_json": published_json,
            }
        )
    return result


def get_card(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any] | None:
    """Retrieve full database record for a local agent."""
    cur = conn.cursor()
    cur.execute(
        """\
        SELECT agent_id, name, adapter_type, local_card_json, published_card_json,
               enabled, availability, created_at, updated_at, card_version
        FROM agents WHERE agent_id = ?
        """,
        (agent_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "agent_id": row[0],
        "name": row[1],
        "adapter_type": row[2],
        "local_card_json": row[3],
        "published_card_json": row[4],
        "enabled": bool(row[5]),
        "availability": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "card_version": row[9],
    }


def set_enabled(conn: sqlite3.Connection, agent_id: str, enabled: bool, profile_name: str | None = None, vault_key: bytes | None = None) -> None:
    """Enable or disable a local agent and update its availability state."""
    now_str = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute("SELECT local_card_json FROM agents WHERE agent_id = ?", (agent_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"Agent '{agent_id}' does not exist in registry.")

    new_avail = AgentAvailability.POLICY_BLOCKED.value if not enabled else AgentAvailability.READY.value
    if enabled and profile_name is not None and vault_key is not None and row[0] is not None:
        from kin.storage.vault import decrypt_field
        decrypted = decrypt_field(vault_key, row[0])
        if decrypted:
            card = AgentCard.model_validate_json(decrypted)
            new_avail = compute_availability(card, profile_name, enabled=True).value

    cur.execute(
        "UPDATE agents SET enabled = ?, availability = ?, updated_at = ? WHERE agent_id = ?",
        (1 if enabled else 0, new_avail, now_str, agent_id),
    )
    conn.commit()


def import_card(
    conn: sqlite3.Connection,
    vault_key: bytes,
    resolver: ProfileContextResolver,
    source_path: Path,
) -> AgentCard:
    """Validate, copy source card file into profile agents directory, and register in database."""
    agents_dir = get_agents_dir(resolver)
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Standalone validation on source_path (no expected_agent_id requirement for source filename)
    card = load_card_file(source_path, profile_name=resolver.active_profile)

    dest_path = agents_dir / f"{card.id}.yaml"
    if dest_path.exists() and source_path.resolve() != dest_path.resolve():
        raise CardLoadError(f"Cannot import card '{card.id}': destination file '{dest_path.name}' already exists.")

    # Check for duplicate ID claimed by a different filename
    valid_cards, _, _ = scan_local_cards(agents_dir, profile_name=resolver.active_profile)
    for existing in valid_cards:
        if existing.id == card.id and not dest_path.exists():
            raise CardLoadError(f"Cannot import card '{card.id}': agent ID is already claimed by an existing card in agents directory.")

    if source_path.resolve() != dest_path.resolve():
        shutil.copy2(source_path, dest_path)

    register_card(conn, vault_key, card, profile_name=resolver.active_profile)
    return card
