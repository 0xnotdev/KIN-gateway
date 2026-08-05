"""Structured, non-mutating health checks for ``kin doctor``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable

import httpx

from kin.tui.redaction import redact_ui_text


_LABELED_KEY_MATERIAL = re.compile(
    r"(?i)\b(?:private|public|vault|x25519|ed25519|signing|encryption)[_-]?key"
    r"\s*[:=]\s*[^\s,;]+"
)


def _redact_doctor_text(value: str) -> str:
    """Scrub diagnostic errors more strictly than ordinary display content."""
    return _LABELED_KEY_MATERIAL.sub("[REDACTED SECRET]", redact_ui_text(value))


@dataclass(frozen=True)
class DoctorCheck:
    """One actionable health-check result with no secret-bearing fields."""

    check: str
    status: str
    summary: str
    action: str
    facts: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _result(
    check: str,
    status: str,
    summary: str,
    action: str,
    **facts: object,
) -> DoctorCheck:
    return DoctorCheck(
        check=check,
        status=status,
        summary=_redact_doctor_text(summary),
        action=_redact_doctor_text(action),
        facts={key: value for key, value in facts.items()},
    )


def check_version_profile(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Report package and selected profile without exposing an absolute path."""
    try:
        package_version = version("kin-cli")
    except PackageNotFoundError:
        package_version = "development"
    exists = profile_dir.is_dir()
    return _result(
        "version_profile",
        "pass" if exists else "warn",
        f"KIN {package_version}; selected profile '{profile_name}'.",
        "No action required." if exists else "Run 'kin init' to initialize this profile.",
        version=package_version,
        profile=profile_name,
        profile_location=f"~/.kin/profiles/{profile_name}",
        profile_exists=exists,
    )


def check_keychain(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Verify the credential backend without reading or returning secret values."""
    del profile_name, profile_dir
    from kin.identity.storage import _assert_secure_backend

    _assert_secure_backend()
    return _result(
        "keychain",
        "pass",
        "Secure OS credential backend is available.",
        "No action required.",
        secure_backend=True,
    )


def _open_existing_db(profile_dir: Path) -> sqlite3.Connection:
    db_path = profile_dir / "kin.db"
    if not db_path.is_file():
        raise FileNotFoundError("Profile database is not initialized.")
    return sqlite3.connect(db_path)


def check_identity(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Verify identity metadata and both private key entries by presence only."""
    from kin.identity.storage import load_private_key, load_x25519_private_key

    conn = _open_existing_db(profile_dir)
    try:
        row = conn.execute(
            "SELECT username, public_key, protocol_version FROM identity LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return _result(
            "identity",
            "fail",
            "No local identity is initialized.",
            "Run 'kin init'.",
            identity_present=False,
        )

    ed_key = load_private_key(profile_name)
    x_key = load_x25519_private_key(profile_name)
    if len(ed_key) != 32 or len(x_key) != 32:
        raise ValueError("Stored identity key material has an invalid length.")
    return _result(
        "identity",
        "pass",
        f"Identity '{row[0]}' and signing/encryption key entries are present.",
        "No action required.",
        identity_present=True,
        username=row[0],
        protocol_version=row[2],
        signing_key_present=True,
        encryption_key_present=True,
    )


def check_relay_directory(
    profile_name: str,
    profile_dir: Path,
    *,
    relay_url: str,
) -> DoctorCheck:
    """Probe relay directory routing without requiring a registered probe user."""
    del profile_name, profile_dir
    response = httpx.get(
        f"{relay_url.rstrip('/')}/directory/lookup/__kin_doctor_probe__",
        timeout=3.0,
    )
    if response.status_code not in (200, 204, 404):
        raise RuntimeError(f"Relay directory returned HTTP {response.status_code}.")
    return _result(
        "relay_directory",
        "pass",
        "Relay directory is reachable.",
        "No action required.",
        reachable=True,
        http_status=response.status_code,
    )


def check_node_tunnel(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Probe the profile's configured node/tunnel capability endpoint."""
    del profile_name
    conn = _open_existing_db(profile_dir)
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'public_endpoint'"
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row[0]:
        return _result(
            "node_tunnel",
            "warn",
            "No node or tunnel endpoint is configured.",
            "Run 'kin serve' or provide --public-endpoint when starting the node.",
            configured=False,
            reachable=False,
        )

    response = httpx.get(f"{str(row[0]).rstrip('/')}/v1.1/capabilities", timeout=3.0)
    if response.status_code != 200:
        raise RuntimeError(f"Configured node returned HTTP {response.status_code}.")
    return _result(
        "node_tunnel",
        "pass",
        "Configured node/tunnel endpoint is reachable.",
        "No action required.",
        configured=True,
        reachable=True,
        http_status=response.status_code,
    )


def check_card_validation(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Validate every V1.1 card in the selected profile."""
    from kin.agent_registry.registry import scan_local_cards

    valid, errors, legacy = scan_local_cards(profile_dir / "agents", profile_name)
    if errors:
        return _result(
            "card_validation",
            "fail",
            f"{len(errors)} agent card(s) failed validation.",
            "Run 'kin agent validate <path>' for each invalid card.",
            valid_cards=len(valid),
            invalid_cards=len(errors),
            legacy_cards=len(legacy),
        )
    return _result(
        "card_validation",
        "warn" if legacy else "pass",
        f"Validated {len(valid)} V1.1 agent card(s).",
        "Remove or migrate skipped legacy cards." if legacy else "No action required.",
        valid_cards=len(valid),
        invalid_cards=0,
        legacy_cards=len(legacy),
    )


def check_provider_credentials(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Report provider credential presence without ever returning its value."""
    from kin.identity.storage import SecretNotFoundError, load_llm_api_key

    provider = None
    if (profile_dir / "kin.db").is_file():
        conn = _open_existing_db(profile_dir)
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'llm_provider'"
            ).fetchone()
            provider = row[0] if row else None
        finally:
            conn.close()
    if not provider:
        return _result(
            "provider_credentials",
            "warn",
            "No LLM provider is configured.",
            "Run 'kin configure'.",
            provider=None,
            credential_present=False,
        )
    try:
        credential = load_llm_api_key(profile_name, provider)
    except SecretNotFoundError:
        credential = None
    if not credential:
        return _result(
            "provider_credentials",
            "fail",
            f"Provider '{provider}' is configured but its credential is absent.",
            "Run 'kin configure' to store the credential in the OS keychain.",
            provider=provider,
            credential_present=False,
        )
    return _result(
        "provider_credentials",
        "pass",
        f"Credential for provider '{provider}' is present in the OS keychain.",
        "No action required.",
        provider=provider,
        credential_present=True,
    )


def check_inbox(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Count owner-attention and outbound recovery work without decrypting content."""
    del profile_name
    conn = _open_existing_db(profile_dir)
    try:
        approvals = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE decision IS NULL"
        ).fetchone()[0]
        sessions = conn.execute(
            """SELECT COUNT(*) FROM sessions
               WHERE status IN ('peer_review', 'needs_clarification', 'awaiting_owner_approval')"""
        ).fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM outbound_envelope_queue WHERE delivery_state = 'pending'"
        ).fetchone()[0]
    finally:
        conn.close()
    pending = approvals + sessions
    return _result(
        "inbox",
        "warn" if pending or queued else "pass",
        f"Inbox has {pending} owner-attention item(s); {queued} outbound item(s) are pending.",
        "Run 'kin inbox --plain' and review pending items." if pending else (
            "Run 'kin fetch' or start the node to retry queued delivery." if queued else "No action required."
        ),
        owner_attention=pending,
        pending_approvals=approvals,
        pending_sessions=sessions,
        queued_outbound=queued,
    )


def check_recovery(profile_name: str, profile_dir: Path) -> DoctorCheck:
    """Check SQLite integrity and outstanding local recovery evidence."""
    del profile_name
    conn = _open_existing_db(profile_dir)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        failed_or_expired = conn.execute(
            """SELECT COUNT(*) FROM outbound_envelope_queue
               WHERE delivery_state IN ('failed', 'expired', 'abandoned')"""
        ).fetchone()[0]
    finally:
        conn.close()
    if integrity != "ok":
        raise RuntimeError("SQLite integrity check failed.")
    report_dir = profile_dir.parent.parent / "migration-reports"
    failure_reports = len(list(report_dir.glob(f"{profile_dir.name}-*.json"))) if report_dir.is_dir() else 0
    diagnostics_present = (profile_dir / "diagnostics.log").is_file()
    attention = failed_or_expired or failure_reports
    return _result(
        "recovery",
        "warn" if attention else "pass",
        "Profile database integrity is valid."
        + (f" {failed_or_expired} failed/expired queued item(s) need review." if failed_or_expired else ""),
        "Review migration reports, diagnostics, and failed queue entries." if attention else "No action required.",
        database_integrity=True,
        failed_or_expired_queue=failed_or_expired,
        migration_failure_reports=failure_reports,
        diagnostics_present=diagnostics_present,
    )


def _run_check(
    name: str,
    action: str,
    check: Callable[[], DoctorCheck],
) -> DoctorCheck:
    try:
        return check()
    except Exception as exc:
        return _result(
            name,
            "fail",
            f"{name.replace('_', ' ').title()} check failed: {exc}",
            action,
            available=False,
        )


def run_doctor(profile_name: str, profile_dir: Path, relay_url: str) -> dict[str, object]:
    """Run every dependency check and always return a structured report."""
    checks = [
        _run_check(
            "version_profile",
            "Verify the KIN installation and initialize the selected profile.",
            lambda: check_version_profile(profile_name, profile_dir),
        ),
        _run_check(
            "keychain",
            "Unlock or configure a supported OS credential manager, then retry.",
            lambda: check_keychain(profile_name, profile_dir),
        ),
        _run_check(
            "identity",
            "Run 'kin init' or restore the identity into a new profile.",
            lambda: check_identity(profile_name, profile_dir),
        ),
        _run_check(
            "relay_directory",
            "Check KIN_RELAY_URL and start or reconnect the relay.",
            lambda: check_relay_directory(profile_name, profile_dir, relay_url=relay_url),
        ),
        _run_check(
            "node_tunnel",
            "Start 'kin serve' and verify the configured endpoint or tunnel.",
            lambda: check_node_tunnel(profile_name, profile_dir),
        ),
        _run_check(
            "card_validation",
            "Validate or repair local agent cards.",
            lambda: check_card_validation(profile_name, profile_dir),
        ),
        _run_check(
            "provider_credentials",
            "Run 'kin configure'; credentials must remain in the OS keychain.",
            lambda: check_provider_credentials(profile_name, profile_dir),
        ),
        _run_check(
            "inbox",
            "Initialize the profile or inspect pending work with 'kin inbox --plain'.",
            lambda: check_inbox(profile_name, profile_dir),
        ),
        _run_check(
            "recovery",
            "Run 'kin migrate' or inspect local recovery reports before retrying.",
            lambda: check_recovery(profile_name, profile_dir),
        ),
    ]
    failures = sum(check.status == "fail" for check in checks)
    warnings = sum(check.status == "warn" for check in checks)
    return {
        "schema_version": 1,
        "status": "degraded" if failures else ("needs_attention" if warnings else "healthy"),
        "profile": profile_name,
        "summary": {"passed": len(checks) - failures - warnings, "warnings": warnings, "failed": failures},
        "checks": [check.to_dict() for check in checks],
    }


def format_doctor_plain(report: dict[str, object]) -> str:
    """Render deterministic box-free diagnostic output for terminals and pipes."""
    lines = [
        "KIN DOCTOR",
        f"STATUS: {str(report['status']).upper()}",
        f"PROFILE: {report['profile']}",
        "CHECKS:",
    ]
    for item in report["checks"]:
        check = dict(item)
        lines.append(
            f"[{str(check['status']).upper()}] {check['check']}: {check['summary']}"
        )
        lines.append(f"  ACTION: {check['action']}")
        lines.append(f"  FACTS: {json.dumps(check['facts'], sort_keys=True)}")
    summary = dict(report["summary"])
    lines.append(
        f"SUMMARY: passed={summary['passed']} warnings={summary['warnings']} failed={summary['failed']}"
    )
    return "\n".join(lines)
