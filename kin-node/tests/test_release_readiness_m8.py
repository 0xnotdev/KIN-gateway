"""M8 packaging, documentation, installer, and release-control contracts."""

from pathlib import Path
import tomllib

from typer.testing import CliRunner

import kin
from kin.cli import PROTOCOL_VERSION, app
from kin.version import KIN_VERSION, V11_PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[2]
NODE_ROOT = ROOT / "kin-node"


def test_release_version_and_user_entrypoints_are_v11():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"KIN {KIN_VERSION} (protocol {V11_PROTOCOL_VERSION})"
    assert KIN_VERSION == "1.1.0"
    assert kin.__version__ == KIN_VERSION
    assert PROTOCOL_VERSION == V11_PROTOCOL_VERSION

    metadata = tomllib.loads((NODE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == KIN_VERSION
    assert metadata["project"]["requires-python"] == ">=3.11,<3.13"
    assert all("==" in dependency for dependency in metadata["build-system"]["requires"])
    assert metadata["project"]["scripts"] == {
        "kin": "kin.cli:app",
        "kin-tui": "kin.tui.__main__:main",
    }
    assert all("==" in dependency for dependency in metadata["project"]["dependencies"])


def test_windows_installer_is_pinned_checksum_verifying_and_profile_preserving():
    installer = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "[string]$Version = '1.1.0'" in installer
    assert "Get-FileHash -Algorithm SHA256" in installer
    assert "Checksum mismatch" in installer
    assert "releases/download/v$Version" in installer
    assert '$manifestUri = "$releaseBase/SHA256SUMS"' in installer
    assert '$lockUri = "$releaseBase/$lockName"' in installer
    assert "--constraint $lockPath" in installer
    assert "Lock checksum mismatch" in installer
    assert "raw.githubusercontent.com" not in installer
    assert "kin doctor --plain" not in installer  # executed through the verified launcher, never shell text
    assert "& $launcher doctor --plain" in installer
    assert "& $launcher tui" in installer
    assert "cloudflared is not installed" in installer
    assert "supports Python 3.11 or 3.12" in installer
    assert "Remove-Item -LiteralPath $profileRoot" not in installer

    uninstaller = (ROOT / "uninstall.ps1").read_text(encoding="utf-8")
    assert "[switch]$RemoveProfiles" in uninstaller
    assert "if ($RemoveProfiles" in uninstaller
    assert "Profiles and queued relay data remain" in uninstaller


def test_release_build_requires_clean_signed_tag_and_writes_sha256_manifest():
    script = (ROOT / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
    assert "status --porcelain" in script
    assert "describe --tags --exact-match" in script
    assert "verify-tag" in script
    assert "Get-FileHash -Algorithm SHA256" in script
    assert "SHA256SUMS" in script


def test_release_document_set_and_ci_gate_matrix_exist():
    required = [
        ROOT / "CHANGELOG.md",
        ROOT / "SECURITY.md",
        ROOT / "docs" / "v1.1" / "INSTALL-WINDOWS.md",
        ROOT / "docs" / "v1.1" / "QUICKSTART.md",
        ROOT / "docs" / "v1.1" / "MIGRATION.md",
        ROOT / "docs" / "v1.1" / "PRIVACY.md",
        ROOT / "docs" / "v1.1" / "TROUBLESHOOTING.md",
        ROOT / "docs" / "v1.1" / "RELAY-OPERATOR.md",
        ROOT / "docs" / "v1.1" / "BACKUP-RECOVERY.md",
        ROOT / "docs" / "v1.1" / "TWO-LAPTOP-ACCEPTANCE.md",
        ROOT / "docs" / "v1.1" / "RELEASE-CHECKLIST.md",
        ROOT / "release" / "requirements-windows.lock",
    ]
    assert all(path.is_file() and path.stat().st_size > 100 for path in required)

    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for target in ("windows-latest", "ubuntu-latest", "macos-latest", "-m smoke", "python -m build"):
        assert target in workflow
