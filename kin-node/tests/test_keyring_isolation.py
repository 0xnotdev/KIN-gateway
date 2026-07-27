"""Regression test for Defect A: Keyring isolation between test functions."""

import pytest
import keyring
from kin.identity.storage import save_private_key, load_private_key, SecretNotFoundError
from kin.testing.insecure_memory_keyring import InMemoryTestKeyring

_TEST_KEY_1 = b"0" * 32
_TEST_KEY_2 = b"1" * 32


def test_isolation_part1():
    """Test 1 saves private key for profile 'test-p'."""
    keyring.set_keyring(InMemoryTestKeyring())
    save_private_key("test-p", _TEST_KEY_1)
    assert load_private_key("test-p") == _TEST_KEY_1


def test_isolation_part2():
    """Test 2 must NOT see private key saved by Test 1 for profile 'test-p'."""
    keyring.set_keyring(InMemoryTestKeyring())
    with pytest.raises(SecretNotFoundError):
        load_private_key("test-p")
