param(
  [Parameter(Mandatory = $true)]
  [ValidateRange(1, 2147483647)]
  [int]$BusinessId,
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [string]$DatabaseUrl = $env:TENANT_DATABASE_URL,
  [string]$ManifestFile
)

$ErrorActionPreference = "Stop"
$schema = "shop_$BusinessId"

function Invoke-NativeChecked {
  param([Parameter(Mandatory = $true)] [string]$Command, [Parameter(Mandatory = $true)] [string[]]$Arguments)
  & $Command @Arguments
  $code = $LASTEXITCODE
  if ($code -ne 0) { throw "$Command failed with exit code $code." }
}

function Assert-Archive {
  param([Parameter(Mandatory = $true)] [string]$Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Backup archive was not created: $Path" }
  if ((Get-Item -LiteralPath $Path).Length -le 0) { throw "Backup archive is empty: $Path" }
}

if (-not $DatabaseUrl) { throw "TENANT_DATABASE_URL must be supplied by the secret manager or protected environment." }
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) { throw "pg_dump is required." }
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) { throw "pg_restore is required." }

$dumpVersion = (& pg_dump --version 2>$null)
$restoreVersion = (& pg_restore --version 2>$null)
if ($dumpVersion -match "(\d+)") { $dumpMajor = [int]$Matches[1] } else { throw "Unable to determine pg_dump version." }
if ($restoreVersion -match "(\d+)") { $restoreMajor = [int]$Matches[1] } else { throw "Unable to determine pg_restore version." }
if ($dumpMajor -ne $restoreMajor) { throw "pg_dump/pg_restore major versions must match ($dumpMajor vs $restoreMajor)." }

Invoke-NativeChecked -Command "pg_dump" -Arguments @(
  "--dbname=$DatabaseUrl",
  "--schema=$schema",
  "--format=custom",
  "--file=$BackupFile",
  "--no-owner",
  "--no-privileges"
)
Assert-Archive -Path $BackupFile
Invoke-NativeChecked -Command "pg_restore" -Arguments @("--exit-on-error", "--list", $BackupFile)

if (-not $ManifestFile) { $ManifestFile = "$BackupFile.manifest.json" }
$hash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
  created_at = [DateTime]::UtcNow.ToString("o")
  backup_type = "tenant"
  business_id = $BusinessId
  schema = $schema
  client_major_version = $dumpMajor
  archive = (Resolve-Path -LiteralPath $BackupFile).Path
  sha256 = $hash
  alembic_revision = "unknown"
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestFile -Encoding UTF8
Write-Host "Tenant backup created and verified: $BackupFile (schema=$schema)"
