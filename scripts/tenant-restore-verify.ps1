param(
  [Parameter(Mandatory = $true)]
  [ValidateRange(1, 2147483647)]
  [int]$BusinessId,
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [string]$VerificationDatabaseUrl = $env:TENANT_VERIFY_DATABASE_URL,
  [string]$ManifestFile,
  [switch]$Overwrite
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
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Backup archive does not exist: $Path" }
  if ((Get-Item -LiteralPath $Path).Length -le 0) { throw "Backup archive is empty: $Path" }
}

if (-not $VerificationDatabaseUrl) { throw "TENANT_VERIFY_DATABASE_URL must point to a new verification database." }
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) { throw "pg_restore is required." }
Assert-Archive -Path $BackupFile

if ($ManifestFile) {
  if (-not (Test-Path -LiteralPath $ManifestFile -PathType Leaf)) { throw "Manifest file does not exist: $ManifestFile" }
  $manifest = Get-Content -LiteralPath $ManifestFile -Raw | ConvertFrom-Json
  if ([int]$manifest.business_id -ne $BusinessId -or [string]$manifest.schema -ne $schema) {
    throw "Backup manifest does not match BusinessId=$BusinessId."
  }
  $actualHash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualHash -ne [string]$manifest.sha256) { throw "Backup checksum does not match its manifest." }
}

$restoreArgs = @(
  "--exit-on-error",
  "--dbname=$VerificationDatabaseUrl",
  "--no-owner",
  "--no-privileges",
  "--schema=$schema"
)
if ($Overwrite) {
  $restoreArgs += @("--clean", "--if-exists")
} else {
  # No clean/drop flags are ever sent by default: verification is isolated and
  # cannot overwrite an existing schema accidentally.
}
Invoke-NativeChecked -Command "pg_restore" -Arguments ($restoreArgs + $BackupFile)
Invoke-NativeChecked -Command "pg_restore" -Arguments @("--exit-on-error", "--list", $BackupFile)

if (Get-Command psql -ErrorAction SilentlyContinue) {
  $tableCount = (& psql "--dbname=$VerificationDatabaseUrl" "--tuples-only" "--no-align" "--command=SELECT count(*) FROM information_schema.tables WHERE table_schema='$schema';")
  if ($LASTEXITCODE -ne 0 -or [int]($tableCount.Trim()) -le 0) { throw "Restored schema $schema has no tables." }
}
Write-Host "Tenant restore verified in $VerificationDatabaseUrl (schema=$schema). Overwrite=$Overwrite"
