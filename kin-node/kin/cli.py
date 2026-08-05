"""KIN CLI — Typer entry point with profile support."""

import random
import os
import json
import re
import shutil
import sqlite3
import subprocess
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone
import typer
import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from kin.identity.storage import (
    load_private_key,
    save_llm_api_key,
    save_private_key,
    save_x25519_private_key,
    load_x25519_private_key,
)
from kin.identity.setup import setup_new_identity, verify_phrase_confirmation
from kin.identity.keys import derive_key_pair, derive_x25519_key_pair
from kin.identity.fingerprint import compute_fingerprint
from kin.storage.db import get_connection, create_schema, get_setting, set_setting

DEFAULT_RELAY_URL = "http://localhost:8000"
DEFAULT_ENDPOINT = "http://127.0.0.1:8321"
PROTOCOL_VERSION = "0.1.0"

app = typer.Typer(
    name="kin",
    help="KIN — Personal Agent Network",
    no_args_is_help=True,
)


def open_profile_db(db_path: Path | str) -> sqlite3.Connection:
    """Open profile database connection and ensure schema is current.

    Catches LegacyProfileMigrationRequired cleanly and exits without a traceback.
    """
    from kin.storage.migrations import LegacyProfileMigrationRequired
    conn = get_connection(db_path)
    try:
        create_schema(conn)
        return conn
    except LegacyProfileMigrationRequired as exc:
        conn.close()
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1)


def get_profile_dir(profile_name: str) -> Path:
    """Get the isolated data directory for the given profile."""
    # Place it in user's home directory under .kin/profiles/<name>
    base_dir = Path.home() / ".kin" / "profiles" / profile_name
    return base_dir


def get_relay_url() -> str:
    """Return the configured relay URL, normalized for safe URL composition."""
    return os.environ.get("KIN_RELAY_URL", DEFAULT_RELAY_URL).rstrip("/")


def register_identity_endpoint(conn, profile_name: str, endpoint: str) -> None:
    """Publish the active endpoint without ever changing identity keys."""
    row = conn.execute("SELECT username, public_key FROM identity LIMIT 1").fetchone()
    if row is None:
        raise typer.BadParameter("Identity is not initialized. Run 'kin pair' first.")
    username, public_key = row
    x_private = load_x25519_private_key(profile_name)
    from cryptography.hazmat.primitives.asymmetric import x25519

    x_public = x25519.X25519PrivateKey.from_private_bytes(x_private).public_key().public_bytes_raw().hex()
    response = httpx.post(
        f"{get_relay_url()}/directory/register",
        json={"username": username, "public_key": public_key, "x25519_public_key": x_public, "endpoint": endpoint},
        timeout=15,
    )
    response.raise_for_status()
    set_setting(conn, "public_endpoint", endpoint.rstrip("/"))


def refresh_contact_endpoint(conn, username: str) -> tuple[str, str, str]:
    """Refresh a trusted contact's reachability data while pinning its identity key."""
    local = conn.execute(
        "SELECT public_key, x25519_public_key FROM contacts WHERE username = ? AND fingerprint_verified_at IS NOT NULL",
        (username,),
    ).fetchone()
    if local is None:
        raise typer.BadParameter(f"Contact '{username}' is not verified. Run 'kin pair {username}' first.")
    response = httpx.get(f"{get_relay_url()}/directory/lookup/{username}", timeout=2)
    if response.status_code == 404:
        raise typer.BadParameter(f"Contact '{username}' no longer exists in the directory.")
    response.raise_for_status()
    remote = response.json()
    if remote["public_key"] != local[0] or remote["x25519_public_key"] != local[1]:
        raise typer.BadParameter(
            f"Security alert: '{username}' now presents a different identity key. Pair again only after out-of-band verification."
        )
    endpoint = remote["endpoint"].rstrip("/")
    conn.execute("UPDATE contacts SET endpoint = ? WHERE username = ?", (endpoint, username))
    conn.commit()
    return endpoint, local[0], local[1]


def mark_relay_message_processed(conn, message_id: int | None) -> None:
    """Make relay processing idempotent before acknowledging a message remotely."""
    if message_id is None:
        return
    conn.execute(
        "INSERT OR IGNORE INTO processed_relay_messages (message_id, processed_at) VALUES (?, ?)",
        (message_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


@app.callback()
def main(
    ctx: typer.Context,
    profile: str = typer.Option(
        "default",
        "--profile",
        "-p",
        help="Profile name to use for isolating data directories.",
    ),
) -> None:
    """KIN CLI entry point with profile isolation."""
    if os.environ.get("KIN_UNSAFE_TEST_KEYRING") == "1":
        import sys
        import keyring
        from kin.testing.insecure_memory_keyring import InMemoryTestKeyring

        keyring.set_keyring(InMemoryTestKeyring())
        sys.stderr.write(
            "WARNING: KIN_UNSAFE_TEST_KEYRING=1 — using an insecure in-memory keyring. Test use only.\n"
        )

    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise typer.BadParameter("Profile names may contain only letters, numbers, hyphens, and underscores.")
    profile_dir = get_profile_dir(profile)
    # Store profile name and path in the context object for command use
    ctx.obj = {
        "profile_name": profile,
        "profile_dir": profile_dir,
    }


@app.command()
def pair(
    ctx: typer.Context,
    code: Optional[str] = typer.Argument(
        default=None,
        help="Target contact username to pair with. Omit to initialize your own identity.",
    ),
) -> None:
    """Pair with another KIN instance or initialize your identity.

    If username is provided, looks up that contact on the relay.
    If username is omitted, runs the first-time setup flow (generates phrase,
    confirms it, and registers your public key with the relay directory).
    """
    profile_name = ctx.obj["profile_name"]
    profile_dir = ctx.obj["profile_dir"]

    # Ensure profile directory exists
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    relay_url = get_relay_url()

    if code is not None:
        # ----------------------------------------------------
        # 'kin pair <username>' flow: lookup, fingerprint, save contact
        # ----------------------------------------------------
        contact_username = code

        # Check database first to see if contact is already verified
        conn = open_profile_db(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT fingerprint_verified_at FROM contacts WHERE username = ?",
                (contact_username,),
            )
            row = cursor.fetchone()
            if row is not None and row[0] is not None:
                typer.echo(f"Already verified as a trusted contact: '{contact_username}' — no action needed.")
                return
        finally:
            conn.close()

        lookup_url = f"{relay_url}/directory/lookup/{contact_username}"
        try:
            r = httpx.get(lookup_url)
            if r.status_code == 404:
                typer.echo(f"Error: Contact '{contact_username}' not found in the relay directory.", err=True)
                raise typer.Exit(code=1)
            r.raise_for_status()
            data = r.json()
            contact_pubkey_hex = data["public_key"]
            contact_x25519_pub_hex = data["x25519_public_key"]
            contact_endpoint = data["endpoint"]
        except httpx.HTTPError as e:
            typer.echo(f"Error connecting to relay: {e}", err=True)
            raise typer.Exit(code=1)

        # Connect to DB to load local identity
        conn = open_profile_db(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT username, public_key FROM identity")
            row = cursor.fetchone()
            if row is None:
                typer.echo(
                    "Error: You must initialize your identity (run 'kin pair' without arguments) "
                    "before pairing with other contacts.",
                    err=True,
                )
                raise typer.Exit(code=1)
            
            our_pubkey_hex = row[1]
            
            # Compute fingerprint
            our_pubkey_bytes = bytes.fromhex(our_pubkey_hex)
            contact_pubkey_bytes = bytes.fromhex(contact_pubkey_hex)
            fingerprint = compute_fingerprint(our_pubkey_bytes, contact_pubkey_bytes)
            
            typer.echo(f"Contact '{contact_username}' found!")
            typer.echo(f"  Public Key: {contact_pubkey_hex}")
            typer.echo(f"  Endpoint: {contact_endpoint}")
            typer.echo(f"  Computed Fingerprint: {fingerprint}")
            typer.echo("=====================================================================")
            
            # Prompt user to verify the fingerprint
            matches = typer.confirm(
                "Confirm with the other person out of band that they see the same fingerprint. Does it match?"
            )
            
            if matches:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO contacts 
                    (username, display_name, public_key, x25519_public_key, endpoint, autonomy_level, fingerprint_verified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (contact_username, contact_username, contact_pubkey_hex, contact_x25519_pub_hex, contact_endpoint, "always_ask", now_str)
                )
                conn.commit()
                typer.echo(f"Success! Contact '{contact_username}' added and marked verified.")
            else:
                typer.echo("Pairing aborted for safety.")
                raise typer.Exit(code=0)
        finally:
            conn.close()
        return

    # ----------------------------------------------------
    # 'kin pair' (no-args) flow: first-time setup
    # ----------------------------------------------------
    conn = open_profile_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM identity")
        row = cursor.fetchone()
        if row is not None:
            typer.echo(f"Identity already initialized for username: '{row[0]}'")
            return

        # 1. Prompt for username FIRST to check availability
        username = typer.prompt("Choose your desired username")

        # 2. Check username availability with the relay
        lookup_url = f"{relay_url}/directory/lookup/{username}"
        try:
            r = httpx.get(lookup_url)
            if r.status_code == 200:
                typer.echo(
                    f"Error: Username '{username}' is already taken. Please try another username.",
                    err=True,
                )
                raise typer.Exit(code=1)
            elif r.status_code != 404:
                r.raise_for_status()
        except httpx.HTTPError as e:
            typer.echo(f"Error connecting to relay directory: {e}", err=True)
            raise typer.Exit(code=1)

        # 3. Proceed with phrase generation now that username is available
        phrase = setup_new_identity(profile_name)
        typer.echo("=====================================================================")
        typer.echo("Welcome to KIN! No identity was found for this profile. Generating one...")
        typer.echo("Here is your 12-word recovery phrase. Write it down and keep it safe!")
        typer.echo("It is the only way to recover your identity.")
        typer.echo("=====================================================================")
        typer.echo(f"\n{phrase}\n")
        typer.echo("=====================================================================")

        # Select 2 random indices to confirm
        word_indices = sorted(random.sample(range(12), 2))
        user_input = []
        for idx in word_indices:
            word = typer.prompt(f"Enter word #{idx + 1} of your recovery phrase")
            user_input.append(word)

        if not verify_phrase_confirmation(phrase, word_indices, user_input):
            typer.echo("Verification failed! Words do not match. Please try again.", err=True)
            raise typer.Exit(code=1)

        # Load private key from keychain and derive public key
        try:
            private_key = load_private_key(profile_name)
        except Exception as e:
            typer.echo(f"Error loading private key from keychain: {e}", err=True)
            raise typer.Exit(code=1)

        priv_obj = ed25519.Ed25519PrivateKey.from_private_bytes(private_key)
        public_key = priv_obj.public_key().public_bytes_raw()

        # Derive X25519 keypair and save to keychain
        try:
            x25519_priv, x25519_pub = derive_x25519_key_pair(phrase)
            save_x25519_private_key(profile_name, x25519_priv)
        except Exception as e:
            typer.echo(f"Error deriving/saving X25519 private key: {e}", err=True)
            raise typer.Exit(code=1)

        # Call register endpoint on the relay before committing to the DB
        register_url = f"{relay_url}/directory/register"
        payload = {
            "username": username,
            "public_key": public_key.hex(),
            "x25519_public_key": x25519_pub.hex(),
            "endpoint": os.environ.get("KIN_PUBLIC_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/"),
        }

        try:
            r = httpx.post(register_url, json=payload)
            if r.status_code == 409:
                typer.echo(f"Error: Username '{username}' is already registered to a different key.", err=True)
                raise typer.Exit(code=1)
            r.raise_for_status()
        except httpx.HTTPError as e:
            typer.echo(f"Error registering with relay directory: {e}", err=True)
            raise typer.Exit(code=1)

        # Commit to local database since registration succeeded
        cursor.execute(
            "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
            (username, public_key.hex(), f"kin-{profile_name}-private-key", "0.1.0"),
        )
        conn.commit()
        set_setting(conn, "public_endpoint", payload["endpoint"])
    finally:
        conn.close()

    typer.echo(f"Success! Identity initialized and registered as '{username}'.")


@app.command("init")
def initialize(ctx: typer.Context) -> None:
    """Create this profile's identity (an explicit alias for ``kin pair``)."""
    pair(ctx, None)


def select_agent(profile_name: str, agent_option: Optional[str] = None) -> Optional[str]:
    """Helper to load agent roster, apply selection rules, and return chosen agent name."""
    from kin.agent_roster.loader import load_agent_roster, AgentLoadingError
    try:
        roster = load_agent_roster(profile_name)
    except AgentLoadingError as e:
        typer.echo(f"Error loading agent roster: {e}", err=True)
        raise typer.Exit(code=1)

    if not roster:
        if agent_option is not None:
            typer.echo(f"Error: Agent '{agent_option}' requested, but no agents are configured.", err=True)
            raise typer.Exit(code=1)
        return None

    if agent_option is not None:
        if agent_option not in roster:
            available = ", ".join(sorted(roster.keys()))
            typer.echo(f"Error: Agent '{agent_option}' not found in roster. Available agents: {available}", err=True)
            raise typer.Exit(code=1)
        return agent_option

    if len(roster) == 1:
        return next(iter(roster.keys()))

    # Multiple agents: show interactive picker
    typer.echo("Select an agent:")
    agents_list = sorted(roster.keys())
    for idx, name in enumerate(agents_list):
        agent_cfg = roster[name]
        typer.echo(f"  [{idx + 1}] {name} ({agent_cfg.backend_type})")

    while True:
        choice = typer.prompt("Enter the number of your choice", type=str).strip()
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(agents_list):
                return agents_list[choice_idx]
        except ValueError:
            pass
        typer.echo("Invalid choice. Please enter a valid number.", err=True)


@app.command()
def ask(
    ctx: typer.Context,
    contact: str = typer.Argument(help="Contact username to ask"),
    question: str = typer.Argument(help="Question to ask"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Name of the agent to use"),
) -> None:
    """Ask another KIN agent a question."""
    profile_name = ctx.obj["profile_name"]
    profile_dir = ctx.obj["profile_dir"]

    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        typer.echo("Error: Local database not found. Please run 'kin pair' first.", err=True)
        raise typer.Exit(code=1)

    conn = open_profile_db(db_path)
    try:
        # 1. Check our own identity
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM identity")
        row = cursor.fetchone()
        if row is None:
            typer.echo(
                "Error: Identity is not initialized. Run 'kin pair' without arguments first.",
                err=True,
            )
            raise typer.Exit(code=1)
        own_username = row[0]

        # Select agent config based on user input / option
        selected_agent_name = select_agent(profile_name, agent)

        # 2. Check the contact
        cursor.execute(
            "SELECT endpoint, public_key, fingerprint_verified_at, x25519_public_key FROM contacts WHERE username = ?",
            (contact,),
        )
        row = cursor.fetchone()
        if row is None or row[2] is None:
            typer.echo(
                f"Error: Contact '{contact}' is not verified or does not exist. "
                f"Please pair and verify fingerprint first.",
                err=True,
            )
            raise typer.Exit(code=1)
        endpoint, _, _, contact_x25519_pub_hex = row
        # Quick Cloudflare tunnel URLs change between sessions. Refresh those addresses
        # before delivery while pinning the fingerprint-verified identity keys. Stable
        # endpoints avoid an unnecessary directory round trip on every ask.
        if ".trycloudflare.com" in endpoint or os.environ.get("KIN_REFRESH_DIRECTORY") == "1":
            try:
                endpoint, _, contact_x25519_pub_hex = refresh_contact_endpoint(conn, contact)
            except (httpx.HTTPError, typer.BadParameter):
                # The stored endpoint remains a valid last-known address; relay fallback
                # protects delivery if the recipient is currently unreachable.
                pass

        # 3. Load private key to sign the task request
        try:
            private_key = load_private_key(profile_name)
        except Exception as e:
            typer.echo(f"Error loading private key from keychain: {e}", err=True)
            raise typer.Exit(code=1)

        # 4. Form payload and serialize *exactly once*
        payload = {
            "goal": question,
            "context": {},
            "requester_username": own_username,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        # 5. Sign the payload bytes
        from kin.identity.keys import sign_message
        try:
            sig = sign_message(private_key, payload_bytes)
            x_signature = sig.hex()
        except Exception as e:
            typer.echo(f"Error signing request payload: {e}", err=True)
            raise typer.Exit(code=1)

        # 6. Post to the contact's endpoint
        endpoint = endpoint.rstrip("/")
        url = f"{endpoint}/tasks"
        import uuid
        local_task_id = f"local-queued-{uuid.uuid4()}"
        try:
            r = httpx.post(
                url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": x_signature,
                },
                timeout=30.0,
            )
            r.raise_for_status()
            res = r.json()
            task_id = res["task_id"]
            status = res["status"]
            
            # Save task locally to track agent assignment
            now_str = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO tasks (task_id, contact_username, goal, context_json, status, created_at, updated_at, agent_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, contact, question, "{}", status, now_str, now_str, selected_agent_name),
            )
            conn.commit()

            typer.echo(f"Task created successfully! ID: {task_id}, Status: {status}")
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            typer.echo(f"Error from receiving node: {detail}", err=True)
            raise typer.Exit(code=1)
        except httpx.RequestError as direct_conn_err:
            typer.echo(f"Direct connection to {contact} failed. Falling back to relay mailbox...")
            
            from kin.identity.storage import load_x25519_private_key
            try:
                own_x25519_priv = load_x25519_private_key(profile_name)
            except Exception as e:
                typer.echo(f"Error loading own X25519 private key from keychain: {e}", err=True)
                raise typer.Exit(code=1)

            if not contact_x25519_pub_hex:
                typer.echo(f"Error: Contact '{contact}' has no registered X25519 public key. Cannot encrypt.", err=True)
                raise typer.Exit(code=1)

            contact_x25519_pub = bytes.fromhex(contact_x25519_pub_hex)

            # Construct routing envelope
            envelope = {
                "type": "create_task",
                "payload_bytes": payload_bytes.hex(),
                "signature": x_signature,
                "local_ref_id": local_task_id,
            }
            envelope_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")

            # Encrypt for recipient
            from kin.identity.keys import encrypt_for_recipient
            try:
                ciphertext = encrypt_for_recipient(own_x25519_priv, contact_x25519_pub, envelope_bytes)
            except Exception as e:
                typer.echo(f"Error encrypting message: {e}", err=True)
                raise typer.Exit(code=1)

            # POST to relay
            relay_url = get_relay_url()
            relay_mailbox_url = f"{relay_url}/relay/mailbox/{contact}"
            relay_payload = {
                "sender_username": own_username,
                "encrypted_blob": ciphertext.hex(),
            }

            try:
                r_relay = httpx.post(relay_mailbox_url, json=relay_payload)
                r_relay.raise_for_status()
                
                # Print distinct confirmation message
                typer.echo("Task queued at relay, contact is offline.")

                # Insert tracking under the exact identifier carried in the relay envelope.
                # This makes the recipient's first reply safely reconcile to this row.
                now_str = datetime.now(timezone.utc).isoformat()
                
                cursor.execute(
                    """
                    INSERT INTO tasks (task_id, contact_username, goal, context_json, status, created_at, updated_at, result_json, draft_content, draft_message_type, agent_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (local_task_id, contact, question, "{}", "queued-relay", now_str, now_str, None, None, None, selected_agent_name),
                )
                conn.commit()
            except Exception as relay_err:
                typer.echo(f"Connection to peer failed: {direct_conn_err}", err=True)
                typer.echo(f"Fallback connection to relay failed: {relay_err}", err=True)
                raise typer.Exit(code=1)
        except httpx.HTTPError as e:
            typer.echo(f"Error connecting to contact endpoint: {e}", err=True)
            raise typer.Exit(code=1)
    finally:
        conn.close()


@app.command()
def respond(
    ctx: typer.Context,
    task_id: str = typer.Argument(help="Task ID to respond to"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Name of the agent to use"),
) -> None:
    """Respond to a task proposal with the drafted response."""
    profile_name = ctx.obj["profile_name"]
    profile_dir = ctx.obj["profile_dir"]

    # Ensure profile directory exists
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    conn = open_profile_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, draft_content, draft_message_type, contact_username, peer_task_id, origin_ref_id FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        if row is None:
            typer.echo(f"Error: Task with ID '{task_id}' not found.", err=True)
            raise typer.Exit(code=1)
        status, draft_content, draft_message_type, contact_username, peer_task_id, origin_ref_id = row

        # Select agent config based on user input / option
        selected_agent_name = select_agent(profile_name, agent)

        if status != "input-required" or draft_content is None:
            typer.echo(f"No draft reply pending for task '{task_id}'.", err=True)
            raise typer.Exit(code=1)

        # Load contact details
        cursor.execute(
            "SELECT endpoint, public_key, x25519_public_key FROM contacts WHERE username = ?",
            (contact_username,),
        )
        contact_row = cursor.fetchone()
        if contact_row is None:
            typer.echo(f"Error: Contact '{contact_username}' not found.", err=True)
            raise typer.Exit(code=1)
        endpoint, contact_pubkey, contact_x25519_pub_hex = contact_row

        # Load our own identity and private key
        cursor.execute("SELECT username FROM identity")
        row_identity = cursor.fetchone()
        if row_identity is None:
            typer.echo("Error: Local identity not initialized.", err=True)
            raise typer.Exit(code=1)
        own_username = row_identity[0]

        try:
            private_key = load_private_key(profile_name)
        except Exception as e:
            typer.echo(f"Error loading private key: {e}", err=True)
            raise typer.Exit(code=1)

        # Branch based on draft_message_type
        if draft_message_type == "finalize_proposal":
            typer.echo(f"The other side proposes finalizing with: {draft_content}")
            typer.echo("=====================================================================")
            action = typer.prompt(
                "Accept this as final [a], or reject and explain why [r]?",
                default="a"
            ).lower().strip()

            if action not in ("a", "r"):
                typer.echo("Error: Invalid action. Choose 'a' or 'r'.", err=True)
                raise typer.Exit(code=1)

            if action == "a":
                outgoing_msg_type = "finalize_accept"
                content = draft_content
            else:
                outgoing_msg_type = "counter_proposal"
                reason = typer.prompt("What's missing, or why doesn't this work for you?")
                if not reason.strip():
                    typer.echo("Error: Explanation cannot be empty.", err=True)
                    raise typer.Exit(code=1)
                content = reason
        else:
            typer.echo(f"Draft message type: {draft_message_type}")
            typer.echo(f"Draft content: {draft_content}")
            typer.echo("=====================================================================")

            # Prompt options: Send as-is [y], edit before sending [e], cancel [c], or finalize [f]?
            action = typer.prompt(
                "Send as-is [y], edit before sending [e], cancel [c], or finalize [f]?",
                default="y"
            ).lower().strip()

            if action not in ("y", "e", "c", "f"):
                typer.echo("Error: Invalid action. Choose 'y', 'e', 'c', or 'f'.", err=True)
                raise typer.Exit(code=1)

            if action == "c":
                typer.echo("Cancelled.")
                raise typer.Exit(code=0)

            if action == "y":
                outgoing_msg_type = draft_message_type
                content = draft_content
            elif action == "e":
                outgoing_msg_type = draft_message_type
                content = typer.prompt("Enter your edited response")
                if not content.strip():
                    typer.echo("Error: Message content cannot be empty.", err=True)
                    raise typer.Exit(code=1)
            else:  # action == "f" (finalize)
                outgoing_msg_type = "finalize_proposal"
                content = draft_content

        # Construct payload and serialize once
        import uuid
        payload = {
            "from_username": own_username,
            "content": content,
            "message_type": outgoing_msg_type,
        }
        if origin_ref_id:
            payload["origin_ref_id"] = origin_ref_id
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        # Sign payload bytes
        from kin.identity.keys import sign_message
        try:
            sig = sign_message(private_key, payload_bytes)
            x_signature = sig.hex()
        except Exception as e:
            typer.echo(f"Error signing payload: {e}", err=True)
            raise typer.Exit(code=1)

        # Defensive target ID selection: use peer_task_id if known, else task_id
        target_peer_id = peer_task_id if peer_task_id else task_id

        # Send payload to contact's endpoint
        endpoint = endpoint.rstrip("/")
        url = f"{endpoint}/tasks/{target_peer_id}/messages"
        try:
            r = httpx.post(
                url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": x_signature,
                },
            )
            r.raise_for_status()
            res = r.json()
            returned_status = res["status"]
            typer.echo(f"Response from peer node: Status = {returned_status}")

            now_str = datetime.now(timezone.utc).isoformat()
            new_msg_id = str(uuid.uuid4())

            # Insert message locally
            cursor.execute(
                """
                INSERT INTO messages (message_id, task_id, from_username, content, message_type, created_at, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_msg_id, task_id, own_username, content, outgoing_msg_type, now_str, x_signature),
            )

            # Update task status and clear draft fields.
            # If outgoing message is finalize_accept, set local task to completed as well.
            if outgoing_msg_type == "finalize_accept":
                cursor.execute(
                    """
                    UPDATE tasks
                    SET status = ?, draft_content = NULL, draft_message_type = NULL, result_json = ?, updated_at = ?, agent_name = ?
                    WHERE task_id = ?
                    """,
                    ("completed", json.dumps({"outcome": content, "finalized_by": own_username}), now_str, selected_agent_name, task_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE tasks
                    SET status = ?, draft_content = NULL, draft_message_type = NULL, updated_at = ?, agent_name = ?
                    WHERE task_id = ?
                    """,
                    (returned_status, now_str, selected_agent_name, task_id),
                )
            conn.commit()
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            typer.echo(f"Error from peer node: {detail}", err=True)
            raise typer.Exit(code=1)
        except httpx.RequestError as direct_conn_err:
            typer.echo(f"Direct connection to {contact_username} failed. Falling back to relay mailbox...")
            
            from kin.identity.storage import load_x25519_private_key
            try:
                own_x25519_priv = load_x25519_private_key(profile_name)
            except Exception as e:
                typer.echo(f"Error loading own X25519 private key from keychain: {e}", err=True)
                raise typer.Exit(code=1)

            if not contact_x25519_pub_hex:
                typer.echo(f"Error: Contact '{contact_username}' has no registered X25519 public key. Cannot encrypt.", err=True)
                raise typer.Exit(code=1)

            contact_x25519_pub = bytes.fromhex(contact_x25519_pub_hex)

            # Construct routing envelope
            envelope = {
                "type": "send_message",
                "task_id": target_peer_id,
                "payload_bytes": payload_bytes.hex(),
                "signature": x_signature,
            }
            envelope_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")

            # Encrypt for recipient
            from kin.identity.keys import encrypt_for_recipient
            try:
                ciphertext = encrypt_for_recipient(own_x25519_priv, contact_x25519_pub, envelope_bytes)
            except Exception as e:
                typer.echo(f"Error encrypting message: {e}", err=True)
                raise typer.Exit(code=1)

            # POST to relay
            relay_url = os.environ.get("KIN_RELAY_URL", "http://localhost:8000").rstrip("/")
            relay_mailbox_url = f"{relay_url}/relay/mailbox/{contact_username}"
            relay_payload = {
                "sender_username": own_username,
                "encrypted_blob": ciphertext.hex(),
            }

            try:
                r_relay = httpx.post(relay_mailbox_url, json=relay_payload)
                r_relay.raise_for_status()

                # Print human message
                if outgoing_msg_type == "finalize_accept":
                    typer.echo(f"Response queued — will be delivered when {contact_username} comes online. This has NOT yet been confirmed as final by them.")
                else:
                    typer.echo("Response queued at relay.")

                now_str = datetime.now(timezone.utc).isoformat()
                new_msg_id = str(uuid.uuid4())

                # Insert message locally
                cursor.execute(
                    """
                    INSERT INTO messages (message_id, task_id, from_username, content, message_type, created_at, signature)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (new_msg_id, task_id, own_username, content, outgoing_msg_type, now_str, x_signature),
                )

                # Update task status to "queued-relay" and clear draft fields (for all message types, including finalize_accept)
                cursor.execute(
                    """
                    UPDATE tasks
                    SET status = ?, draft_content = NULL, draft_message_type = NULL, updated_at = ?, agent_name = ?
                    WHERE task_id = ?
                    """,
                    ("queued-relay", now_str, selected_agent_name, task_id),
                )
                conn.commit()
            except Exception as relay_err:
                typer.echo(f"Connection to peer failed: {direct_conn_err}", err=True)
                typer.echo(f"Fallback connection to relay failed: {relay_err}", err=True)
                raise typer.Exit(code=1)
        except httpx.HTTPError as e:
            typer.echo(f"Error connecting to contact endpoint: {e}", err=True)
            raise typer.Exit(code=1)
    finally:
        conn.close()
@app.command()
def fetch(ctx: typer.Context) -> None:
    """Fetch waiting messages from the relay mailbox and process them."""
    profile_name = ctx.obj["profile_name"]
    profile_dir = ctx.obj["profile_dir"]

    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "kin.db"

    conn = open_profile_db(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username, public_key FROM identity")
        row = cursor.fetchone()
        if row is None:
            typer.echo("Error: Identity not initialized. Run 'kin pair' first.", err=True)
            raise typer.Exit(code=1)
        own_username, own_pubkey_hex = row

        try:
            own_priv = load_private_key(profile_name)
            own_x25519_priv = load_x25519_private_key(profile_name)
        except Exception as e:
            typer.echo(f"Error loading private keys from keychain: {e}", err=True)
            raise typer.Exit(code=1)

        relay_url = os.environ.get("KIN_RELAY_URL", "http://localhost:8000").rstrip("/")
        inbox_url = f"{relay_url}/relay/inbox"
        
        ts = datetime.now(timezone.utc).isoformat()
        msg_bytes = f"{own_username}:{ts}".encode("utf-8")
        from kin.identity.keys import sign_message
        sig = sign_message(own_priv, msg_bytes).hex()

        try:
            r = httpx.get(
                inbox_url,
                headers={
                    "X-Username": own_username,
                    "X-Timestamp": ts,
                    "X-Signature": sig,
                }
            )
            r.raise_for_status()
            res = r.json()
            messages = res.get("messages", [])
        except httpx.HTTPError as e:
            typer.echo(f"Error connecting to relay: {e}", err=True)
            raise typer.Exit(code=1)

        if not messages:
            typer.echo("Inbox is empty.")
            return

        typer.echo(f"Fetched {len(messages)} message(s) from relay.")

        import asyncio
        from kin.identity.keys import decrypt_from_sender
        from kin.node.routes import process_create_task, process_send_message
        from kin.node.models import CreateTaskRequest, SendMessageRequest
        import json

        for idx, item in enumerate(messages):
            relay_message_id = item.get("message_id")
            if relay_message_id is not None:
                already_processed = cursor.execute(
                    "SELECT 1 FROM processed_relay_messages WHERE message_id = ?", (relay_message_id,)
                ).fetchone()
                if already_processed:
                    typer.echo(f"Message {idx + 1}/{len(messages)} was already processed; acknowledging it.")
                    continue
            sender = item["sender_username"]
            blob_hex = item["encrypted_blob"]

            typer.echo(f"Processing message {idx + 1}/{len(messages)} from '{sender}'...")

            cursor.execute(
                "SELECT x25519_public_key, fingerprint_verified_at FROM contacts WHERE username = ?",
                (sender,),
            )
            contact_row = cursor.fetchone()
            if contact_row is None or contact_row[1] is None:
                typer.echo(f"Warning: Sender '{sender}' is not a verified contact. Skipping message.", err=True)
                mark_relay_message_processed(conn, relay_message_id)
                continue

            contact_x25519_pub_hex = contact_row[0]
            if not contact_x25519_pub_hex:
                typer.echo(f"Warning: Contact '{sender}' has no registered X25519 public key. Skipping message.", err=True)
                mark_relay_message_processed(conn, relay_message_id)
                continue

            contact_x25519_pub = bytes.fromhex(contact_x25519_pub_hex)

            try:
                ciphertext = bytes.fromhex(blob_hex)
                decrypted_bytes = decrypt_from_sender(own_x25519_priv, contact_x25519_pub, ciphertext)
                envelope = json.loads(decrypted_bytes.decode("utf-8"))
            except Exception as e:
                typer.echo(f"Warning: Decryption failed for message from '{sender}': {e}. Skipping message.", err=True)
                mark_relay_message_processed(conn, relay_message_id)
                continue

            env_type = envelope.get("type")
            env_sig = envelope.get("signature")
            env_payload_hex = envelope.get("payload_bytes")

            if not env_type or not env_sig or not env_payload_hex:
                typer.echo(f"Warning: Malformed envelope received from '{sender}'. Skipping message.", err=True)
                mark_relay_message_processed(conn, relay_message_id)
                continue

            try:
                raw_payload = bytes.fromhex(env_payload_hex)
                payload = json.loads(raw_payload.decode("utf-8"))
            except Exception as e:
                typer.echo(f"Warning: Malformed payload in envelope from '{sender}': {e}. Skipping message.", err=True)
                mark_relay_message_processed(conn, relay_message_id)
                continue

            if env_type == "create_task":
                try:
                    req_body = CreateTaskRequest(**payload)
                    env_local_ref_id = envelope.get("local_ref_id")
                    status_code, response_body = asyncio.run(process_create_task(
                        req_body, raw_payload, env_sig, conn, profile_name, local_ref_id=env_local_ref_id
                    ))
                    if status_code == 200:
                        typer.echo(f"Successfully processed new task. ID: {response_body['task_id']}, Status: {response_body['status']}")
                        mark_relay_message_processed(conn, relay_message_id)
                    else:
                        typer.echo(f"Warning: Failed to process task creation from '{sender}': {response_body.get('detail', 'Unknown error')}", err=True)
                except Exception as e:
                    typer.echo(f"Warning: Error processing task from '{sender}': {e}. Skipping.", err=True)
                    continue

            elif env_type == "send_message":
                env_task_id = envelope.get("task_id")
                if not env_task_id:
                    typer.echo(f"Warning: Missing task_id in message envelope from '{sender}'. Skipping.", err=True)
                    continue

                try:
                    req_body = SendMessageRequest(**payload)
                    status_code, response_body = asyncio.run(process_send_message(
                        env_task_id, req_body, raw_payload, env_sig, conn, profile_name
                    ))
                    if status_code == 200:
                        typer.echo(f"Successfully processed message for task '{env_task_id}'. Status: {response_body['status']}")
                        mark_relay_message_processed(conn, relay_message_id)
                    elif status_code == 404:
                        typer.echo(
                            f"Warning: Received a reply for an unrecognized task '{env_task_id}' — "
                            f"likely a local-queued task that hasn't been reconciled; message not processed.",
                            err=True,
                        )
                    else:
                        typer.echo(f"Warning: Failed to process message from '{sender}': {response_body.get('detail', 'Unknown error')}", err=True)
                except Exception as e:
                    typer.echo(f"Warning: Error processing message from '{sender}': {e}. Skipping.", err=True)
                    continue
            else:
                typer.echo(f"Warning: Unknown envelope type '{env_type}' from '{sender}'. Skipping.", err=True)
                mark_relay_message_processed(conn, relay_message_id)
                continue

        acknowledged = [
            row[0] for row in cursor.execute("SELECT message_id FROM processed_relay_messages").fetchall()
        ]
        received_ids = {item.get("message_id") for item in messages if item.get("message_id") is not None}
        acknowledged = [message_id for message_id in acknowledged if message_id in received_ids]
        if acknowledged:
            try:
                ack_timestamp = datetime.now(timezone.utc).isoformat()
                ack_body = json.dumps({"message_ids": acknowledged}, separators=(",", ":"))
                ack_signature = sign_message(
                    own_priv, f"{own_username}:{ack_timestamp}:{ack_body}".encode("utf-8")
                ).hex()
                ack_response = httpx.post(
                    f"{relay_url}/relay/inbox/ack",
                    content=ack_body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Username": own_username,
                        "X-Timestamp": ack_timestamp,
                        "X-Signature": ack_signature,
                    },
                    timeout=15,
                )
                ack_response.raise_for_status()
            except httpx.HTTPError as exc:
                typer.echo(f"Warning: Messages were processed but could not be acknowledged yet: {exc}", err=True)

    finally:
        conn.close()


@app.command()
def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", help="Host to bind the server to."),
    port: int = typer.Option(8321, help="Port to bind the server to."),
    public_endpoint: Optional[str] = typer.Option(None, "--public-endpoint", help="Public HTTPS endpoint to publish in the directory."),
    tunnel: bool = typer.Option(False, "--tunnel", help="Create a Cloudflare quick tunnel and publish its HTTPS URL."),
    fetch_on_start: bool = typer.Option(True, "--fetch/--no-fetch", help="Fetch pending relay messages before serving."),
) -> None:
    """Start the KIN node server for the active profile."""
    profile_name = ctx.obj["profile_name"]
    profile_dir = ctx.obj["profile_dir"]
    db_path = profile_dir / "kin.db"

    # Ensure the profile directory exists and schema is initialized
    profile_dir.mkdir(parents=True, exist_ok=True)
    conn = open_profile_db(db_path)
    tunnel_process = None
    try:
        if tunnel and public_endpoint:
            raise typer.BadParameter("Use either --tunnel or --public-endpoint, not both.")
        if tunnel:
            cloudflared = shutil.which("cloudflared")
            if cloudflared is None:
                raise typer.BadParameter(
                    "cloudflared is required for --tunnel. Install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ and retry."
                )
            tunnel_process = subprocess.Popen(
                [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
            public_endpoint = None
            for _ in range(60):
                line = tunnel_process.stdout.readline() if tunnel_process.stdout else ""
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line, flags=re.IGNORECASE)
                if match:
                    public_endpoint = match.group(0)
                    break
                if tunnel_process.poll() is not None:
                    break
            if public_endpoint is None:
                raise typer.BadParameter("Cloudflare Tunnel did not provide a public URL. Check cloudflared output and retry.")

        if public_endpoint:
            register_identity_endpoint(conn, profile_name, public_endpoint)
            typer.echo(f"Published endpoint: {public_endpoint}")
        elif get_setting(conn, "public_endpoint") is None:
            set_setting(conn, "public_endpoint", f"http://{host}:{port}")
    except Exception:
        if tunnel_process is not None:
            tunnel_process.terminate()
        conn.close()
        raise
    conn.close()

    import uvicorn
    from kin.node.app import app as fastapi_app

    # Set app state for the active profile
    fastapi_app.state.profile_name = profile_name
    fastapi_app.state.db_path = db_path

    if fetch_on_start:
        try:
            fetch(ctx)
        except typer.Exit as exc:
            typer.echo(f"Relay inbox check skipped ({exc.exit_code}). The node will still start.", err=True)

    typer.echo(f"Starting KIN node server for profile '{profile_name}' on {host}:{port}...")
    try:
        uvicorn.run(fastapi_app, host=host, port=port)
    finally:
        if tunnel_process is not None:
            tunnel_process.terminate()


@app.command()
def contacts(ctx: typer.Context) -> None:
    """List paired contacts."""
    profile_dir = ctx.obj["profile_dir"]
    db_path = profile_dir / "kin.db"
    if not db_path.exists():
        typer.echo("No identity or contacts yet. Run 'kin pair' first.")
        return
    conn = open_profile_db(db_path)
    try:
        rows = conn.execute(
            "SELECT username, display_name, endpoint, autonomy_level, fingerprint_verified_at FROM contacts ORDER BY username"
        ).fetchall()
        if not rows:
            typer.echo("No paired contacts. Use 'kin pair <username>' to add one.")
            return
        typer.echo("CONTACTS")
        for username, display_name, endpoint, autonomy, verified_at in rows:
            trust = "verified" if verified_at else "unverified"
            typer.echo(f"{username} ({display_name})  {trust}  policy={autonomy}\n  {endpoint}")
    finally:
        conn.close()


@app.command("contact-policy")
def contact_policy(
    ctx: typer.Context,
    username: str = typer.Argument(help="Paired contact username"),
    policy: str = typer.Argument(help="always_ask or auto_relay_info"),
) -> None:
    """Set the human-approval policy for a paired contact."""
    if policy not in {"always_ask", "auto_relay_info"}:
        raise typer.BadParameter("Policy must be 'always_ask' or 'auto_relay_info'.")
    db_path = ctx.obj["profile_dir"] / "kin.db"
    conn = open_profile_db(db_path)
    try:
        cursor = conn.execute("UPDATE contacts SET autonomy_level = ? WHERE username = ?", (policy, username))
        if cursor.rowcount == 0:
            raise typer.BadParameter(f"Contact '{username}' does not exist.")
        conn.commit()
    finally:
        conn.close()
    typer.echo(f"Policy for '{username}' is now {policy}.")


@app.command()
def configure(
    ctx: typer.Context,
    provider: str = typer.Option("openrouter", help="LiteLLM provider name, e.g. openrouter or openai."),
    model: str = typer.Option("openrouter/google/gemini-2.5-flash:free", help="LiteLLM model identifier."),
) -> None:
    """Store this profile's BYOK agent configuration in the OS keychain."""
    api_key = typer.prompt(f"API key for {provider}", hide_input=True, confirmation_prompt=True)
    if not api_key.strip():
        raise typer.BadParameter("API key cannot be empty.")
    save_llm_api_key(ctx.obj["profile_name"], provider, api_key.strip())
    db_path = ctx.obj["profile_dir"] / "kin.db"
    ctx.obj["profile_dir"].mkdir(parents=True, exist_ok=True)
    conn = open_profile_db(db_path)
    try:
        set_setting(conn, "llm_provider", provider)
        set_setting(conn, "llm_model", model)
    finally:
        conn.close()
    typer.echo(f"Agent configured for provider '{provider}' and model '{model}'.")


@app.command()
def tasks(
    ctx: typer.Context,
    status: Optional[str] = typer.Option(None, help="Filter by a task status."),
) -> None:
    """List local tasks, including drafts that need your approval."""
    db_path = ctx.obj["profile_dir"] / "kin.db"
    if not db_path.exists():
        typer.echo("No tasks yet.")
        return
    conn = open_profile_db(db_path)
    try:
        query = "SELECT task_id, contact_username, status, goal, updated_at FROM tasks"
        params: tuple = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY updated_at DESC"
        rows = conn.execute(query, params).fetchall()
        if not rows:
            typer.echo("No matching tasks.")
            return
        typer.echo("TASKS")
        for task_id, contact, task_status, goal, updated_at in rows:
            typer.echo(f"{task_id}  {task_status}  with {contact}\n  {goal}\n  updated {updated_at}")
    finally:
        conn.close()


@app.command()
def status(ctx: typer.Context, task_id: str = typer.Argument(help="Task ID to inspect")) -> None:
    """Show a task's audit history, current state, and any draft awaiting approval."""
    db_path = ctx.obj["profile_dir"] / "kin.db"
    conn = open_profile_db(db_path)
    try:
        task = conn.execute(
            "SELECT task_id, contact_username, goal, status, result_json, draft_content, draft_message_type "
            "FROM tasks WHERE task_id = ? OR peer_task_id = ?",
            (task_id, task_id),
        ).fetchone()
        if task is None:
            raise typer.BadParameter(f"Task '{task_id}' was not found.")
        local_id, contact, goal, task_status, result_json, draft, draft_type = task
        typer.echo(f"Task: {local_id}\nContact: {contact}\nStatus: {task_status}\nGoal: {goal}")
        for sender, content, message_type, created_at in conn.execute(
            "SELECT from_username, content, message_type, created_at FROM messages WHERE task_id = ? ORDER BY created_at", (local_id,)
        ):
            typer.echo(f"\n[{created_at}] {sender} ({message_type})\n{content}")
        if draft:
            typer.echo(f"\nDRAFT ({draft_type}) — run: kin respond {local_id}\n{draft}")
        if result_json:
            typer.echo(f"\nRESULT\n{result_json}")
    finally:
        conn.close()


@app.command()
def restore(
    ctx: typer.Context,
    phrase: Optional[str] = typer.Argument(None, help="Recovery phrase. Omit to enter it without saving it in shell history."),
) -> None:
    """Restore identity from a recovery phrase."""
    profile_name = ctx.obj["profile_name"]
    profile_dir = ctx.obj["profile_dir"]
    if phrase is None:
        phrase = typer.prompt("Enter your 12-word recovery phrase", hide_input=True)
    try:
        private_key, public_key = derive_key_pair(phrase)
        x_private, x_public = derive_x25519_key_pair(phrase)
    except Exception as exc:
        raise typer.BadParameter("That is not a valid 12-word KIN recovery phrase.") from exc
    if len(phrase.strip().split()) != 12:
        raise typer.BadParameter("A KIN recovery phrase has exactly 12 words.")

    username = typer.prompt("Enter the username registered to this identity")
    lookup = httpx.get(f"{get_relay_url()}/directory/lookup/{username}", timeout=15)
    if lookup.status_code == 404:
        raise typer.BadParameter("That username is not registered in the KIN directory.")
    lookup.raise_for_status()
    remote = lookup.json()
    if remote["public_key"] != public_key.hex() or remote["x25519_public_key"] != x_public.hex():
        raise typer.BadParameter("The recovery phrase does not match that username's registered identity.")

    profile_dir.mkdir(parents=True, exist_ok=True)
    conn = open_profile_db(profile_dir / "kin.db")
    try:
        if conn.execute("SELECT 1 FROM identity LIMIT 1").fetchone() is not None:
            raise typer.BadParameter("This profile already has an identity; choose a new --profile to restore safely.")
        save_private_key(profile_name, private_key)
        save_x25519_private_key(profile_name, x_private)
        conn.execute(
            "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
            (username, public_key.hex(), f"kin-{profile_name}-private-key", PROTOCOL_VERSION),
        )
        conn.commit()
        set_setting(conn, "public_endpoint", remote["endpoint"])
    finally:
        conn.close()
    typer.echo(f"Identity '{username}' restored. Pair contacts again on this device before sending messages.")



@app.command("migrate")
def migrate(ctx: typer.Context) -> None:
    """Migrate local profile storage schema using staging validation and atomic commit."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.storage.migrations import run_migrations, ALL_MIGRATIONS
    from kin.identity.storage import get_or_create_vault_key

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    profile_dir = resolver.profile_dir
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    if not db_path.exists():
        typer.echo(f"No database found for profile '{profile_name}' at {db_path}. Nothing to migrate.")
        return

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    staging_dir = profile_dir.parent / f"{profile_name}_staging_{timestamp_str}"

    conn = None
    staged_conn = None
    try:
        # Preflight: read original integrity facts
        conn = get_connection(db_path)
        
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contacts'")
        has_contacts = cur.fetchone() is not None
        orig_contacts_count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] if has_contacts else 0

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        has_tasks = cur.fetchone() is not None
        orig_tasks_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] if has_tasks else 0

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='identity'")
        has_identity = cur.fetchone() is not None
        orig_identity = conn.execute("SELECT username, public_key FROM identity LIMIT 1").fetchone() if has_identity else None

        conn.close()
        conn = None

        # Copy to staging directory
        shutil.copytree(profile_dir, staging_dir)

        # Validate on staging copy
        staged_db_path = staging_dir / "kin.db"
        staged_conn = get_connection(staged_db_path)
        report = run_migrations(staged_conn)

        if report.errors:
            raise RuntimeError(f"Migration failed during validation: {'; '.join(report.errors)}")

        # Validate post-migration integrity
        if has_identity:
            staged_identity = staged_conn.execute("SELECT username, public_key FROM identity LIMIT 1").fetchone()
            if staged_identity != orig_identity:
                raise RuntimeError("Integrity check failed: identity record changed after migration")

        if has_contacts:
            staged_contacts = staged_conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
            if staged_contacts != orig_contacts_count:
                raise RuntimeError(f"Integrity check failed: contacts count changed ({orig_contacts_count} -> {staged_contacts})")

        if has_tasks:
            staged_tasks = staged_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            if staged_tasks != orig_tasks_count:
                raise RuntimeError(f"Integrity check failed: tasks count changed ({orig_tasks_count} -> {staged_tasks})")

        max_ver = staged_conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        expected_max = max(m.version for m in ALL_MIGRATIONS)
        if max_ver != expected_max:
            raise RuntimeError(f"Integrity check failed: expected latest version {expected_max}, got {max_ver}")

        # Validate vault key readiness (keyring / keychain check)
        get_or_create_vault_key(profile_name)

        staged_conn.close()
        staged_conn = None

        # Atomic commit: swap staged kin.db file with original db_path
        os.replace(staged_db_path, db_path)

        typer.echo(
            f"Migration report for profile '{profile_name}': "
            f"applied={report.applied}, skipped={report.skipped}, "
            f"version={report.starting_version}->{report.ending_version}"
        )

    except Exception as err:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if staged_conn is not None:
            try:
                staged_conn.close()
            except Exception:
                pass

        # Write failure report outside authoritative profile directory
        report_dir = Path.home() / ".kin" / "migration-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        failure_report_path = report_dir / f"{profile_name}-{timestamp_str}.json"
        failure_data = {
            "profile": profile_name,
            "timestamp": timestamp_str,
            "status": "failed",
            "error": str(err),
            "recoverable": True,
        }
        failure_report_path.write_text(json.dumps(failure_data, indent=2))

        typer.echo(f"ERROR: Migration failed for profile '{profile_name}': {err}", err=True)
        typer.echo(f"Original profile database left untouched. Failure report written to: {failure_report_path}", err=True)
        raise typer.Exit(1)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


# ------------------------------------------------------------------------------
# kin agent subcommand group (Milestone M2)
# ------------------------------------------------------------------------------
agent_app = typer.Typer(name="agent", help="Manage local agent cards.")
app.add_typer(agent_app)


@agent_app.command("list")
def agent_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit stable JSON list format."),
) -> None:
    """Scan agents_dir, register/refresh valid cards, list them with availability."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.identity.storage import get_or_create_vault_key
    from kin.schemas import AgentAvailability
    from kin.agent_registry.availability import AVAILABILITY_EXPLANATIONS
    from kin.agent_registry.registry import (
        get_agents_dir,
        list_cards,
        register_card,
        scan_local_cards,
    )

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    profile_dir = resolver.profile_dir
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    profile_dir.mkdir(parents=True, exist_ok=True)
    conn = open_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)

    try:
        agents_dir = get_agents_dir(resolver)
        valid_cards, per_file_errors, legacy_v1_files_skipped = scan_local_cards(agents_dir, profile_name=profile_name)

        for card in valid_cards:
            register_card(conn, vault_key, card, profile_name=profile_name)

        cards = list_cards(conn, include_disabled=True)
        for c in cards:
            avail_enum = AgentAvailability(c["availability"])
            c["availability_reason"] = AVAILABILITY_EXPLANATIONS.get(avail_enum, "")

        if json_output:
            typer.echo(json.dumps(cards, indent=2))
        else:
            if not cards:
                typer.echo("No local agent cards registered.")
            else:
                typer.echo("REGISTERED AGENT CARDS:")
                for c in cards:
                    typer.echo(
                        f"  - {c['agent_id']} ({c['name']}) [adapter: {c['adapter_type']}, enabled: {c['enabled']}, status: {c['availability']}, version: v{c['card_version']}]\n"
                        f"    Explanation: {c['availability_reason']}"
                    )

            if per_file_errors:
                typer.echo("\nPER-FILE LOAD ERRORS:", err=True)
                for err in per_file_errors:
                    typer.echo(f"  - {err}", err=True)

            if legacy_v1_files_skipped:
                typer.echo("\nSKIPPED LEGACY V1 FILES:")
                for path in legacy_v1_files_skipped:
                    typer.echo(f"  - {path.name}")
    finally:
        conn.close()


@agent_app.command("inspect")
def agent_inspect(
    ctx: typer.Context,
    agent_id: str = typer.Argument(..., help="Agent ID to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit PublishedAgentCard projection JSON ONLY."),
) -> None:
    """Inspect a local agent card."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.identity.storage import get_or_create_vault_key
    from kin.schemas import AgentCard
    from kin.storage.vault import decrypt_field
    from kin.agent_registry.availability import AVAILABILITY_EXPLANATIONS, compute_availability
    from kin.agent_registry.registry import get_card, publish_card

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    if not db_path.exists():
        typer.echo(f"ERROR: Agent '{agent_id}' not found.", err=True)
        raise typer.Exit(1)

    conn = open_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)

    try:
        record = get_card(conn, agent_id)
        if record is None:
            typer.echo(f"ERROR: Agent '{agent_id}' not found.", err=True)
            raise typer.Exit(1)

        decrypted_json = decrypt_field(vault_key, record["local_card_json"])
        if decrypted_json is None:
            typer.echo(f"ERROR: Failed to decrypt agent card '{agent_id}'.", err=True)
            raise typer.Exit(1)

        card = AgentCard.model_validate_json(decrypted_json)
        avail = compute_availability(card, profile_name, enabled=record["enabled"])
        avail_reason = AVAILABILITY_EXPLANATIONS.get(avail, "")

        if json_output:
            pub_card = publish_card(card)
            pub_card.availability = avail
            out_dict = pub_card.model_dump()
            out_dict["availability_reason"] = avail_reason
            typer.echo(json.dumps(out_dict, indent=2))
        else:
            typer.echo(f"Agent ID: {card.id}")
            typer.echo(f"Name: {card.name}")
            typer.echo(f"Description: {card.description}")
            typer.echo(f"Adapter Type: {card.adapter.type}")
            typer.echo(f"Enabled: {record['enabled']}")
            typer.echo(f"Availability: {avail.value} ({avail_reason})")
            typer.echo(f"Card Version: {record['card_version']}")
            typer.echo(f"Capabilities Tags: {card.capabilities.tags}")
            typer.echo(f"Capabilities Accepts: {card.capabilities.accepts}")
            typer.echo(f"Boundaries Network: {card.boundaries.network_access}, Filesystem: {card.boundaries.filesystem}, Shell: {card.boundaries.shell}")
            typer.echo(f"Autonomy Relay: {card.autonomy.relay_information.value}, Propose: {card.autonomy.propose_actions.value}, Execute: {card.autonomy.execute_local_actions.value}")
    finally:
        conn.close()


@agent_app.command("validate")
def agent_validate(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Path to agent YAML file to validate."),
) -> None:
    """Validate an agent card YAML file without importing it."""
    from kin.agent_registry.loader import CardLoadError, load_card_file

    profile_name = ctx.obj["profile_name"]
    try:
        card = load_card_file(path, profile_name=profile_name)
        typer.echo(f"Card '{path}' is valid (Agent ID: '{card.id}').")
    except CardLoadError as err:
        typer.echo(f"ERROR: Card validation failed for '{path}': {err}", err=True)
        raise typer.Exit(1)
    except Exception as err:
        typer.echo(f"ERROR: Card validation failed for '{path}': {err}", err=True)
        raise typer.Exit(1)


@agent_app.command("enable")
def agent_enable(
    ctx: typer.Context,
    agent_id: str = typer.Argument(..., help="Agent ID to enable."),
) -> None:
    """Enable a local agent card."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.identity.storage import get_or_create_vault_key
    from kin.agent_registry.registry import set_enabled

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    if not db_path.exists():
        typer.echo(f"ERROR: Agent '{agent_id}' not found.", err=True)
        raise typer.Exit(1)

    conn = open_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)
    try:
        set_enabled(conn, agent_id, True, profile_name=profile_name, vault_key=vault_key)
        typer.echo(f"Agent '{agent_id}' enabled.")
    except Exception as err:
        typer.echo(f"ERROR: Failed to enable agent '{agent_id}': {err}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()


@agent_app.command("disable")
def agent_disable(
    ctx: typer.Context,
    agent_id: str = typer.Argument(..., help="Agent ID to disable."),
) -> None:
    """Disable a local agent card."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.identity.storage import get_or_create_vault_key
    from kin.agent_registry.registry import set_enabled

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    if not db_path.exists():
        typer.echo(f"ERROR: Agent '{agent_id}' not found.", err=True)
        raise typer.Exit(1)

    conn = open_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)
    try:
        set_enabled(conn, agent_id, False, profile_name=profile_name, vault_key=vault_key)
        typer.echo(f"Agent '{agent_id}' disabled.")
    except Exception as err:
        typer.echo(f"ERROR: Failed to disable agent '{agent_id}': {err}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()


@agent_app.command("import")
def agent_import(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Path to agent YAML file to import."),
) -> None:
    """Validate, copy, and register an agent card into profile agents directory."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.identity.storage import get_or_create_vault_key
    from kin.agent_registry.loader import CardLoadError
    from kin.agent_registry.registry import import_card

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    profile_dir = resolver.profile_dir
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    profile_dir.mkdir(parents=True, exist_ok=True)
    conn = open_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)

    try:
        card = import_card(conn, vault_key, resolver, path)
        typer.echo(f"Agent '{card.id}' imported and registered successfully.")
    except CardLoadError as err:
        typer.echo(f"ERROR: Import failed: {err}", err=True)
        raise typer.Exit(1)
    except Exception as err:
        typer.echo(f"ERROR: Import failed: {err}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()


@agent_app.command("publish")
def agent_publish(
    ctx: typer.Context,
    agent_id: str = typer.Argument(..., help="Agent ID to publish/project."),
    json_output: bool = typer.Option(False, "--json", help="Emit PublishedAgentCard JSON format."),
) -> None:
    """Compute and display the PublishedAgentCard projection (local display only, no network transport)."""
    from kin.identity.resolver import ProfileContextResolver
    from kin.identity.storage import get_or_create_vault_key
    from kin.schemas import AgentCard
    from kin.storage.vault import decrypt_field
    from kin.agent_registry.availability import compute_availability
    from kin.agent_registry.registry import get_card, publish_card

    profile_name = ctx.obj["profile_name"]
    root_dir = Path.home() / ".kin"
    resolver = ProfileContextResolver(profile_name, root_dir)
    db_path = resolver.resolve_profile_path(profile_name, "kin.db")

    if not db_path.exists():
        typer.echo(f"ERROR: Agent '{agent_id}' not found.", err=True)
        raise typer.Exit(1)

    conn = open_profile_db(db_path)
    vault_key = get_or_create_vault_key(profile_name)

    try:
        record = get_card(conn, agent_id)
        if record is None:
            typer.echo(f"ERROR: Agent '{agent_id}' not found.", err=True)
            raise typer.Exit(1)

        if not record["enabled"]:
            typer.echo(f"ERROR: Agent '{agent_id}' is disabled. Enable it before publishing.", err=True)
            raise typer.Exit(1)

        decrypted_json = decrypt_field(vault_key, record["local_card_json"])
        if decrypted_json is None:
            typer.echo(f"ERROR: Failed to decrypt agent card '{agent_id}'.", err=True)
            raise typer.Exit(1)

        card = AgentCard.model_validate_json(decrypted_json)
        pub_card = publish_card(card)
        pub_card.availability = compute_availability(card, profile_name, enabled=record["enabled"])

        if json_output:
            typer.echo(pub_card.model_dump_json(indent=2))
        else:
            typer.echo("PUBLISHED AGENT CARD PROJECTION:")
            typer.echo(f"  Agent ID: {pub_card.agent_id}")
            typer.echo(f"  Name: {pub_card.name}")
            typer.echo(f"  Description: {pub_card.description}")
            typer.echo(f"  Capabilities: {pub_card.capabilities.tags}")
            typer.echo(f"  Availability: {pub_card.availability.value}")
            typer.echo(f"  Requires Owner Acceptance: {pub_card.requires_owner_acceptance}")
            typer.echo("\nNote: This PublishedAgentCard projection is ready for peer discovery. No transport transmission was performed.")
    finally:
        conn.close()


if __name__ == "__main__":
    app()
