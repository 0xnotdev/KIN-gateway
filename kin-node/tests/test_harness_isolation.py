"""Profile isolation and context boundary tests for multi-profile harness setups."""

from pathlib import Path
import pytest

from kin.identity.resolver import AccessBoundaryViolation, ProfileContextResolver


def test_profile_path_isolation(tmp_path: Path):
    """Test that Alice's context resolver cannot access Bob's profile filesystem directory using Path.is_relative_to()."""
    alice_resolver = ProfileContextResolver("alice", tmp_path)
    bob_resolver = ProfileContextResolver("bob", tmp_path)

    # Valid access
    alice_db = alice_resolver.resolve_profile_path("alice", "kin.db")
    assert str(alice_db).endswith(str(Path("profiles/alice/kin.db")))

    bob_db = bob_resolver.resolve_profile_path("bob", "kin.db")
    assert str(bob_db).endswith(str(Path("profiles/bob/kin.db")))

    # Boundary violation check
    with pytest.raises(AccessBoundaryViolation):
        alice_resolver.resolve_profile_path("bob", "kin.db")

    with pytest.raises(AccessBoundaryViolation):
        bob_resolver.resolve_profile_path("alice", "kin.db")


def test_profile_keychain_isolation(tmp_path: Path):
    """Test that Alice's context resolver cannot access Bob's keychain service namespace."""
    alice_resolver = ProfileContextResolver("alice", tmp_path)

    alice_service = alice_resolver.resolve_keychain_service("alice", "private_key")
    assert alice_service == "kin-alice-private-key"

    with pytest.raises(AccessBoundaryViolation):
        alice_resolver.resolve_keychain_service("bob", "private_key")


def test_path_traversal_prevention(tmp_path: Path):
    """Test that path traversal attempts outside profile directory are blocked."""
    alice_resolver = ProfileContextResolver("alice", tmp_path)

    with pytest.raises(AccessBoundaryViolation):
        alice_resolver.resolve_profile_path("alice", "../bob/kin.db")


def test_invalid_profile_name_validation(tmp_path: Path):
    """Test that invalid profile names with special characters are rejected."""
    with pytest.raises(ValueError):
        ProfileContextResolver("invalid/profile/name", tmp_path)
