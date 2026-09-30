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
    Test-Endpoint -Name "Backend detailed health" -Url ($ApiBaseUrl.TrimEnd('/') + "/health/details")
    Test-Endpoint -Name "Backend API docs" -Url ($ApiBaseUrl.TrimEnd('/') + "/docs")
    Test-Endpoint -Name "Frontend readiness" -Url ($FrontendUrl.TrimEnd('/') + "/")
}

$backendPath = Join-Path $PSScriptRoot "..\backend"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Python is required for the release gate." }
$alembic = Get-Command alembic -ErrorAction SilentlyContinue
if (-not $alembic) { throw "Alembic CLI is required for the release gate." }
Push-Location $backendPath
try {
    & $alembic.Source -c alembic-platform.ini current
    if ($LASTEXITCODE -ne 0) { throw "Platform Alembic current failed." }
    & $alembic.Source -c alembic-platform.ini check
    if ($LASTEXITCODE -ne 0) { throw "Platform Alembic drift check failed." }
    & $alembic.Source -c alembic-tenant.ini heads
    if ($LASTEXITCODE -ne 0) { throw "Tenant Alembic head check failed." }
    & $python.Source -m compileall -q app alembic alembic_platform alembic_tenant tests
    if ($LASTEXITCODE -ne 0) { throw "Backend compile failed." }
    & $python.Source -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
    $previousPostgresMode = $env:RUN_POSTGRES_TESTS
    try {
        $env:RUN_POSTGRES_TESTS = "1"
        & $python.Source -m pytest -q tests/test_database_boundaries.py tests/test_tenant_migration_runner.py
        if ($LASTEXITCODE -ne 0) { throw "PostgreSQL tenant isolation tests failed." }
    }
    finally {
        $env:RUN_POSTGRES_TESTS = $previousPostgresMode
    }
    Write-Host "  OK  Backend migrations, compile and tests" -ForegroundColor Green
}
finally {
    Pop-Location
}

$frontendPath = Join-Path $PSScriptRoot "..\frontend"
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) { throw "npm is required for the release gate." }
Push-Location $frontendPath
try {
    & $npm.Source test
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }
    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    Write-Host "  OK  Frontend tests and build" -ForegroundColor Green
}
finally {
    Pop-Location
}

Write-Host "Release smoke checks completed." -ForegroundColor Green
