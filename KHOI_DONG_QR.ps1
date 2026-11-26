$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$toolsDir = Join-Path $repo '.git/smh-tools'
$qrRoot = Join-Path $repo 'backend/uploads/payment-qr'
$originFile = Join-Path $repo 'backend/uploads/payment-qr-origin.json'
$tunnelLog = Join-Path $toolsDir 'qr-tunnel.err.log'
New-Item -ItemType Directory -Force $toolsDir,$qrRoot | Out-Null
$cloudflared = Join-Path $toolsDir 'cloudflared.exe'
if (-not (Test-Path -LiteralPath $cloudflared)) {
    Invoke-WebRequest 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $cloudflared -UseBasicParsing
}
$signature = Get-AuthenticodeSignature -LiteralPath $cloudflared
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Cloudflare*') {
    throw 'Cloudflared signature verification failed.'
}
$serverReady = $false
try { $serverReady = (Invoke-WebRequest 'http://127.0.0.1:8189/health' -UseBasicParsing -TimeoutSec 3).Content.Trim() -eq 'SMH QR media' } catch {}
if (-not $serverReady) {
    if (Get-NetTCPConnection -LocalPort 8189 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8189 is occupied by another service.' }
    $python = (Get-Command python).Source
    Start-Process -FilePath $python -ArgumentList @('scripts/qr_media_server.py','--root','backend/uploads/payment-qr') -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $toolsDir 'qr-server.out.log') -RedirectStandardError (Join-Path $toolsDir 'qr-server.err.log') | Out-Null
}
$running = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" | Where-Object { $_.ExecutablePath -eq $cloudflared -and $_.CommandLine -like '*127.0.0.1:8189*' }
if (-not $running) {
    # Never retain a stale URL when starting a replacement tunnel.
    if (Test-Path -LiteralPath $originFile) { Remove-Item -LiteralPath $originFile }
    Start-Process -FilePath $cloudflared -ArgumentList @('tunnel','--url','http://127.0.0.1:8189','--no-autoupdate','--protocol','http2') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $toolsDir 'qr-tunnel.out.log') -RedirectStandardError $tunnelLog | Out-Null
}
$deadline = (Get-Date).AddSeconds(50)
do {
    $origin = $null
    if (Test-Path -LiteralPath $tunnelLog) {
        $matches = [regex]::Matches(([string](Get-Content -LiteralPath $tunnelLog -Raw)), 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($matches.Count) { $origin = $matches[$matches.Count - 1].Value }
    }
    if ($origin) {
        try {
            $probe = Invoke-WebRequest "$origin/health" -UseBasicParsing -TimeoutSec 5
            if ($probe.StatusCode -eq 200 -and $probe.Content.Trim() -eq 'SMH QR media') {
                $temporary = "$originFile.tmp"
                @{origin=$origin} | ConvertTo-Json -Compress | Set-Content -LiteralPath $temporary -Encoding UTF8
                Move-Item -LiteralPath $temporary -Destination $originFile -Force
                Write-Host '[QR] HTTPS image origin ready. Main application/webhooks unchanged.'
                exit 0
            }
        } catch {}
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
throw 'QR image tunnel is not ready. Text/link fallback remains available; check .git/smh-tools/qr-tunnel.err.log.'
