param(
    [Parameter(Mandatory = $true)] [string]$BackupFile,
    [Parameter(Mandatory = $true)] [string]$StagingDatabaseUrl,
    [switch]$Overwrite,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backupVerifier = Join-Path $repoRoot "scripts\backup-verify.ps1"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python is required for the migration and smoke gates." }
if ($StagingDatabaseUrl -match "(?i)^sqlite") { throw "StagingDatabaseUrl must be PostgreSQL." }

Write-Host "== Verify backup archive ==" -ForegroundColor Cyan
& $backupVerifier -BackupFile $BackupFile -VerifyOnly

Write-Host "== Restore to isolated staging database ==" -ForegroundColor Cyan
$restoreArgs = @{ BackupFile = $BackupFile; RestoreDatabaseUrl = $StagingDatabaseUrl }
if ($Overwrite) { $restoreArgs.Overwrite = $true }
& $backupVerifier @restoreArgs

Push-Location (Join-Path $repoRoot "backend")
try {
    $previousDatabaseUrl = $env:DATABASE_URL
    $previousPythonPath = $env:PYTHONPATH
    $env:DATABASE_URL = $StagingDatabaseUrl
    $migrationDeps = Join-Path (Get-Location) ".migrationdeps"
    if (Test-Path -LiteralPath $migrationDeps) {
        $env:PYTHONPATH = if ($previousPythonPath) { "$migrationDeps;$previousPythonPath" } else { $migrationDeps }
    }
    Write-Host "== Alembic upgrade/current/check ==" -ForegroundColor Cyan
    & $python.Source -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic upgrade failed." }
    & $python.Source -m alembic current
    if ($LASTEXITCODE -ne 0) { throw "Alembic current failed." }
    & $python.Source -m alembic check
    if ($LASTEXITCODE -ne 0) { throw "Alembic drift check failed." }
    if (-not $SkipTests) {
        Write-Host "== Tenant isolation and webhook smoke tests ==" -ForegroundColor Cyan
        & $python.Source -m pytest -q tests/test_api_tenant_isolation.py tests/test_rag_tenant_isolation.py tests/test_webhook_oauth_security.py tests/test_unified_inbox_webhooks.py tests/test_zalo_webhook.py tests/test_instagram_webhook.py tests/test_tiktok_webhook.py
        if ($LASTEXITCODE -ne 0) { throw "Staging smoke tests failed." }
    }
}
finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $previousDatabaseUrl }
    if ($null -eq $previousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $previousPythonPath }
    Pop-Location
}

Write-Host "Staging migration/restore rehearsal passed." -ForegroundColor Green
