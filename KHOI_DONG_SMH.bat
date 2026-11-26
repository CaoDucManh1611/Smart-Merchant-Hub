@echo off
setlocal
chcp 65001 >nul
set "SMH_REPO=%~dp0"
cd /d "%SMH_REPO%" || goto error
echo [1/4] Kiem tra Docker...
docker info >nul 2>&1
if errorlevel 1 (
  powershell.exe -NoProfile -Command "$p=Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'; if(-not(Test-Path $p)){$p=Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'}; Start-Process -FilePath $p -WindowStyle Hidden"
  if errorlevel 1 goto error
)
powershell.exe -NoProfile -Command "$end=(Get-Date).AddMinutes(3); do {docker info *> $null; if($LASTEXITCODE -eq 0){exit 0}; Start-Sleep -Seconds 3} while((Get-Date) -lt $end); exit 1"
if errorlevel 1 goto error
echo [2/4] Khoi dong SMH va cho dich vu san sang...
docker compose --env-file .env -p smart-merchant-hub-runtime -f docker-compose.yml -f .git/smh-local.compose.yml up -d --wait --wait-timeout 180
if errorlevel 1 goto error
echo [QR] Khoi dong duong anh thanh toan...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0KHOI_DONG_QR.ps1"
if errorlevel 1 echo [CANH BAO] Anh QR chua san sang. SMH van chay, chi gui duoc chu/link. Xem log .git/smh-tools.
echo [3/4] Khoi dong cac connector da setup...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0KHOI_DONG_CONNECTORS.ps1"
if errorlevel 1 goto error
echo [4/4] Mo SMH...
start "" "http://localhost:5173/"
echo.
echo Dich vu SMH da khoi dong. Giu Edge cua connector mo va dang nhap Meta neu duoc hoi.
echo Neu can duong dan cong khai, mo ngrok bang lenh: ngrok http --url=https://glitzy-confusion-casualty.ngrok-free.dev 5173
pause
exit /b 0
:error
echo.
echo Khoi dong chua hoan tat. Xem loi phia tren.
pause
exit /b 1
