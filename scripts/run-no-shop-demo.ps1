param([switch]$SkipFrontend)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$qaScript = Join-Path $PSScriptRoot "no-shop-qa.ps1"

if ($SkipFrontend) {
    & $qaScript -SkipFrontend
}
else {
    & $qaScript
}
if ($LASTEXITCODE -ne 0) { throw "No-shop QA failed (exit code $LASTEXITCODE)." }

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonPrefix = @()
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { $pythonPrefix = @("-3.12") }
}
if (-not $python) { throw "Python 3.12 is required to run the RAG evaluation." }

Write-Host "== Deterministic RAG routing evaluation (no LLM calls) ==" -ForegroundColor Cyan
Push-Location $repoRoot
try {
    & $python.Source @pythonPrefix scripts/evaluate_rag_set.py
    if ($LASTEXITCODE -ne 0) { throw "RAG routing evaluation failed (exit code $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

Write-Host "No-shop demo checks passed. For manual RAG questions, follow docs/no-shop-rag-demo-scenario.md." -ForegroundColor Green
