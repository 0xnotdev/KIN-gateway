"""M6 contract, fault-injection, and redaction tests for ``kin doctor``."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from kin.cli import app
from kin.identity.storage import (
    save_llm_api_key,
    save_private_key,
    save_x25519_private_key,
)
from kin.storage.db import create_schema, get_connection, set_setting


CHECK_NAMES = (
    "version_profile",
    "keychain",
    "identity",
    "relay_directory",
    "node_tunnel",
    "card_validation",
    "provider_credentials",
    "inbox",
    "recovery",
)


def _healthy_profile(profile_dir: Path, profile_name: str = "doctor-test") -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection(profile_dir / "kin.db")
    create_schema(conn)
    conn.execute(
        "INSERT INTO identity (username, public_key, keychain_ref, protocol_version) VALUES (?, ?, ?, ?)",
        ("alice", (b"p" * 32).hex(), "keychain-only-reference", "1.1"),
    )
    set_setting(conn, "public_endpoint", "https://alice-node.example")
    set_setting(conn, "llm_provider", "openrouter")
    conn.commit()
    conn.close()
    save_private_key(profile_name, b"e" * 32)
    save_x25519_private_key(profile_name, b"x" * 32)
    save_llm_api_key(profile_name, "openrouter", "sk-proj-doctor-secret-value-never-print")


def _healthy_http_get(url: str, **kwargs) -> httpx.Response:
    del kwargs
    if url.endswith("/v1.1/capabilities"):
        return httpx.Response(200, json={"supported_features": ["session_v1"]})
    return httpx.Response(404)


def test_doctor_json_reports_every_dependency_without_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_name = "doctor-test"
    profile_dir = tmp_path / "profiles" / profile_name
    _healthy_profile(profile_dir, profile_name)
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    monkeypatch.setattr("kin.doctor.httpx.get", _healthy_http_get)

    result = CliRunner().invoke(app, ["--profile", profile_name, "doctor", "--json"])

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["status"] == "healthy"
    assert [item["check"] for item in report["checks"]] == list(CHECK_NAMES)
    assert all(item["status"] == "pass" for item in report["checks"])
    assert "sk-proj-doctor-secret-value-never-print" not in result.stdout
    assert (b"e" * 32).hex() not in result.stdout
    assert (b"x" * 32).hex() not in result.stdout


@pytest.mark.parametrize("check_name", CHECK_NAMES)
def test_doctor_fault_injection_is_structured_for_every_checked_dependency(
    check_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every dependency failure becomes one actionable result, never a traceback."""
    from kin import doctor as doctor_module

    profile_name = "doctor-test"
    profile_dir = tmp_path / "profiles" / profile_name
    _healthy_profile(profile_dir, profile_name)
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    monkeypatch.setattr("kin.doctor.httpx.get", _healthy_http_get)

    def injected_failure(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected dependency failure")

    monkeypatch.setattr(doctor_module, f"check_{check_name}", injected_failure)
    result = CliRunner().invoke(app, ["--profile", profile_name, "doctor", "--json"])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    failed = next(item for item in report["checks"] if item["check"] == check_name)
    assert failed["status"] == "fail"
    assert failed["action"]
    assert failed["facts"] == {"available": False}
    assert "Traceback" not in result.stdout
    assert result.exception is not None


def test_doctor_keychain_locked_and_relay_unreachable_are_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_name = "doctor-test"
    profile_dir = tmp_path / "profiles" / profile_name
    _healthy_profile(profile_dir, profile_name)
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    monkeypatch.setattr(
        "kin.identity.storage._assert_secure_backend",
        lambda: (_ for _ in ()).throw(RuntimeError("OS keychain is locked")),
    )

    def unreachable(url: str, **kwargs):
        del kwargs
        if "directory/lookup" in url:
            raise httpx.ConnectError("relay refused connection")
        return httpx.Response(200, json={})

    monkeypatch.setattr("kin.doctor.httpx.get", unreachable)
    result = CliRunner().invoke(app, ["--profile", profile_name, "doctor", "--plain"])

    assert result.exit_code == 1
    assert "[FAIL] keychain: Keychain check failed: OS keychain is locked" in result.stdout
    assert "[FAIL] relay_directory: Relay Directory check failed: relay refused connection" in result.stdout
    assert "Unlock or configure a supported OS credential manager" in result.stdout
    assert "Check KIN_RELAY_URL and start or reconnect the relay" in result.stdout
    assert "Traceback" not in result.stdout


def test_doctor_redacts_values_even_when_a_dependency_exception_contains_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kin import doctor as doctor_module

    profile_name = "doctor-test"
    profile_dir = tmp_path / "profiles" / profile_name
    _healthy_profile(profile_dir, profile_name)
    monkeypatch.setattr("kin.cli.get_profile_dir", lambda _profile: profile_dir)
    monkeypatch.setattr("kin.doctor.httpx.get", _healthy_http_get)
    leaked_api_key = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    leaked_private_key = (b"z" * 32).hex()

    def leaking_dependency(*args, **kwargs):
        del args, kwargs
        raise RuntimeError(
            f"api_key={leaked_api_key} private_key={leaked_private_key} at C:\\Users\\alice\\secret.txt"
        )

    monkeypatch.setattr(doctor_module, "check_provider_credentials", leaking_dependency)
    result = CliRunner().invoke(app, ["--profile", profile_name, "doctor", "--json"])

    assert result.exit_code == 1
    assert leaked_api_key not in result.stdout
    assert leaked_private_key not in result.stdout
    assert "C:\\Users\\alice\\secret.txt" not in result.stdout
    assert "[REDACTED SECRET]" in result.stdout
    assert "[REDACTED PATH]" in result.stdout
