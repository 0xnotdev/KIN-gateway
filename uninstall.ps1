[CmdletBinding(SupportsShouldProcess)]
param([switch]$RemoveProfiles)

$ErrorActionPreference = 'Stop'
$installRoot = Join-Path $env:LOCALAPPDATA 'KIN'
$binRoot = Join-Path $installRoot 'bin'
$profileRoot = Join-Path $env:USERPROFILE '.kin'

if ($PSCmdlet.ShouldProcess($installRoot, 'Remove the KIN application')) {
    if (Test-Path -LiteralPath $installRoot) { Remove-Item -LiteralPath $installRoot -Recurse -Force }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $newPath = (($userPath -split ';' | Where-Object { $_ -and $_ -ne $binRoot }) -join ';')
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
}
if ($RemoveProfiles -and $PSCmdlet.ShouldProcess($profileRoot, 'Permanently remove identities, profiles, artifacts, and queued data')) {
    if (Test-Path -LiteralPath $profileRoot) { Remove-Item -LiteralPath $profileRoot -Recurse -Force }
} else {
    Write-Host "KIN was removed. Profiles and queued relay data remain at $profileRoot."
}
