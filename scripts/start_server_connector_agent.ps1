param(
  [string]$Python = "python",
  [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"
$agentScript = Join-Path $PSScriptRoot "server_connector_agent.py"
if ($ConfigPath) {
  $env:SERVER_CONNECTOR_AGENT_CONFIG = $ConfigPath
}
$configuredFile = $env:SERVER_CONNECTOR_AGENT_CONFIG -and (Test-Path -LiteralPath $env:SERVER_CONNECTOR_AGENT_CONFIG -PathType Leaf)
if (-not $configuredFile -and -not $env:SERVER_CONNECTOR_BACKEND_URL) {
  $env:SERVER_CONNECTOR_BACKEND_URL = (Read-Host "URL CRM mà Windows VPS truy cập được").Trim().TrimEnd("/")
}
if (-not $configuredFile -and -not $env:SERVER_CONNECTOR_AGENT_TOKEN) {
  $secureToken = Read-Host "Dán secret agent giống backend/.env" -AsSecureString
  $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
  try { $env:SERVER_CONNECTOR_AGENT_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secureToken.Dispose() }
}
$hasEnvironment = $env:SERVER_CONNECTOR_BACKEND_URL -and $env:SERVER_CONNECTOR_AGENT_TOKEN -and $env:SERVER_CONNECTOR_AGENT_TOKEN.Length -ge 32
$hasConfig = $false
if ($env:SERVER_CONNECTOR_AGENT_CONFIG -and (Test-Path -LiteralPath $env:SERVER_CONNECTOR_AGENT_CONFIG -PathType Leaf)) {
  $config = Get-Content -LiteralPath $env:SERVER_CONNECTOR_AGENT_CONFIG -Raw | ConvertFrom-Json
  $hasConfig = [bool]$config.backend_url -and [bool]$config.agent_token -and $config.agent_token.Length -ge 32
}
if (-not $hasEnvironment -and -not $hasConfig) {
  throw "Hãy cấu hình SERVER_CONNECTOR_BACKEND_URL và secret ít nhất 32 ký tự, hoặc truyền ConfigPath tới file agent đã bảo vệ ACL."
}

& $Python -c "import playwright.async_api" 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "Thiếu Playwright cho Python này. Cài một lần bằng: $Python -m pip install playwright"
}

& $Python $agentScript
if ($LASTEXITCODE -ne 0) { throw "Windows connector agent đã dừng với mã lỗi $LASTEXITCODE." }
