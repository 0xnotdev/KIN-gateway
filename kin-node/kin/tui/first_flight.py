"""First Flight Controller for KIN V1.1 TUI.

Orchestrates setup steps by composing real underlying backend functions from
kin.identity, kin.agent_registry, kin.storage, and SQLite profile DBs.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.6
"""

import os
import random
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.agent_registry.loader import load_card_file
from kin.agent_registry.registry import scan_local_cards
from kin.cli import DEFAULT_ENDPOINT, DEFAULT_RELAY_URL, open_profile_db
from kin.identity.fingerprint import compute_fingerprint
from kin.identity.keys import derive_key_pair, derive_x25519_key_pair, generate_recovery_phrase
from kin.identity.setup import verify_phrase_confirmation
from kin.identity.storage import (
    SecretNotFoundError,
    load_private_key,
    load_x25519_private_key,
    save_private_key,
    save_x25519_private_key,
)
from kin.storage.db import create_schema, get_setting, set_setting
from kin.tui.persistence import UiStatePreferences, load_ui_preferences, save_ui_preferences
from kin.tui.state import RecoverableError
from kin.version import V11_PROTOCOL_VERSION


class FirstFlightController:
    """Orchestrator for First Flight onboarding setup (§14.6).

    Composes real underlying kin.* backend functions while maintaining strict
    controller/widget separation and zero-secret UI state persistence.
    """

    STEP_SEQUENCE = [
        "identity",
        "agent",
        "relay",
        "pairing",
        "demo",
        "guided_dispatch",
        "complete",
    ]

    def __init__(self, profile_name: str = "default", profile_dir: Optional[Path] = None) -> None:
        self.profile_name = profile_name
        self.profile_dir = profile_dir or (Path.home() / ".kin" / "profiles" / profile_name)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.profile_dir / "kin.db"
        self.relay_url = os.environ.get("KIN_RELAY_URL", DEFAULT_RELAY_URL)

    def _ensure_db(self) -> sqlite3.Connection:
        conn = open_profile_db(self.db_path)
        create_schema(conn)
        return conn

    def check_durable_state(self) -> Dict[str, Any]:
        """Query real durable state to determine which setup steps are completed (§14.6)."""
        conn = self._ensure_db()
        username = None
        has_identity = False
        has_contacts = False
        contact_count = 0

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM identity LIMIT 1")
            row = cursor.fetchone()
            if row:
                username = row[0]
                try:
                    load_private_key(self.profile_name)
                    has_identity = True
                except Exception:
                    has_identity = False

            cursor.execute("SELECT COUNT(*) FROM contacts WHERE fingerprint_verified_at IS NOT NULL")
            contact_count = cursor.fetchone()[0]
            has_contacts = contact_count > 0

            # Check agents table in SQLite DB
            cursor.execute("SELECT COUNT(*) FROM agents")
            db_agent_count = cursor.fetchone()[0]
        finally:
            conn.close()

        # Check local agent registry YAML directory
        agents_dir = self.profile_dir / "agents"
        local_cards, _, _ = scan_local_cards(agents_dir)
        total_agent_count = db_agent_count + len(local_cards)
        has_agents = total_agent_count > 0

        return {
            "has_identity": has_identity,
            "username": username,
            "has_agents": has_agents,
            "agent_count": total_agent_count,
            "has_contacts": has_contacts,
            "contact_count": contact_count,
        }

    def determine_start_step(self, prefs: UiStatePreferences) -> str:
        """Determine which step to start at based on durable state + progress preferences (§14.6)."""
        durable = self.check_durable_state()
        progress = prefs.first_flight_progress or {}

        if not durable["has_identity"]:
            return "identity"
        if not durable["has_agents"]:
            return "agent"
        if not progress.get("relay_checked", False):
            return "relay"
        if not durable["has_contacts"] and not progress.get("pairing_skipped", False):
            return "pairing"
        if not progress.get("demo_completed", False) and not progress.get("demo_skipped", False):
            return "demo"
        if not progress.get("guided_dispatch_shown", False):
            return "guided_dispatch"

        return "complete"

    def prepare_identity_creation(self) -> Tuple[str, List[int]]:
        """Generate a 12-word recovery phrase without persisting keys until confirmation (§14.6)."""
        phrase = generate_recovery_phrase()
        word_indices = sorted(random.sample(range(12), 2))
        return phrase, word_indices

    def confirm_identity_creation(
        self,
        username: str,
        phrase: str,
        word_indices: List[int],
        user_words: List[str],
    ) -> Optional[RecoverableError]:
        """Confirm phrase verification and commit identity to keychain & database (§14.6)."""
        if not verify_phrase_confirmation(phrase, word_indices, user_words):
            return RecoverableError(
                what_happened="Recovery phrase confirmation failed.",
                impact="Identity creation was safely interrupted.",
                preserved="No key material was stored in keychain.",
                next_action="Re-enter the correct words or press [Retry] to generate a new phrase.",
            )

        try:
            priv_bytes, pub_bytes = derive_key_pair(phrase)
            x_priv_bytes, x_pub_bytes = derive_x25519_key_pair(phrase)

            save_private_key(self.profile_name, priv_bytes)
            save_x25519_private_key(self.profile_name, x_priv_bytes)

            conn = self._ensure_db()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
                    (username, pub_bytes.hex(), f"kin-{self.profile_name}-private-key", V11_PROTOCOL_VERSION),
                )
                conn.commit()
            finally:
                conn.close()

            return None
        except Exception as exc:
            return RecoverableError(
                what_happened=f"Keychain error storing identity keys: {exc}",
                impact="Identity keys could not be persisted safely.",
                preserved="Profile directory remains unchanged.",
                next_action="Verify keyring service availability and press [Retry].",
            )

    def restore_identity_from_mnemonic(self, username: str, phrase: str) -> Optional[RecoverableError]:
        """Restore identity keypairs from an existing 12-word mnemonic (§14.6)."""
        try:
            words = phrase.strip().split()
            if len(words) != 12:
                return RecoverableError(
                    what_happened="Invalid mnemonic format: phrase must be exactly 12 words.",
                    impact="Restoration aborted.",
                    preserved="Existing key storage untouched.",
                    next_action="Re-enter a valid 12-word recovery phrase.",
                )

            priv_bytes, pub_bytes = derive_key_pair(phrase)
            x_priv_bytes, x_pub_bytes = derive_x25519_key_pair(phrase)

            save_private_key(self.profile_name, priv_bytes)
            save_x25519_private_key(self.profile_name, x_priv_bytes)

            conn = self._ensure_db()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
                    (username, pub_bytes.hex(), f"kin-{self.profile_name}-private-key", V11_PROTOCOL_VERSION),
                )
                conn.commit()
            finally:
                conn.close()

            return None
        except Exception as exc:
            return RecoverableError(
                what_happened=f"Identity restoration failed: {exc}",
                impact="Identity could not be restored.",
                preserved="Key storage remains unchanged.",
                next_action="Verify mnemonic accuracy and press [Retry].",
            )

    def connect_agent_card(self, card_path: Path) -> Optional[RecoverableError]:
        """Import an agent card YAML into the profile's local agent registry (§14.6)."""
        if not card_path.exists() or not card_path.is_file():
            return RecoverableError(
                what_happened=f"Agent card file not found at '{card_path}'.",
                impact="Agent connection aborted.",
                preserved="Agent registry remains intact.",
                next_action="Verify file path and press [Retry].",
            )

        try:
            agents_dir = self.profile_dir / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            dest_path = agents_dir / card_path.name
            if card_path.resolve() != dest_path.resolve():
                shutil.copy2(card_path, dest_path)

            load_card_file(dest_path, profile_name=self.profile_name)
            return None
        except Exception as exc:
            return RecoverableError(
                what_happened=f"Invalid agent card: {exc}",
                impact="Agent card could not be imported into registry.",
                preserved="Existing registered cards are untouched.",
                next_action="Fix YAML schema errors in agent card and press [Retry].",
            )

    def check_relay_reachability(self, client: Optional[httpx.Client] = None) -> Tuple[bool, Optional[RecoverableError]]:
        """Verify network reachability to configured relay URL (§14.6)."""
        from kin.tui.local_state import check_relay_reachability_status
        return check_relay_reachability_status(self.relay_url, client=client)

    def prepare_contact_pairing(
        self,
        contact_username: str,
        client: Optional[httpx.Client] = None,
    ) -> Tuple[Optional[Dict[str, str]], Optional[str], Optional[RecoverableError]]:
        """Look up a contact and compute the OOB fingerprint without recording trust."""
        lookup_url = f"{self.relay_url}/directory/lookup/{contact_username}"
        try:
            if client:
                resp = client.get(lookup_url)
            else:
                resp = httpx.get(lookup_url, timeout=3.0)

            if resp.status_code == 404:
                return None, None, RecoverableError(
                    what_happened=f"Contact '{contact_username}' not found in relay directory.",
                    impact="Pairing aborted.",
                    preserved="Contacts database untouched.",
                    next_action="Verify username spelling and press [Retry].",
                )
            resp.raise_for_status()
            data = resp.json()
            contact_pubkey_hex = data["public_key"]
            contact_x25519_hex = data["x25519_public_key"]
            contact_endpoint = data.get("endpoint", "http://127.0.0.1:8321")
        except Exception as exc:
            return None, None, RecoverableError(
                what_happened=f"Error connecting to relay directory: {exc}",
                impact="Could not retrieve contact public key.",
                preserved="Contacts database untouched.",
                next_action="Check relay connection and press [Retry].",
            )

        conn = self._ensure_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT public_key FROM identity LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return None, None, RecoverableError(
                    what_happened="No local identity initialized.",
                    impact="Cannot pair trusted contact without local identity.",
                    preserved="Contacts database untouched.",
                    next_action="Complete Identity step first.",
                )

            our_pub_hex = row[0]
            our_pub_bytes = bytes.fromhex(our_pub_hex)
            contact_pub_bytes = bytes.fromhex(contact_pubkey_hex)

            fingerprint = compute_fingerprint(our_pub_bytes, contact_pub_bytes)
            return {
                "username": contact_username,
                "public_key": contact_pubkey_hex,
                "x25519_public_key": contact_x25519_hex,
                "endpoint": contact_endpoint,
            }, fingerprint, None
        except Exception as exc:
            return None, None, RecoverableError(
                what_happened=f"Failed pairing contact '{contact_username}': {exc}",
                impact="Contact was not added to trusted database.",
                preserved="Existing contacts remain untouched.",
                next_action="Verify key format and press [Retry].",
            )
        finally:
            conn.close()

    def confirm_contact_pairing(
        self,
        prepared: Dict[str, str],
        expected_fingerprint: str,
        verified_fingerprint: str,
    ) -> Optional[RecoverableError]:
        """Record trust only after the complete out-of-band fingerprint matches."""
        normalize = lambda value: " ".join(value.strip().lower().split())
        if normalize(verified_fingerprint) != normalize(expected_fingerprint):
            return RecoverableError(
                what_happened="Fingerprint verification did not match.",
                impact="The contact was not trusted or added.",
                preserved="Existing identity and contacts remain unchanged.",
                next_action="Compare the complete fingerprint again over a separate trusted channel.",
            )
        try:
            conn = self._ensure_db()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO contacts
                       (username, display_name, public_key, x25519_public_key, endpoint,
                        autonomy_level, fingerprint_verified_at)
                       VALUES (?, ?, ?, ?, ?, 'always_ask', ?)""",
                    (
                        prepared["username"],
                        prepared["username"],
                        prepared["public_key"],
                        prepared["x25519_public_key"],
                        prepared["endpoint"],
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            return None
        except Exception as exc:
            return RecoverableError(
                what_happened=f"Failed pairing contact '{prepared.get('username', '')}': {exc}",
                impact="The contact was not added to the trusted database.",
                preserved="Existing contacts remain untouched.",
                next_action="Retry fingerprint verification.",
            )

    def pair_trusted_contact(
        self,
        contact_username: str,
        verified_fingerprint: str,
        client: Optional[httpx.Client] = None,
    ) -> Tuple[Optional[str], Optional[RecoverableError]]:
        """Pair through the preparation seam while requiring explicit fingerprint proof."""
        prepared, fingerprint, error = self.prepare_contact_pairing(contact_username, client=client)
        if error or prepared is None or fingerprint is None:
            return fingerprint, error
        return fingerprint, self.confirm_contact_pairing(prepared, fingerprint, verified_fingerprint)

    def mark_progress(self, key: str, value: Any = True) -> UiStatePreferences:
        """Persist non-durable progress flag to ui-state.json without leaking secrets (§14.6)."""
        prefs, _ = load_ui_preferences(self.profile_name)
        if not prefs.first_flight_progress:
            prefs.first_flight_progress = {}
        prefs.first_flight_progress[key] = value
        save_ui_preferences(prefs, self.profile_name)
        return prefs
