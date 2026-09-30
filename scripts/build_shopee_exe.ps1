param(
  [string]$Python = "python",
  [string]$BackendUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "shopee_bot.py"
$dist = Join-Path $PSScriptRoot "dist\shopee-bridge"
$work = Join-Path (Join-Path $PSScriptRoot "..") "build\shopee-bridge"
$defaults = Join-Path $work "connector_defaults.json"

$backendUri = $null
if (-not [Uri]::TryCreate($BackendUrl, [UriKind]::Absolute, [ref]$backendUri) -or $backendUri.Scheme -notin @("http", "https")) {
  throw "BackendUrl phải là một địa chỉ HTTP hoặc HTTPS hợp lệ."
}

& $Python -m pip install pyinstaller playwright
if ($LASTEXITCODE -ne 0) { throw "Không cài được công cụ đóng gói Shopee." }
New-Item -ItemType Directory -Force -Path $work | Out-Null
@{ backend_url = $BackendUrl.TrimEnd("/") } | ConvertTo-Json -Compress | Set-Content -LiteralPath $defaults -Encoding Ascii

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --console `
  --name SmartMerchantShopee `
  --distpath $dist `
  --workpath $work `
  --specpath $work `
  --add-data "$defaults;." `
  --collect-all playwright `
  --hidden-import greenlet `
  --hidden-import pyee `
  $source

if ($LASTEXITCODE -ne 0) { throw "Đóng gói SmartMerchantShopee.exe thất bại." }
Write-Host "Đã tạo: $(Join-Path $dist 'SmartMerchantShopee.exe')"
