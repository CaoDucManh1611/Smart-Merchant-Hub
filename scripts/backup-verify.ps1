param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [switch]$VerifyOnly,
  [string]$RestoreDatabaseUrl,
  [switch]$Overwrite
)

$ErrorActionPreference = "Stop"

function Invoke-NativeChecked {
  param(
    [Parameter(Mandatory = $true)] [string]$Command,
    [Parameter(Mandatory = $true)] [string[]]$Arguments
  )

  & $Command @Arguments
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "$Command failed with exit code $exitCode."
  }
}

function Assert-Archive {
  param([Parameter(Mandatory = $true)] [string]$Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Backup archive was not created: $Path"
  }
  $length = (Get-Item -LiteralPath $Path).Length
  if ($length -le 0) {
    throw "Backup archive is empty: $Path"
  }
}

if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
  throw "pg_restore is required. Install PostgreSQL client tools on the backup runner."
}

if ($VerifyOnly) {
  if ($RestoreDatabaseUrl) {
    throw "VerifyOnly cannot be combined with RestoreDatabaseUrl."
  }
  Invoke-NativeChecked -Command "pg_restore" -Arguments @("--list", $BackupFile) | Out-Null
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
  Invoke-NativeChecked -Command "pg_restore" -Arguments ($restoreArgs + $BackupFile)
  Assert-Archive -Path $BackupFile
  Assert-Archive -Path $BackupFile
  Invoke-NativeChecked -Command "pg_restore" -Arguments @("--list", $BackupFile) | Out-Null
  Write-Host "Backup restored and verified. Overwrite=$Overwrite"
  exit 0
}

if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
  throw "pg_dump is required. Install PostgreSQL client tools on the backup runner."
}
if (-not $env:DATABASE_URL) {
  throw "DATABASE_URL must be supplied by the secret manager or protected environment."
}

Invoke-NativeChecked -Command "pg_dump" -Arguments @(
  "--dbname=$($env:DATABASE_URL)",
  "--format=custom",
  "--file=$BackupFile",
  "--no-owner",
  "--no-privileges"
)
Assert-Archive -Path $BackupFile
Invoke-NativeChecked -Command "pg_restore" -Arguments @("--list", $BackupFile) | Out-Null
Write-Host "Backup created and verified: $BackupFile"
