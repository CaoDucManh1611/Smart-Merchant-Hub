# Reset database to the current 20-table schema.
# This is intentionally separate from normal app startup because it deletes data.

$ErrorActionPreference = "Stop"
$BackendPath = Join-Path $PSScriptRoot "backend"

Write-Host "Smart Merchant Hub - Reset database schema" -ForegroundColor Cyan
Write-Host "This will delete every table in PostgreSQL schema public." -ForegroundColor Red
$confirmation = Read-Host "Type RESET to continue"
if ($confirmation -ne "RESET") {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 1
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker Desktop was not found. Start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

Push-Location $PSScriptRoot
try {
    & docker compose up -d db
    if ($LASTEXITCODE -ne 0) {
        throw "Could not start PostgreSQL/pgvector."
    }
} finally {
    Pop-Location
}

$dbReady = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    $dbHealth = & docker inspect --format="{{.State.Health.Status}}" crm_chatbot_db 2>$null
    if ($dbHealth -eq "healthy") {
        $dbReady = $true
        break
    }
    Write-Host "Waiting for PostgreSQL ($attempt/30)..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
}

if (-not $dbReady) {
    Write-Host "PostgreSQL did not become ready. Check: docker compose logs db" -ForegroundColor Red
    exit 1
}

$envFile = Join-Path $BackendPath ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $BackendPath ".env.example") $envFile
}

Push-Location $BackendPath
try {
    pip install -r requirements.txt -q
    & python "scripts\reset_database_schema.py" --yes
    if ($LASTEXITCODE -ne 0) {
        throw "The database reset failed."
    }
} finally {
    Pop-Location
}

Write-Host "Done: the database now contains the current 20 application tables." -ForegroundColor Green
