[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '1.1.0',
    [string]$Repository = '0xnotdev/kinto',
    [string]$WheelSha256 = '',
    [string]$LockSha256 = '',
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$wheelName = "kin_cli-$Version-py3-none-any.whl"
$releaseBase = "https://github.com/$Repository/releases/download/v$Version"
$wheelUri = "$releaseBase/$wheelName"
$lockName = 'requirements-windows.lock'
$lockUri = "$releaseBase/$lockName"
$manifestUri = "$releaseBase/SHA256SUMS"
$installRoot = Join-Path $env:LOCALAPPDATA 'KIN'
$versionRoot = Join-Path $installRoot $Version
$venvRoot = Join-Path $versionRoot 'venv'
$binRoot = Join-Path $installRoot 'bin'
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kin-install-" + [guid]::NewGuid())

function Invoke-KinDownload([string]$Uri, [string]$Destination) {
    Write-Host "Downloading $Uri"
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
}

try {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python 3.11 or newer is required. Install it from python.org, then rerun this script.' }
    $pythonVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ([version]$pythonVersion -lt [version]'3.11' -or [version]$pythonVersion -ge [version]'3.13') {
        throw "Python $pythonVersion found; KIN V1.1 supports Python 3.11 or 3.12."
    }

    New-Item -ItemType Directory -Force -Path $temporaryRoot, $versionRoot, $binRoot | Out-Null
    $wheelPath = Join-Path $temporaryRoot $wheelName
    $lockPath = Join-Path $temporaryRoot $lockName
    Invoke-KinDownload $wheelUri $wheelPath
    Invoke-KinDownload $lockUri $lockPath

    if (-not $WheelSha256 -or -not $LockSha256) {
        $manifestPath = Join-Path $temporaryRoot 'SHA256SUMS'
        Invoke-KinDownload $manifestUri $manifestPath
        if (-not $WheelSha256) {
            $manifestLine = Get-Content -LiteralPath $manifestPath | Where-Object { $_ -match "\s+$([regex]::Escape($wheelName))$" } | Select-Object -First 1
            if (-not $manifestLine) { throw "The release checksum manifest has no entry for $wheelName." }
            $WheelSha256 = ($manifestLine -split '\s+')[0]
        }
        if (-not $LockSha256) {
            $lockManifestLine = Get-Content -LiteralPath $manifestPath | Where-Object { $_ -match "\s+$([regex]::Escape($lockName))$" } | Select-Object -First 1
            if (-not $lockManifestLine) { throw "The release checksum manifest has no entry for $lockName." }
            $LockSha256 = ($lockManifestLine -split '\s+')[0]
        }
    }
    if ($WheelSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Expected wheel checksum is not a SHA-256 value.' }
    if ($LockSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Expected lock checksum is not a SHA-256 value.' }
    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $wheelPath).Hash
    if ($actualSha256 -ne $WheelSha256) { throw "Checksum mismatch. Expected $WheelSha256; received $actualSha256. Nothing was installed." }
    $actualLockSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $lockPath).Hash
    if ($actualLockSha256 -ne $LockSha256) { throw "Lock checksum mismatch. Expected $LockSha256; received $actualLockSha256. Nothing was installed." }

    if (Test-Path -LiteralPath $venvRoot) { Remove-Item -LiteralPath $venvRoot -Recurse -Force }
    & python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated KIN environment.' }
    $venvPython = Join-Path $venvRoot 'Scripts\python.exe'
    & $venvPython -m pip install --disable-pip-version-check --constraint $lockPath $wheelPath
    if ($LASTEXITCODE -ne 0) { throw 'KIN dependency installation failed.' }

    $launcher = Join-Path $binRoot 'kin.cmd'
    $launcherText = "@echo off`r`n`"$venvRoot\Scripts\kin.exe`" %*`r`n"
    [System.IO.File]::WriteAllText($launcher, $launcherText, [System.Text.UTF8Encoding]::new($false))
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (($userPath -split ';') -notcontains $binRoot) {
        [Environment]::SetEnvironmentVariable('Path', (($userPath.TrimEnd(';') + ';' + $binRoot).TrimStart(';')), 'User')
        Write-Host "Added $binRoot to your user PATH. Open a new terminal before typing kin."
    }

    Write-Host "KIN $Version installed in an isolated environment. Existing profiles and queued data were not changed."
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Write-Host 'Optional: cloudflared is not installed. It is needed only for automatic public tunnels; KIN also supports a manually managed HTTPS endpoint.'
    }
    & $launcher --version
    & $launcher doctor --plain
    if (-not $NoLaunch) { & $launcher tui }
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Recurse -Force }
}
