[CmdletBinding()]
param(
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"
$pytestTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("smh-pytest-" + [guid]::NewGuid().ToString("N"))

function Invoke-ReleaseStep {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [scriptblock]$Command
    )

    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Backend virtual environment is missing: $pythonPath"
}

Push-Location $backendRoot
try {
    # A unique OS temp directory avoids OneDrive/antivirus locks when pytest
    # removes a reused repository-local basetemp on Windows.
    Invoke-ReleaseStep "Backend regression" {
        & $pythonPath -m pytest -q "--basetemp=$pytestTemp" -p no:cacheprovider
    }
    Invoke-ReleaseStep "Python compile check" { & $pythonPath -m compileall -q app tests }
}
finally {
    Pop-Location
}

Push-Location $frontendRoot
try {
    Invoke-ReleaseStep "Frontend behavior regression" { & npm.cmd test }
    Invoke-ReleaseStep "Frontend production build" { & npm.cmd run build }
}
finally {
    Pop-Location
}

Push-Location $projectRoot
try {
    Invoke-ReleaseStep "Git working-tree whitespace check" { & git diff --check }
    Invoke-ReleaseStep "Git staged whitespace check" { & git diff --cached --check }
}
finally {
    Pop-Location
}

if (-not $SkipDocker) {
    $containers = @(
        "crm_chatbot_db",
        "crm_chatbot_redis",
        "crm_chatbot_backend",
        "crm_chatbot_worker",
        "crm_chatbot_frontend"
    )
    foreach ($container in $containers) {
        $state = & docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}' $container 2>$null
        if ($LASTEXITCODE -ne 0 -or $state.Trim() -ne "running/healthy") {
            throw "Container $container is not running/healthy (state: $state)."
        }
    }
    Write-Host "==> Docker runtime: 5/5 running and healthy"
}

Write-Host "Release audit passed."
