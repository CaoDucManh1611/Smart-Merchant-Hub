param(
    [switch]$SkipCompose,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Get-Command python -ErrorAction SilentlyContinue
$pythonPrefix = @()
if (-not $pythonExecutable) {
    $pythonExecutable = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonExecutable) {
        $pythonPrefix = @("-3.12")
    }
}
if (-not $pythonExecutable) {
    throw "Python 3.12 is required. Install Python or make the 'python'/'py' command available."
}

function Invoke-Gate {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host "`n== $Name ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Gate failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Invoke-Python {
    param([string[]]$Arguments)
    & $pythonExecutable.Source @pythonPrefix @Arguments
}

Push-Location $repoRoot
try {
    Invoke-Gate "Git whitespace" { git diff --check }

    Push-Location backend
    try {
        # The local test image keeps migration-only packages in this folder;
        # prepend it once so direct Python/Alembic invocations use the same
        # environment as the migration gate.
        $migrationDeps = Join-Path (Get-Location) ".migrationdeps"
        if (Test-Path -LiteralPath $migrationDeps) {
            $env:PYTHONPATH = if ($env:PYTHONPATH) { "$migrationDeps;$env:PYTHONPATH" } else { $migrationDeps }
        }
        Invoke-Gate "Alembic upgrade" { Invoke-Python -Arguments @("-m", "alembic", "upgrade", "head") }
        Invoke-Gate "Alembic current" { Invoke-Python -Arguments @("-m", "alembic", "current") }
        Invoke-Gate "Alembic drift check" { Invoke-Python -Arguments @("-m", "alembic", "check") }
        Invoke-Gate "Backend compile" { Invoke-Python -Arguments @("-m", "compileall", "-q", "app", "alembic", "tests") }
        if (-not $SkipTests) {
            Invoke-Gate "Backend tests" { Invoke-Python -Arguments @("-m", "pytest", "-q") }
        }
    }
    finally {
        Pop-Location
    }

    Push-Location frontend
    try {
        Invoke-Gate "Frontend install" { npm ci }
        if (-not $SkipTests) {
            Invoke-Gate "Frontend tests" { npm test }
        }
        Invoke-Gate "Frontend build" { npm run build }
    }
    finally {
        Pop-Location
    }

    if (-not $SkipCompose) {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Write-Warning "Docker is not available; compose smoke was skipped. Re-run with Docker Desktop for the full gate."
        }
        else {
            $backendEnvPath = Join-Path $repoRoot "backend\.env"
            $createdBackendEnv = $false
            if (-not (Test-Path $backendEnvPath)) {
                @"
DATABASE_URL=postgresql+psycopg://ci_user:ci_password@db:5432/crm_chatbot
ENVIRONMENT=development
AUTH_SECRET=ci-only-auth-secret
CHANNEL_ENCRYPTION_KEY=ci-only-channel-key
RAG_AUTO_SEED_ENABLED=false
RAG_AUTO_REPLY_ENABLED=false
EMBEDDING_PROVIDER=local
CORS_ORIGINS=http://localhost:5173
ALLOWED_HOSTS=*
"@ | Set-Content -Path $backendEnvPath -Encoding utf8
                $createdBackendEnv = $true
            }

            $env:POSTGRES_DB = "crm_chatbot"
            $env:POSTGRES_USER = "ci_user"
            $env:POSTGRES_PASSWORD = "ci_password"
            $env:DATABASE_URL = "postgresql+psycopg://ci_user:ci_password@db:5432/crm_chatbot"
            try {
                Invoke-Gate "Compose config" { docker compose config --quiet }
                Invoke-Gate "Compose build and start" { docker compose up -d --build }

                $healthy = $false
                for ($attempt = 1; $attempt -le 30; $attempt++) {
                    $backendStatus = docker inspect --format '{{.State.Health.Status}}' crm_chatbot_backend 2>$null
                    $frontendStatus = docker inspect --format '{{.State.Health.Status}}' crm_chatbot_frontend 2>$null
                    if ($backendStatus -eq "healthy" -and $frontendStatus -eq "healthy") {
                        $healthy = $true
                        break
                    }
                    Start-Sleep -Seconds 5
                }
                if (-not $healthy) {
                    docker compose ps
                    docker compose logs --no-color db backend frontend
                    throw "Compose services did not become healthy within 150 seconds."
                }

                Invoke-Gate "Backend health" { curl.exe --fail --silent --show-error http://localhost:8000/health }
                Invoke-Gate "Backend detailed health" { curl.exe --fail --silent --show-error http://localhost:8000/health/details }
                Invoke-Gate "Backend API docs" { curl.exe --fail --silent --show-error http://localhost:8000/docs }
                Invoke-Gate "Frontend readiness" { curl.exe --fail --silent --show-error http://localhost:5173/ }
                Invoke-Gate "Compose status" { docker compose ps }
            }
            finally {
                docker compose down --volumes --remove-orphans
                if ($createdBackendEnv -and (Test-Path $backendEnvPath)) {
                    Remove-Item -LiteralPath $backendEnvPath -Force
                }
            }
        }
    }

    Write-Host "`nAll selected CI gates passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
