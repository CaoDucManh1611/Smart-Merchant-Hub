param([switch]$SkipFrontend)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $repoRoot "backend"
$frontendPath = Join-Path $repoRoot "frontend"

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonPrefix = @()
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { $pythonPrefix = @("-3.12") }
}
if (-not $python) { throw "Python 3.12 is required for the no-shop QA suite." }

$environmentNames = @(
    "RUN_POSTGRES_TESTS", "ENVIRONMENT", "DATABASE_URL", "PLATFORM_DATABASE_URL", "TENANT_DATABASE_URL",
    "SECRET_MANAGER_MODE", "SECRET_MANAGER_FILE", "OTP_DELIVERY_MODE", "OTP_DELIVERY_FALLBACK", "RAG_AUTO_REPLY_ENABLED",
    "RAG_AUTO_SEED_ENABLED", "GEMINI_API_KEY", "GEMINI_API_KEYS", "LLM_API_KEY", "LLM_API_KEYS",
    "GROQ_API_KEY", "GROQ_API_KEYS", "EMBEDDING_API_KEY", "EMBEDDING_API_KEYS", "FACEBOOK_PAGE_ACCESS_TOKEN",
    "FACEBOOK_VERIFY_TOKEN", "INSTAGRAM_ACCESS_TOKEN", "ZALO_PERSONAL_BRIDGE_KEY", "META_APP_ID",
    "META_APP_SECRET", "TIKTOK_APP_KEY", "TIKTOK_APP_SECRET", "SERVER_CONNECTOR_AGENT_TOKEN",
    "OTP_SMTP_PASSWORD", "OTP_TWILIO_AUTH_TOKEN", "CHANNEL_ENCRYPTION_KEY", "CHANNEL_ROUTE_SECRET", "AUTH_SECRET"
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    # Backend conftest routes every test to isolated SQLite; these switches
    # also prevent tests from using real provider credentials or delivery paths.
    $env:RUN_POSTGRES_TESTS = "0"
    $env:ENVIRONMENT = "test"
    $env:DATABASE_URL = "sqlite:///./.pytest_tmp/no-shop-qa.db"
    $env:PLATFORM_DATABASE_URL = "sqlite:///./.pytest_tmp/no-shop-platform.db"
    $env:TENANT_DATABASE_URL = "sqlite:///./.pytest_tmp/no-shop-tenant.db"
    $env:SECRET_MANAGER_MODE = "disabled"
    $env:OTP_DELIVERY_MODE = "disabled"
    $env:OTP_DELIVERY_FALLBACK = "disabled"
    $env:RAG_AUTO_REPLY_ENABLED = "false"
    $env:RAG_AUTO_SEED_ENABLED = "false"
    foreach ($name in $environmentNames | Where-Object { $_ -match "KEY|TOKEN|SECRET|PASSWORD" }) {
        [Environment]::SetEnvironmentVariable($name, "", "Process")
    }
    $env:AUTH_SECRET = "no-shop-qa-only-auth-secret"

    Write-Host "== Backend no-shop suite: isolated tenant, connectors, RFM, recommendations, RAG and automation ==" -ForegroundColor Cyan
    Push-Location $backendPath
    try {
        & $python.Source @pythonPrefix -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "Backend no-shop suite failed (exit code $LASTEXITCODE)." }
    }
    finally {
        Pop-Location
    }

    if (-not $SkipFrontend) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
        if (-not $npm) { throw "npm is required for frontend QA; install Node.js or use -SkipFrontend." }
        if (-not (Test-Path -LiteralPath (Join-Path $frontendPath "node_modules"))) {
            throw "Frontend dependencies are missing. Run 'npm ci' in frontend, then rerun this suite."
        }

        Push-Location $frontendPath
        try {
            Write-Host "== Frontend tests ==" -ForegroundColor Cyan
            & $npm.Source test
            if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed (exit code $LASTEXITCODE)." }

            Write-Host "== Frontend production build ==" -ForegroundColor Cyan
            & $npm.Source run build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed (exit code $LASTEXITCODE)." }
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "No-shop QA passed. No real shop login, provider API, production database, or Docker volume was used." -ForegroundColor Green
}
finally {
    foreach ($name in $environmentNames) {
        $value = $previousEnvironment[$name]
        if ($null -eq $value) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}
