param(
    [string]$Python = "python",
    [string]$OutputPath = ".artifacts/cp0-demo/inventory-lookup-demo.json"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$artifactRoot = Join-Path $repositoryRoot ".artifacts/cp0-demo"
$upstreamProcess = $null
$gatewayProcess = $null

foreach ($port in @(18080, 18081)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "CP0 fixture port $port is already in use."
    }
}

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

    & $Python (Join-Path $PSScriptRoot "run_cp0_demo.py") `
        --upstream-url "http://127.0.0.1:18081" `
        --gateway-url "http://127.0.0.1:18080" `
        --item "widget-cp0" `
        --output (Join-Path $repositoryRoot $OutputPath)
    if ($LASTEXITCODE -ne 0) {
        throw "CP0 canonical demo failed."
    }
} finally {
    foreach ($process in @($gatewayProcess, $upstreamProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }
}
