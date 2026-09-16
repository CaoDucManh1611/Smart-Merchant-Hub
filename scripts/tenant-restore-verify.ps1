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

function Get-TableChecksums {
  param(
    [Parameter(Mandatory = $true)] [string]$Url,
    [Parameter(Mandatory = $true)] [string]$SchemaName
  )

  $names = (& psql "--dbname=$Url" "--tuples-only" "--no-align" "--command=SELECT table_name FROM information_schema.tables WHERE table_schema='$SchemaName' ORDER BY table_name;")
  if ($LASTEXITCODE -ne 0) { throw "Unable to list tables in tenant schema $SchemaName." }
  $checksums = [ordered]@{}
  foreach ($rawName in ($names -split "`r?`n")) {
    $tableName = $rawName.Trim()
    if (-not $tableName) { continue }
    $qualified = '"' + $SchemaName.Replace('"', '""') + '"."' + $tableName.Replace('"', '""') + '"'
    $sql = "SELECT md5(COALESCE(string_agg(md5(row_to_json(t)::text), '' ORDER BY row_to_json(t)::text), '')) FROM $qualified AS t;"
    $checksum = (& psql "--dbname=$Url" "--tuples-only" "--no-align" "--command=$sql")
    if ($LASTEXITCODE -ne 0 -or -not $checksum.Trim()) { throw "Unable to checksum tenant table $tableName." }
    $checksums[$tableName] = $checksum.Trim()
  }
  if ($checksums.Count -le 0) { throw "Tenant schema $SchemaName has no tables." }
  return $checksums
}

if (-not $VerificationDatabaseUrl) { throw "TENANT_VERIFY_DATABASE_URL must point to a new verification database." }
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) { throw "pg_restore is required." }
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) { throw "psql is required." }
Assert-Archive -Path $BackupFile

if (-not $ManifestFile) { throw "ManifestFile is required for a verified tenant restore." }
if (-not (Test-Path -LiteralPath $ManifestFile -PathType Leaf)) { throw "Manifest file does not exist: $ManifestFile" }
$manifest = Get-Content -LiteralPath $ManifestFile -Raw | ConvertFrom-Json
if ([int]$manifest.business_id -ne $BusinessId -or [string]$manifest.schema -ne $schema) {
  throw "Backup manifest does not match BusinessId=$BusinessId."
}
$actualHash = (Get-FileHash -LiteralPath $BackupFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne [string]$manifest.sha256) { throw "Backup checksum does not match its manifest." }

$serverVersionNum = (& psql "--dbname=$VerificationDatabaseUrl" "--tuples-only" "--no-align" "--command=SHOW server_version_num;")
if ($LASTEXITCODE -ne 0 -or -not ($serverVersionNum.Trim() -match '^\d+$')) { throw "Unable to determine verification server version." }
$serverMajor = [int][Math]::Floor(([int]$serverVersionNum.Trim()) / 10000)
if ($serverMajor -ne [int]$manifest.server_major_version) { throw "Verification server major version does not match the backup manifest." }

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

$tableCount = (& psql "--dbname=$VerificationDatabaseUrl" "--tuples-only" "--no-align" "--command=SELECT count(*) FROM information_schema.tables WHERE table_schema='$schema';")
if ($LASTEXITCODE -ne 0 -or [int]($tableCount.Trim()) -ne [int]$manifest.table_count) { throw "Restored schema table_count does not match the backup manifest." }
$expectedChecksums = @{}
if (-not $manifest.table_checksums) { throw "Backup manifest is missing table_checksums." }
foreach ($property in $manifest.table_checksums.PSObject.Properties) {
  $expectedChecksums[[string]$property.Name] = [string]$property.Value
}
$actualChecksums = Get-TableChecksums -Url $VerificationDatabaseUrl -SchemaName $schema
if ($actualChecksums.Count -ne $expectedChecksums.Count) { throw "Restored schema table checksum set does not match the backup manifest." }
foreach ($tableName in $expectedChecksums.Keys) {
  if (-not $actualChecksums.Contains($tableName) -or $actualChecksums[$tableName] -ne $expectedChecksums[$tableName]) {
    throw "Restored tenant table checksum does not match: $tableName."
  }
}
$alembicRevision = (& psql "--dbname=$VerificationDatabaseUrl" "--tuples-only" "--no-align" "--command=SELECT version_num FROM `"$schema`".alembic_version;")
if ($LASTEXITCODE -ne 0 -or $alembicRevision.Trim() -ne [string]$manifest.alembic_revision) { throw "Restored tenant Alembic revision does not match the backup manifest." }
Write-Host "Tenant restore verified in $VerificationDatabaseUrl (schema=$schema). Overwrite=$Overwrite"
