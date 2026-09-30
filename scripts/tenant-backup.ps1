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

if (-not $DatabaseUrl) { throw "TENANT_DATABASE_URL must be supplied by the secret manager or protected environment." }
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) { throw "pg_dump is required." }
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) { throw "pg_restore is required." }
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) { throw "psql is required." }

$dumpVersion = (& pg_dump --version 2>$null)
$restoreVersion = (& pg_restore --version 2>$null)
if ($dumpVersion -match "(\d+)") { $dumpMajor = [int]$Matches[1] } else { throw "Unable to determine pg_dump version." }
if ($restoreVersion -match "(\d+)") { $restoreMajor = [int]$Matches[1] } else { throw "Unable to determine pg_restore version." }
if ($dumpMajor -ne $restoreMajor) { throw "pg_dump/pg_restore major versions must match ($dumpMajor vs $restoreMajor)." }

$serverVersionNum = (& psql "--dbname=$DatabaseUrl" "--tuples-only" "--no-align" "--command=SHOW server_version_num;")
if ($LASTEXITCODE -ne 0 -or -not ($serverVersionNum.Trim() -match '^\d+$')) { throw "Unable to determine PostgreSQL server version." }
$serverMajor = [int][Math]::Floor(([int]$serverVersionNum.Trim()) / 10000)
if ($serverMajor -ne $dumpMajor) { throw "pg_dump major version must match the server ($dumpMajor vs $serverMajor)." }
$alembicRevision = (& psql "--dbname=$DatabaseUrl" "--tuples-only" "--no-align" "--command=SELECT version_num FROM `"$schema`".alembic_version;")
if ($LASTEXITCODE -ne 0 -or -not $alembicRevision.Trim()) { throw "Unable to determine tenant Alembic revision." }
$tableCount = (& psql "--dbname=$DatabaseUrl" "--tuples-only" "--no-align" "--command=SELECT count(*) FROM information_schema.tables WHERE table_schema='$schema';")
if ($LASTEXITCODE -ne 0 -or [int]($tableCount.Trim()) -le 0) { throw "Tenant schema $schema has no tables." }
$tableChecksums = Get-TableChecksums -Url $DatabaseUrl -SchemaName $schema

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
  server_major_version = $serverMajor
  archive = (Resolve-Path -LiteralPath $BackupFile).Path
  sha256 = $hash
  alembic_revision = $alembicRevision.Trim()
  table_count = [int]$tableCount.Trim()
  table_checksums = $tableChecksums
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestFile -Encoding UTF8
Write-Host "Tenant backup created and verified: $BackupFile (schema=$schema)"
