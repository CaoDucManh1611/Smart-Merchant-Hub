param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $PSScriptRoot "tiktok_bot.py"
$lttk = Join-Path $PSScriptRoot "lttk"
$dist = Join-Path $PSScriptRoot "dist\tiktok-bridge"
$work = Join-Path $root "build\tiktok-bridge"
$bundle = Join-Path $work "lttk"

if (-not (Test-Path (Join-Path $lttk "main.py"))) {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Cần cài Git để tải TikTok runtime lần đầu."
  }
  & git clone https://github.com/Linkmail16/ReLttk-TikTok-Client-Bot.git $lttk
}

& $Python -m pip install -r (Join-Path $lttk "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Không cài được thư viện TikTok runtime." }
& $Python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Không cài được PyInstaller." }

New-Item -ItemType Directory -Force -Path $work | Out-Null
if (Test-Path $bundle) {
  [System.IO.Directory]::Delete($bundle, $true)
}
New-Item -ItemType Directory -Force -Path $bundle | Out-Null

# Never ship local sessions, message caches, git metadata, or Python bytecode.
Get-ChildItem $lttk -Recurse -File | Where-Object {
  $_.FullName -notmatch "\\(sesion|__pycache__|\.git)(\\|$)" -and $_.Name -ne "messages.db"
} | ForEach-Object {
  $relative = $_.FullName.Substring($lttk.Length).TrimStart("\\")
  $destination = Join-Path $bundle $relative
  New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
  Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --console `
  --name SmartMerchantTikTok `
  --distpath $dist `
  --workpath $work `
  --specpath $work `
  --add-data "$bundle;lttk" `
  --collect-submodules lttk `
  --collect-all qrcode `
  --collect-all websockets `
  --collect-all lz4 `
  --collect-all Crypto `
  --collect-all stealth_requests `
  $source

if ($LASTEXITCODE -ne 0) { throw "Đóng gói SmartMerchantTikTok.exe thất bại." }
Write-Host "Đã tạo: $(Join-Path $dist 'SmartMerchantTikTok.exe')"
