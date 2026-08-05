"""FastAPI application instance and durable V1.1 relay synchronization loop."""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os

from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi import FastAPI

from kin.cli import DEFAULT_RELAY_URL, open_profile_db
from kin.identity.storage import get_or_create_vault_key, load_private_key, load_x25519_private_key
from kin.node.routes import router
from kin.transport.v11 import poll_relay_and_process, retry_outbound_queue
from kin.version import KIN_VERSION

logger = logging.getLogger(__name__)


def _synchronize_once(app: FastAPI) -> None:
    """Retry durable outbound work and consume the encrypted relay mailbox once."""
    profile_name = getattr(app.state, "profile_name", None)
    db_path = getattr(app.state, "db_path", None)
    if not profile_name or not db_path:
        return

    conn = open_profile_db(db_path)
    try:
        identity = conn.execute("SELECT username FROM identity LIMIT 1").fetchone()
        if identity is None:
            return
        username = identity[0]
        owner_key = ed25519.Ed25519PrivateKey.from_private_bytes(load_private_key(profile_name))
        owner_x25519 = load_x25519_private_key(profile_name)
        vault_key = get_or_create_vault_key(profile_name)
        relay_url = os.environ.get("KIN_RELAY_URL", DEFAULT_RELAY_URL).rstrip("/")

        def get_public_key(peer_username: str):
            if peer_username == username:
                return owner_key.public_key()
            row = conn.execute(
                "SELECT public_key FROM contacts WHERE username = ? AND fingerprint_verified_at IS NOT NULL",
                (peer_username,),
            ).fetchone()
            if not row or not row[0]:
                return None
            return ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(row[0]))

        retry_outbound_queue(
            conn,
            vault_key,
            owner_username=username,
            owner_x25519_privkey=owner_x25519,
            relay_url=relay_url,
        )
        poll_relay_and_process(
            conn,
            vault_key,
            username,
            owner_key,
            owner_x25519,
            relay_url,
            get_public_key,
        )
    except Exception:
        logger.warning("KIN background synchronization pass failed; durable data was retained.", exc_info=True)
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def synchronization_loop() -> None:
        while True:
            await asyncio.to_thread(_synchronize_once, app)
            await asyncio.sleep(5)

    task = asyncio.create_task(synchronization_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="KIN Node", version=KIN_VERSION, lifespan=lifespan)
app.include_router(router)
