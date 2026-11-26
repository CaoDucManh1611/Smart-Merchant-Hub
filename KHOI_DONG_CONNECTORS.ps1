param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$channels = @(
    @('Facebook', 'meta-business-suite-bridge\SmartMerchantMessenger.exe', 'SmartMerchantMetaBusinessSuite', 'facebook_connector_config.json'),
    @('Instagram', 'meta-business-suite-bridge\SmartMerchantInstagram.exe', 'SmartMerchantMetaBusinessSuite', 'instagram_connector_config.json'),
    @('Shopee', 'shopee-bridge\SmartMerchantShopee.exe', 'SmartMerchantShopee', 'connector_config.json'),
    @('TikTok', 'tiktok-bridge\SmartMerchantTikTok.exe', 'SmartMerchantTikTok', 'connector_config.json')
)
# Saved pairing files are only candidates; the database is authoritative.
$entries = @()
foreach ($candidate in $channels) {
    $path = Join-Path (Join-Path $env:LOCALAPPDATA $candidate[2]) $candidate[3]
    if (Test-Path -LiteralPath $path) {
        $saved = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($saved.connector_token) {
            $entries += @{ kind = $candidate[0].ToLowerInvariant(); token = [string]$saved.connector_token }
        }
    }
}
$allowed = @{}
$verificationReasons = @{}
if ($entries.Count) {
    $payload = ConvertTo-Json -InputObject @($entries) -Compress
    $verification = $payload | docker exec -i smart-merchant-hub-runtime-backend-1 python -m app.scripts.check_startup_connectors
    if ($LASTEXITCODE -ne 0) { throw 'Khong xac minh duoc kenh dang ket noi; khong tu mo connector.' }
    foreach ($state in (ConvertFrom-Json -InputObject ($verification -join "`n"))) { $allowed[$state.kind] = [bool]$state.allowed; $verificationReasons[$state.kind] = $state.reason }
}
$facebookEnabled = $false
$failed = $false
foreach ($channel in $channels) {
    $name, $relativeExe, $runtimeFolder, $configName = $channel
    $kind = $name.ToLowerInvariant()
    if (-not $allowed[$kind]) {
        if ($verificationReasons[$kind] -eq "credentials_unavailable") {
            Write-Warning "$name - thong tin ket noi khong giai ma duoc; can ghep noi lai kenh nay, khong tu mo."
        } else { Write-Host "$name - chua ket noi, da ngat hoac khong chay local; bo qua." }
        continue
    }
    if ($kind -eq 'facebook') { $facebookEnabled = $true }
    $runtime = Join-Path $env:LOCALAPPDATA $runtimeFolder
    $configPath = Join-Path $runtime $configName
    if (-not (Test-Path -LiteralPath $configPath)) {
        Write-Host "$name - chua ghep noi tren may nay, bo qua."
        continue
    }
    try {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if (-not $config.backend_url -or -not $config.connector_token) {
            throw 'Cau hinh ghep noi chua day du.'
        }
        $exe = Join-Path $repo "scripts\dist\$relativeExe"
        if (-not (Test-Path -LiteralPath $exe)) { throw "Thieu ung dung $name." }
        $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe }
        if ($running) { Write-Host "$name - tien trinh dang chay; can kiem tra phien dang nhap trong Edge."; continue }
        if ($CheckOnly) { Write-Host "$name - da setup, san sang khoi dong."; continue }
        $previousRestart = $env:SMART_MERCHANT_AUTO_RESTART
        try {
            $env:SMART_MERCHANT_AUTO_RESTART = '1'
            Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime "$name-startup.stdout.log") -RedirectStandardError (Join-Path $runtime "$name-startup.stderr.log")
        } finally {
            $env:SMART_MERCHANT_AUTO_RESTART = $previousRestart
        }
        Write-Host "$name - da mo tien trinh, dang cho ket noi nen tang."
    } catch {
        Write-Warning "$name - $($_.Exception.Message)"
        $failed = $true
    }
}
Write-Host 'Telegram va Zalo API nhan tin qua backend/webhook. Can tunnel cong khai neu nha cung cap goi vao may nay.'
if (-not $CheckOnly -and $facebookEnabled) {
    try {
        $deadline = (Get-Date).AddSeconds(90)
        do {
            $inbox = @()
            try {
                $tabs = Invoke-RestMethod 'http://127.0.0.1:9224/json/list' -TimeoutSec 3
                $inbox = @($tabs | Where-Object { $_.url -like 'https://business.facebook.com/latest/inbox/messenger*' })
            } catch {}
            if ($inbox.Count) { break }
            Start-Sleep -Seconds 2
        } while ((Get-Date) -lt $deadline)
        if (-not $inbox.Count) { throw 'Facebook chua o dung inbox. Dang nhap Meta Business Suite trong Edge cua connector.' }
        Write-Host 'Facebook - da mo dung inbox. Hay kiem tra dung Page va gui mot tin de xac nhan hai chieu.'
    } catch {
        Write-Warning $_.Exception.Message
        $failed = $true
    }
}
if ($failed) { exit 1 }
