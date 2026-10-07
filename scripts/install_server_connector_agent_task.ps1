param(
  [string]$Python = "python",
  [string]$TaskName = "SmartMerchantWindowsConnectorAgent"
)

$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Mở PowerShell bằng quyền Administrator để cài tác vụ chạy cùng Windows."
}
$pythonCommand = Get-Command $Python -ErrorAction Stop
$pythonPath = $pythonCommand.Source
& $pythonPath -c "import playwright.async_api"
if ($LASTEXITCODE -ne 0) { throw "Python này chưa có Playwright. Chạy: `"$pythonPath`" -m pip install playwright" }

$backendUrl = (Read-Host "URL CRM mà Windows VPS truy cập được, ví dụ https://api.example.com").Trim().TrimEnd("/")
$backendUri = $null
if (-not [Uri]::TryCreate($backendUrl, [UriKind]::Absolute, [ref]$backendUri) -or $backendUri.Scheme -notin @("http", "https")) {
  throw "Backend URL phải là HTTP/HTTPS hợp lệ. Dùng HTTPS ngoài môi trường phát triển."
}
$secureToken = Read-Host "Dán secret agent đã cấu hình giống hệt trong backend/.env" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try { $agentToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
if ($agentToken.Length -lt 32) { throw "Secret phải có ít nhất 32 ký tự." }

$dataDirectory = Join-Path $env:ProgramData "SmartMerchant\ServerConnectorAgent"
New-Item -ItemType Directory -Force -Path $dataDirectory | Out-Null
$configPath = Join-Path $dataDirectory "server-connector-agent.json"
$config = @{
  backend_url = $backendUrl
  agent_token = $agentToken
  listen_host = "0.0.0.0"
  listen_port = 8095
  data_dir = (Join-Path $dataDirectory "channels")
} | ConvertTo-Json -Compress
[IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))
$agentToken = $null
$secureToken.Dispose()

$icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
& $icacls $dataDirectory /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Không thể giới hạn ACL cho secret và profile connector." }

$launcher = Join-Path $PSScriptRoot "start_server_connector_agent.ps1"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$launcher`" -Python `"$pythonPath`" -ConfigPath `"$configPath`""
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Đã đăng ký tác vụ $TaskName chạy cùng Windows. Hãy kiểm tra Windows Firewall chỉ cho backend/private network vào cổng 8095."
Write-Host "Không mở cổng 8095 hoặc cổng CDP ra internet; cấu hình SERVER_CONNECTOR_AGENT_URL/token ở backend rồi khởi động lại backend/worker."
