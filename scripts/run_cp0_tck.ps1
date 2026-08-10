param(
    [Parameter(Mandatory = $true)]
    [string]$TckPath,
    [string]$Python = "python",
    [string]$ReportDirectory = ".artifacts/cp0-tck/supported-profile"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$resolvedTckPath = (Resolve-Path -LiteralPath $TckPath).Path
$resolvedReportDirectory = Join-Path $repositoryRoot $ReportDirectory
$artifactRoot = Split-Path -Parent $resolvedReportDirectory
$upstreamProcess = $null
$gatewayProcess = $null
$expectedCommit = "5996b79f9cefa6fc390980e383e358a66fb9e49e"

if ((git -C $resolvedTckPath rev-parse HEAD) -ne $expectedCommit) {
    throw "TCK checkout is not at the pinned CP0 commit $expectedCommit."
}
if (Test-Path -LiteralPath $resolvedReportDirectory) {
    throw "Refusing to overwrite TCK report directory: $resolvedReportDirectory"
}
foreach ($port in @(18080, 18081)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "CP0 fixture port $port is already in use."
    }
}

uv sync --project $resolvedTckPath --python 3.11
if ($LASTEXITCODE -ne 0) {
    throw "Pinned TCK environment setup failed."
}
$tckPython = Join-Path $resolvedTckPath ".venv/Scripts/python.exe"
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

try {
    $upstreamProcess = Start-Process -FilePath $Python -ArgumentList @(
        "-m", "uvicorn", "tests.contract.cp0_live_fixture:upstream_app",
        "--host", "127.0.0.1", "--port", "18081", "--log-level", "warning"
    ) -WorkingDirectory $repositoryRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $artifactRoot "upstream.out.log") `
        -RedirectStandardError (Join-Path $artifactRoot "upstream.err.log") `
        -PassThru

    $gatewayProcess = Start-Process -FilePath $Python -ArgumentList @(
        "-m", "uvicorn", "tests.contract.cp0_live_fixture:gateway_app",
        "--host", "127.0.0.1", "--port", "18080", "--log-level", "warning"
    ) -WorkingDirectory $repositoryRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $artifactRoot "gateway.out.log") `
        -RedirectStandardError (Join-Path $artifactRoot "gateway.err.log") `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                -Uri "http://127.0.0.1:18080/.well-known/agent-card.json" `
                -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) {
        throw "CP0 live fixture did not become ready."
    }

    & $Python (Join-Path $PSScriptRoot "verify_tck_manifest.py") `
        --tck-path $resolvedTckPath `
        --tck-python $tckPython
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned TCK manifest verification failed."
    }

    & $Python (Join-Path $PSScriptRoot "run_cp0_tck_subset.py") `
        --tck-path $resolvedTckPath `
        --tck-python $tckPython `
        --sut-host "http://127.0.0.1:18080" `
        --report-directory $resolvedReportDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Supported CP0 TCK profile failed."
    }
} finally {
    foreach ($process in @($gatewayProcess, $upstreamProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }
}
