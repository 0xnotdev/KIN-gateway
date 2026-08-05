[CmdletBinding()]
param([string]$Version = '1.1.0')

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$releaseRoot = Join-Path $repoRoot 'release'
$nodeRoot = Join-Path $repoRoot 'kin-node'
$relayRoot = Join-Path $repoRoot 'kin-relay'

if ((git -C $repoRoot status --porcelain)) { throw 'Release builds require a clean checkout.' }
$tag = git -C $repoRoot describe --tags --exact-match 2>$null
if ($tag -ne "v$Version") { throw "Checkout must be exactly at tag v$Version." }
git -C $repoRoot verify-tag $tag
if ($LASTEXITCODE -ne 0) { throw "Tag $tag is not signed by a trusted release key." }

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
python -m build --outdir $releaseRoot $nodeRoot
python -m build --outdir $releaseRoot $relayRoot
if ($LASTEXITCODE -ne 0) { throw 'Package build failed.' }

$artifacts = Get-ChildItem -LiteralPath $releaseRoot -File | Where-Object { $_.Name -ne 'SHA256SUMS' } | Sort-Object Name
$lines = foreach ($artifact in $artifacts) {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName).Hash.ToLowerInvariant()
    "$hash  $($artifact.Name)"
}
[System.IO.File]::WriteAllLines((Join-Path $releaseRoot 'SHA256SUMS'), $lines, [System.Text.UTF8Encoding]::new($false))
Write-Host 'Release artifacts built from a clean, signed tag. Upload every file in release/ to the matching GitHub release.'
