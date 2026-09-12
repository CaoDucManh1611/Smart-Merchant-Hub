param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [switch]$VerifyOnly,
  [string]$RestoreDatabaseUrl,
  [switch]$Overwrite
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
  throw "pg_restore is required. Install PostgreSQL client tools on the backup runner."
}

if ($VerifyOnly) {
  if ($RestoreDatabaseUrl) {
    throw "VerifyOnly cannot be combined with RestoreDatabaseUrl."
  }
  & pg_restore --list $BackupFile | Out-Null
  Write-Host "Backup archive is readable: $BackupFile"
  exit 0
}

if ($RestoreDatabaseUrl) {
  # Restore is intentionally opt-in and does not clean an existing database
  # unless the operator explicitly supplies -Overwrite. This makes restore
  # rehearsals safe for an isolated target while still supporting a planned
  # replacement database during an approved maintenance window.
  $restoreArgs = @(
    "--dbname=$RestoreDatabaseUrl",
    "--no-owner",
    "--no-privileges"
  )
  if ($Overwrite) {
    $restoreArgs += @("--clean", "--if-exists")
  }
  & pg_restore @restoreArgs $BackupFile
  & pg_restore --list $BackupFile | Out-Null
  Write-Host "Backup restored and verified. Overwrite=$Overwrite"
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
