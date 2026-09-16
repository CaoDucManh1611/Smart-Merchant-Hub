param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [switch]$VerifyOnly,
  [string]$RestoreDatabaseUrl,
  [string]$ManifestFile,
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
  if (-not $ManifestFile) { throw "ManifestFile is required for a verified platform restore." }
  if (-not (Test-Path -LiteralPath $ManifestFile -PathType Leaf)) { throw "Manifest file does not exist: $ManifestFile" }
  Assert-Archive -Path $BackupFile
  $manifest = Get-Content -LiteralPath $ManifestFile -Raw | ConvertFrom-Json
  if ([string]$manifest.backup_type -ne "platform") { throw "Backup manifest is not a platform archive." }
  $actualHash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualHash -ne [string]$manifest.sha256) { throw "Backup checksum does not match its manifest." }
  if (-not (Get-Command psql -ErrorAction SilentlyContinue)) { throw "psql is required to verify a platform restore." }
  Invoke-NativeChecked -Command "pg_restore" -Arguments ($restoreArgs + $BackupFile)
  Invoke-NativeChecked -Command "pg_restore" -Arguments @("--list", $BackupFile) | Out-Null
  $serverVersionNum = (& psql "--dbname=$RestoreDatabaseUrl" "--tuples-only" "--no-align" "--command=SHOW server_version_num;")
  if ($LASTEXITCODE -ne 0 -or -not ($serverVersionNum.Trim() -match '^\d+$')) { throw "Unable to determine restored PostgreSQL server version." }
  $serverMajor = [int][Math]::Floor(([int]$serverVersionNum.Trim()) / 10000)
  if ($serverMajor -ne [int]$manifest.server_major_version) { throw "Restored server major version does not match the backup manifest." }
  $alembicRevision = (& psql "--dbname=$RestoreDatabaseUrl" "--tuples-only" "--no-align" "--command=SELECT version_num FROM alembic_version;")
  if ($LASTEXITCODE -ne 0 -or $alembicRevision.Trim() -ne [string]$manifest.alembic_revision) { throw "Restored platform Alembic revision does not match the backup manifest." }
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
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
  throw "psql is required to create a verified backup manifest."
}
$serverVersionNum = (& psql "--dbname=$($env:DATABASE_URL)" "--tuples-only" "--no-align" "--command=SHOW server_version_num;")
if ($LASTEXITCODE -ne 0 -or -not ($serverVersionNum.Trim() -match '^\d+$')) { throw "Unable to determine PostgreSQL server version." }
$serverMajor = [int][Math]::Floor(([int]$serverVersionNum.Trim()) / 10000)
$alembicRevision = (& psql "--dbname=$($env:DATABASE_URL)" "--tuples-only" "--no-align" "--command=SELECT version_num FROM alembic_version;")
if ($LASTEXITCODE -ne 0 -or -not $alembicRevision.Trim()) { throw "Unable to determine platform Alembic revision." }
if (-not $ManifestFile) { $ManifestFile = "$BackupFile.manifest.json" }
$manifest = [ordered]@{
  created_at = [DateTime]::UtcNow.ToString("o")
  backup_type = "platform"
  server_major_version = $serverMajor
  alembic_revision = $alembicRevision.Trim()
  archive = (Resolve-Path -LiteralPath $BackupFile).Path
  sha256 = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestFile -Encoding UTF8
Write-Host "Backup created and verified: $BackupFile"
