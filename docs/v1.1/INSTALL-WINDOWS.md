# Install KIN V1.1 on Windows

Prerequisites: Windows 10/11, PowerShell 5.1+, Python 3.11 or 3.12, internet access, and
Windows Credential Manager. `cloudflared` is optional and only needed for the
automatic tunnel mode.

## Recommended pinned installer

First verify the release tag in a Git client with your trusted release key:

```powershell
git clone https://github.com/0xnotdev/kinto.git
cd kinto
git verify-tag v1.1.0
git checkout v1.1.0
Get-Content .\install.ps1
.\install.ps1
```

The script downloads `kin_cli-1.1.0-py3-none-any.whl`, the exact Windows runtime
constraints file, and `SHA256SUMS` from the GitHub release attached to the
verified signed tag. It verifies both artifacts, refuses any mismatch, and
installs the constrained dependency set into an isolated
per-user virtual environment, adds a small `kin.cmd` launcher to the user PATH,
runs `kin doctor`, and launches First Flight. It never installs `cloudflared` or
changes unrelated Python environments.

## Inspectable alternatives

Download the wheel, `requirements-windows.lock`, and `SHA256SUMS` from the GitHub v1.1.0 release, compare with
`Get-FileHash -Algorithm SHA256`, then use either:

```powershell
pipx install .\kin_cli-1.1.0-py3-none-any.whl
```

or pass the verified hash to the inspected installer:

```powershell
.\install.ps1 -WheelSha256 '<wheel hash>' -LockSha256 '<lock hash>'
```

## Upgrade and uninstall

Rerun a newer signed installer. It installs beside the old application and
switches only the launcher after verification; profiles and queued data remain
under `%USERPROFILE%\.kin`. Run `kin migrate --dry-run` and then `kin migrate`
for a legacy profile.

`uninstall.ps1` removes application files but preserves profiles by default.
`uninstall.ps1 -RemoveProfiles` is intentionally destructive and prompts before
removing identities, history, artifacts, and queued data.
