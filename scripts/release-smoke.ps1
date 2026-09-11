param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$FrontendUrl = "http://127.0.0.1:5173",
    [switch]$SkipHttp
)

$ErrorActionPreference = "Stop"

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            throw "HTTP $($response.StatusCode)"
        }
        Write-Host "  OK  $Name" -ForegroundColor Green
    }
    catch {
        throw "Release smoke check failed for $Name ($Url): $($_.Exception.Message)"
    }
}

Write-Host "Smart Merchant Hub release smoke check" -ForegroundColor Cyan
Write-Host "Only health/readiness endpoints are checked; secrets are never printed." -ForegroundColor Gray

if (-not $SkipHttp) {
    Test-Endpoint -Name "Backend health" -Url ($ApiBaseUrl.TrimEnd('/') + "/health")
    Test-Endpoint -Name "Frontend readiness" -Url ($FrontendUrl.TrimEnd('/') + "/")
}

$backendPath = Join-Path $PSScriptRoot "..\backend"
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    Push-Location $backendPath
    try {
        $alembic = Get-Command alembic -ErrorAction SilentlyContinue
        if ($alembic) {
            & $alembic.Source current
            if ($LASTEXITCODE -ne 0) { throw "Alembic current failed." }
            Write-Host "  OK  Alembic current" -ForegroundColor Green
        }
        else {
            Write-Warning "Alembic CLI is not available; skipped migration current check."
        }
        & $python.Source -m compileall -q app alembic
        if ($LASTEXITCODE -ne 0) { throw "Backend compile failed." }
        Write-Host "  OK  Backend compile" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Warning "Python is not available; skipped Alembic and backend compile checks."
}

$frontendPath = Join-Path $PSScriptRoot "..\frontend"
$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($npm) {
    Push-Location $frontendPath
    try {
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
        Write-Host "  OK  Frontend build" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
else {
    $viteCommand = Join-Path $frontendPath "node_modules\.bin\vite.cmd"
    if (Test-Path $viteCommand) {
        Push-Location $frontendPath
        try {
            & $viteCommand build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
            Write-Host "  OK  Frontend build (local Vite)" -ForegroundColor Green
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Warning "npm and a local Vite binary are not available; skipped frontend build."
    }
}

Write-Host "Release smoke checks completed." -ForegroundColor Green
