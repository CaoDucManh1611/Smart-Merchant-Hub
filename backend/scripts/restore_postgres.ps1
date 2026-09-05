param(
    [Parameter(Mandatory = $true)] [string]$BackupFile,
    [Parameter(Mandatory = $true)] [string]$TargetDatabaseUrl,
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore is destructive. Re-run with -ConfirmRestore after testing against a fresh staging database."
}
if (-not (Test-Path -LiteralPath $BackupFile -PathType Leaf)) {
    throw "Backup file was not found: $BackupFile"
}
if ($TargetDatabaseUrl -match "(?i)^sqlite") {
    throw "Refusing to restore to SQLite."
}
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
    throw "pg_restore was not found. Install PostgreSQL client tools on the deployment host."
}

& pg_restore --clean --if-exists --no-owner --no-privileges --dbname $TargetDatabaseUrl $BackupFile
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }
Write-Output "Restore completed. Run alembic upgrade head and application smoke tests before traffic is restored."

