param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
  throw "pg_restore is required. Install PostgreSQL client tools on the backup runner."
}

if ($VerifyOnly) {
  & pg_restore --list $BackupFile | Out-Null
  Write-Host "Backup archive is readable: $BackupFile"
  exit 0
}

if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
  throw "pg_dump is required. Install PostgreSQL client tools on the backup runner."
}
if (-not $env:DATABASE_URL) {
  throw "DATABASE_URL must be supplied by the secret manager or protected environment."
}

& pg_dump --dbname=$env:DATABASE_URL --format=custom --file=$BackupFile --no-owner --no-privileges
& pg_restore --list $BackupFile | Out-Null
Write-Host "Backup created and verified: $BackupFile"
