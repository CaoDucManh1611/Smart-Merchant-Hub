param(
  [string]$Python = "python",
  [string]$BackendUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "tiktok_bot.py"
$dist = Join-Path $PSScriptRoot "dist\tiktok-bridge"
$work = Join-Path (Join-Path $PSScriptRoot "..") "build\tiktok-bridge"
$defaults = Join-Path $work "connector_defaults.json"

$backendUri = $null
if (-not [Uri]::TryCreate($BackendUrl, [UriKind]::Absolute, [ref]$backendUri) -or $backendUri.Scheme -notin @("http", "https")) {
  throw "BackendUrl phải là một địa chỉ HTTP hoặc HTTPS hợp lệ."
}

& $Python -m pip install pyinstaller playwright
if ($LASTEXITCODE -ne 0) { throw "Không cài được công cụ đóng gói TikTok Seller Center." }
New-Item -ItemType Directory -Force -Path $work | Out-Null
@{ backend_url = $BackendUrl.TrimEnd("/") } | ConvertTo-Json -Compress | Set-Content -LiteralPath $defaults -Encoding Ascii

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --console `
  --name SmartMerchantTikTok `
  --distpath $dist `
  --workpath $work `
  --specpath $work `
  --add-data "$defaults;." `
  --collect-all playwright `
  --hidden-import greenlet `
  --hidden-import pyee `
  $source

if ($LASTEXITCODE -ne 0) { throw "Đóng gói SmartMerchantTikTok.exe thất bại." }
Write-Host "Đã tạo: $(Join-Path $dist 'SmartMerchantTikTok.exe')"
