$ErrorActionPreference = "Stop"
$backendJson = docker exec crm_chatbot_backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
if ($LASTEXITCODE -ne 0) { throw "Backend unavailable" }
$backendState = $backendJson | ConvertFrom-Json
$workerRevision = docker exec crm_chatbot_worker cat /tmp/crm-worker-revision
if ($LASTEXITCODE -ne 0) { throw "Worker revision unavailable" }
if ($backendState.loaded_revision -ne $backendState.source_revision -or $workerRevision.Trim() -ne $backendState.loaded_revision) {
    throw "Backend/worker/source revisions differ. Restart both backend and worker before acceptance."
}
Write-Output "Backend and worker revision verified: $workerRevision"
