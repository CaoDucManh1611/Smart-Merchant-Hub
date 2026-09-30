param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$OutputDirectory = "backups"
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    throw "DATABASE_URL is required. Do not put credentials in this script or commit them."
}
if ($DatabaseUrl -match "(?i)^sqlite") {
    throw "Refusing to back up SQLite. This P0 runbook requires PostgreSQL."
}
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    throw "pg_dump was not found. Install PostgreSQL client tools on the deployment host."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = Join-Path $OutputDirectory "crm_chatbot_$stamp.dump"

& pg_dump --format=custom --no-owner --no-privileges --file $backupFile $DatabaseUrl
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }

& pg_restore --list $backupFile | Out-File -Encoding utf8 "$backupFile.list"
if ($LASTEXITCODE -ne 0) { throw "pg_restore validation failed with exit code $LASTEXITCODE" }
Write-Output "Backup created and catalog validated: $backupFile"

