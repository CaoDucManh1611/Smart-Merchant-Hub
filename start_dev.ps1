# start_dev.ps1
# Script khoi dong FastAPI + ngrok cung luc
# Cach chay:
#   .\start_dev.ps1 -AuthToken "YOUR_NGROK_AUTHTOKEN"
#   .\start_dev.ps1 -ResetDatabase
#   .\start_dev.ps1   (neu da add authtoken roi)

param(
    [Parameter(Mandatory=$false)]
    [string]$AuthToken = "",

    [Parameter(Mandatory=$false)]
    [switch]$ResetDatabase
)

$ErrorActionPreference = "Stop"
$BackendPath = "$PSScriptRoot\backend"
$PowerShellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$ComposeProjectPath = $PSScriptRoot

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "    Smart Merchant Hub -- Dev Server Start      " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ----------------------------------------------
# 0. Khoi dong PostgreSQL/pgvector tu dong
# ----------------------------------------------
Write-Host "[0/5] Kiem tra PostgreSQL/pgvector Docker..." -ForegroundColor Yellow
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Host "   LOI: Chua tim thay Docker Desktop. Hay mo Docker Desktop roi chay lai script." -ForegroundColor Red
    exit 1
}

Push-Location $ComposeProjectPath
try {
    & docker compose up -d db
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose khong khoi dong duoc PostgreSQL/pgvector."
    }
} finally {
    Pop-Location
}

$dbReady = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    $dbHealth = & docker inspect --format="{{.State.Health.Status}}" crm_chatbot_db 2>$null
    if ($dbHealth -eq "healthy") {
        $dbReady = $true
        break
    }
    Write-Host "   Dang cho database san sang ($attempt/30)..." -ForegroundColor Gray
    Start-Sleep -Seconds 2
}

if (-not $dbReady) {
    Write-Host "   LOI: Database chua san sang sau 60 giay." -ForegroundColor Red
    Write-Host "   Kiem tra Docker Desktop va xem log bang: docker compose logs db" -ForegroundColor Yellow
    exit 1
}
Write-Host "   OK: PostgreSQL/pgvector da san sang. Backend se tu tao/cap nhat schema." -ForegroundColor Green

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

if ($ResetDatabase) {
    Write-Host ""
    Write-Host "!!! RESET DATABASE: XOA TOAN BO BANG CU TRONG schema public !!!" -ForegroundColor Red
    Write-Host "!!! Du lieu cu se khong the khoi phuc sau thao tac nay. !!!" -ForegroundColor Red
    $resetConfirmation = Read-Host "Nhap RESET de xac nhan"
    if ($resetConfirmation -ne "RESET") {
        Write-Host "Da huy reset database." -ForegroundColor Yellow
        exit 1
    }

    Write-Host ">> Xoa bang cu va tao lai dung 20 bang..." -ForegroundColor Yellow
    Push-Location $BackendPath
    try {
        & python "scripts\reset_database_schema.py" --yes
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   LOI: Reset database that bai." -ForegroundColor Red
            exit 1
        }
    } finally {
        Pop-Location
    }
    Write-Host "   OK: Database da duoc reset ve dung 20 bang." -ForegroundColor Green
}

Write-Host ">> Tao du lieu seed RAG..." -ForegroundColor Yellow
& python "$BackendPath\scripts\generate_seed_dataset.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host "   LOI: Khong the tao du lieu seed RAG" -ForegroundColor Red
    exit 1
}
Write-Host "   OK: Du lieu seed RAG da san sang" -ForegroundColor Green

# ----------------------------------------------
# 6. Khoi dong FastAPI (terminal moi)
# ----------------------------------------------
Write-Host ""
Write-Host ">> Mo terminal FastAPI server..." -ForegroundColor Cyan
Start-Process $PowerShellExe -ArgumentList "-NoExit", "-Command", "Set-Location '$BackendPath'; Write-Host 'FastAPI dang chay...' -ForegroundColor Cyan; python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

Start-Sleep -Seconds 4

# ----------------------------------------------
# 7. Khoi dong ngrok voi Static Domain cố định
# ----------------------------------------------
Write-Host ">> Mo tunnel ngrok (Static Domain)..." -ForegroundColor Cyan
Start-Process $PowerShellExe -ArgumentList "-NoExit", "-Command", "Write-Host 'ngrok tunnel (Static Domain)...' -ForegroundColor Green; & '$ngrokCmd' http 127.0.0.1:8000 --url=https://vocalist-dreamy-corned.ngrok-free.dev"

Start-Sleep -Seconds 5

# ----------------------------------------------
# 8. Lay URL va hien thi
# ----------------------------------------------
try {
    $tunnels = Invoke-RestMethod -Uri "http://localhost:4040/api/tunnels" -TimeoutSec 5
    $publicUrl = ($tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url

    Write-Host ""
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host "  SMART MERCHANT HUB (RAG CHATBOT) DA RUNNING!  " -ForegroundColor Green
    Write-Host "=================================================" -ForegroundColor Green
    Write-Host "  Ngrok URL  : $publicUrl" -ForegroundColor White
    Write-Host "  FB Webhook : $publicUrl/api/webhooks/facebook" -ForegroundColor Yellow
    Write-Host "  IG Webhook : $publicUrl/api/webhooks/instagram" -ForegroundColor Yellow
    Write-Host "  Verify Token: value configured in backend/.env" -ForegroundColor Cyan
    Write-Host "  Swagger docs: http://localhost:8000/docs      " -ForegroundColor Cyan
    Write-Host "=================================================" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "CHU Y: Mo http://localhost:4040 de lay ngrok URL." -ForegroundColor Yellow
}

# ----------------------------------------------
# 9. Tu dong mo Frontend Web App
# ----------------------------------------------
$frontendIndex = "$PSScriptRoot\frontend\index.html"
if (Test-Path $frontendIndex) {
    Write-Host ">> Tu dong mo Frontend App tren trinh duyet..." -ForegroundColor Cyan
    Start-Process $frontendIndex
}

Write-Host ""
Write-Host "HD TEST RAG CHATBOT TREN WEB APP:" -ForegroundColor Cyan
Write-Host "   1. Tab 'Kho tri thức': Drag & drop upload file (PDF, DOCX, TXT...)" -ForegroundColor White
Write-Host "   2. Tab 'AI Assistant': Nhap cau hoi de chat AI RAG + xem nguon trich dan" -ForegroundColor White
Write-Host "   3. Tab 'AI Assistant': Bat 'Auto-Reply' de AI tu dong nhan tin cho khach Facebook/Instagram" -ForegroundColor White
Write-Host ""
