"""Shared signed HTTP header authentication helper functions."""

from __future__ import annotations

import datetime
from typing import Callable

from cryptography.hazmat.primitives.asymmetric import ed25519
from kin.schemas import base64url_decode, base64url_encode


def create_signed_auth_headers(
    username: str,
    private_key: ed25519.Ed25519PrivateKey,
    now: datetime.datetime | None = None,
) -> dict[str, str]:
    """Generate X-Username, X-Timestamp, and X-Signature headers."""
    ts_str = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    if not ts_str.endswith("Z"):
        ts_str = ts_str.split("+")[0] + "Z"

    canonical_str = f"{username}:{ts_str}"
    sig_bytes = private_key.sign(canonical_str.encode("utf-8"))
    sig_b64 = base64url_encode(sig_bytes)

    return {
        "X-Username": username,
        "X-Timestamp": ts_str,
        "X-Signature": sig_b64,
    }


def verify_signed_auth_headers(
    headers: dict[str, str],
    get_public_key_fn: Callable[[str], ed25519.Ed25519PublicKey | None],
    now: datetime.datetime | None = None,
    max_age_seconds: int = 300,
) -> tuple[bool, str | None, str | None]:
    """Verify signed HTTP request headers (X-Username, X-Timestamp, X-Signature).

    Returns (success, authenticated_username, error_message).
    """
    header_map = {k.lower(): v for k, v in headers.items()}
    username = header_map.get("x-username")
    timestamp = header_map.get("x-timestamp")
    signature = header_map.get("x-signature")

    if not username or not timestamp or not signature:
        return False, None, "Missing required authentication headers (X-Username, X-Timestamp, X-Signature)"

    current_time = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        ts_clean = timestamp.rstrip("Z")
        ts_dt = datetime.datetime.fromisoformat(ts_clean).replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return False, None, "Invalid ISO 8601 timestamp format in X-Timestamp header"

    diff_seconds = abs((current_time - ts_dt).total_seconds())
    if diff_seconds > max_age_seconds:
        return False, None, f"Authentication timestamp expired or out of window (diff: {diff_seconds:.1f}s > {max_age_seconds}s)"

    pub_key = get_public_key_fn(username)
    if not pub_key:
        return False, None, f"Public key for user '{username}' not found or contact untrusted"

    canonical_str = f"{username}:{timestamp}"
    try:
        sig_bytes = base64url_decode(signature)
        pub_key.verify(sig_bytes, canonical_str.encode("utf-8"))
    except Exception:
        return False, None, f"Invalid signature verification for user '{username}'"

    return True, username, None
