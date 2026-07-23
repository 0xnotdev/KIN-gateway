"""Peer agent card caching, staleness detection, and owner review tracking."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from kin.schemas import PublishedAgentCard, compute_content_hash


def cache_peer_card(
    conn: sqlite3.Connection,
    peer_username: str,
    published_card: PublishedAgentCard,
) -> str:
    """Cache or update a peer's PublishedAgentCard projection.

    Returns:
        "fresh" | "stale" | "unchanged"
    """
    now_str = datetime.now(timezone.utc).isoformat()
    card_dict = published_card.model_dump()
    content_hash = compute_content_hash(card_dict)
    card_json = published_card.model_dump_json()

    cur = conn.cursor()
    cur.execute(
        "SELECT content_hash, status FROM peer_agent_cards WHERE peer_username = ? AND agent_id = ?",
        (peer_username, published_card.agent_id),
    )
    row = cur.fetchone()

    if row is None:
        cur.execute(
            """\
            INSERT INTO peer_agent_cards (
                peer_username, agent_id, card_json, content_hash, status, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 'fresh', ?, ?)
            """,
            (peer_username, published_card.agent_id, card_json, content_hash, now_str, now_str),
        )
        conn.commit()
        return "fresh"

    existing_hash, existing_status = row
    if existing_hash == content_hash:
        cur.execute(
            "UPDATE peer_agent_cards SET last_seen_at = ? WHERE peer_username = ? AND agent_id = ?",
            (now_str, peer_username, published_card.agent_id),
        )
        conn.commit()
        return "unchanged"
    else:
        cur.execute(
            """\
            UPDATE peer_agent_cards
            SET card_json = ?, content_hash = ?, status = 'stale', last_seen_at = ?
            WHERE peer_username = ? AND agent_id = ?
            """,
            (card_json, content_hash, now_str, peer_username, published_card.agent_id),
        )
        conn.commit()
        return "stale"


def mark_reviewed(conn: sqlite3.Connection, peer_username: str, agent_id: str) -> None:
    """Mark a peer agent card as reviewed by the local owner, resetting status to 'fresh'."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE peer_agent_cards SET status = 'fresh' WHERE peer_username = ? AND agent_id = ?",
        (peer_username, agent_id),
    )
    conn.commit()


def is_stale(conn: sqlite3.Connection, peer_username: str, agent_id: str) -> bool:
    """Return True if the peer card is currently marked stale."""
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM peer_agent_cards WHERE peer_username = ? AND agent_id = ?",
        (peer_username, agent_id),
    )
    row = cur.fetchone()
    if row is None:
        return False
    return row[0] == "stale"
