# start_dev.ps1
# Script khoi dong FastAPI + ngrok cung luc
# Cach chay:
#   .\start_dev.ps1 -AuthToken "YOUR_NGROK_AUTHTOKEN"
#   .\start_dev.ps1   (neu da add authtoken roi)

param(
    [Parameter(Mandatory=$false)]
    [string]$AuthToken = ""
)

$ErrorActionPreference = "Stop"
$BackendPath = "$PSScriptRoot\backend"
$PowerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "    Smart Merchant Hub -- Dev Server Start      " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------
# 1. Kiem tra Python
# ----------------------------------------------
Write-Host "[1/5] Kiem tra Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "   OK: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "   LOI: Python chua cai! Cai tai: https://python.org" -ForegroundColor Red
    exit 1
}

# ----------------------------------------------
# 2. Tim ngrok
# ----------------------------------------------
Write-Host "[2/5] Tim ngrok..." -ForegroundColor Yellow

$ngrokPaths = @(
    "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe",
    "C:\Program Files\ngrok\ngrok.exe",
    "ngrok"
)

$ngrokCmd = $null
foreach ($p in $ngrokPaths) {
    if ($p -eq "ngrok") {
        if (Get-Command ngrok -ErrorAction SilentlyContinue) { $ngrokCmd = "ngrok"; break }
    } elseif (Test-Path $p) {
        $ngrokCmd = $p; break
    }
}

if (-not $ngrokCmd) {
    Write-Host "   Tim them trong WinGet..." -ForegroundColor Yellow
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "ngrok.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $ngrokCmd = $found.FullName }
}

if ($ngrokCmd) {
    Write-Host "   OK: ngrok tai $ngrokCmd" -ForegroundColor Green
} else {
    Write-Host "   LOI: Khong tim thay ngrok. Hay restart PowerShell sau khi cai." -ForegroundColor Red
    exit 1
}

# ----------------------------------------------
# 3. Set ngrok authtoken
# ----------------------------------------------
if ($AuthToken -ne "") {
    Write-Host "[3/5] Cau hinh ngrok authtoken..." -ForegroundColor Yellow
    & $ngrokCmd config add-authtoken $AuthToken
    Write-Host "   OK: Authtoken da luu" -ForegroundColor Green
} else {
    Write-Host "[3/5] Bo qua authtoken (dung token da luu)" -ForegroundColor Gray
}

# ----------------------------------------------
# 4. Cai dependencies
# ----------------------------------------------
Write-Host "[4/5] Cai Python dependencies..." -ForegroundColor Yellow
Push-Location $BackendPath
pip install -r requirements.txt -q
Pop-Location
Write-Host "   OK: Dependencies sẵn sàng" -ForegroundColor Green

# ----------------------------------------------
# 5. Tao .env neu chua co
# ----------------------------------------------
$envFile = "$BackendPath\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "[5/5] Tao .env tu .env.example..." -ForegroundColor Yellow
    Copy-Item "$BackendPath\.env.example" $envFile
    Write-Host "   OK: .env da tao tai $envFile" -ForegroundColor Green
    Write-Host "   CHU Y: Dien FACEBOOK_PAGE_ACCESS_TOKEN vao .env truoc khi test!" -ForegroundColor Yellow
} else {
    Write-Host "[5/5] .env da ton tai" -ForegroundColor Green
}

# ----------------------------------------------
# 6. Khoi dong FastAPI (terminal moi)
# ----------------------------------------------
Write-Host ""
Write-Host ">> Mo terminal FastAPI server..." -ForegroundColor Cyan
Start-Process $PowerShellExe -ArgumentList "-NoExit", "-Command", "Set-Location '$BackendPath'; Write-Host 'FastAPI dang chay...' -ForegroundColor Cyan; python -m uvicorn app.main:app --reload --port 8000"

Start-Sleep -Seconds 4

# ----------------------------------------------
# 7. Khoi dong ngrok voi Static Domain cố định
# ----------------------------------------------
Write-Host ">> Mo tunnel ngrok (Static Domain)..." -ForegroundColor Cyan
Start-Process $PowerShellExe -ArgumentList "-NoExit", "-Command", "Write-Host 'ngrok tunnel (Static Domain)...' -ForegroundColor Green; & '$ngrokCmd' http 8000 --url=https://rimmed-cane-legwarmer.ngrok-free.dev"

Start-Sleep -Seconds 5

# ----------------------------------------------
# 8. Lay URL va hien thi
# ----------------------------------------------
try {
    $tunnels = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -TimeoutSec 5
    $publicUrl = ($tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url

    Write-Host ""
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "  MOI THU DA CHAY!                             " -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "  Ngrok URL  : $publicUrl" -ForegroundColor White
    Write-Host "  Webhook    : $publicUrl/api/webhooks/instagram" -ForegroundColor Yellow
    Write-Host "  Verify Token: crm_chatbot_2026               " -ForegroundColor Cyan
    Write-Host "  Swagger docs: http://localhost:8000/docs      " -ForegroundColor Cyan
    Write-Host "================================================" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "CHU Y: Mo http://localhost:4040 de lay ngrok URL." -ForegroundColor Yellow
    Write-Host "   Roi paste URL vao Meta Dashboard theo dang:" -ForegroundColor Gray
    Write-Host "   https://xxxx.ngrok-free.app/api/webhooks/instagram" -ForegroundColor White
}

Write-Host ""
Write-Host "Cac buoc tiep theo trong Meta Dashboard:" -ForegroundColor Cyan
Write-Host "   1. Vao developers.facebook.com -> App cua ban" -ForegroundColor White
Write-Host "   2. Webhooks -> Instagram -> Edit Subscription" -ForegroundColor White
Write-Host "   3. Paste Webhook URL + Verify Token roi click Verify and Save" -ForegroundColor White
Write-Host "   4. Subscribe field: messages" -ForegroundColor White
Write-Host ""
