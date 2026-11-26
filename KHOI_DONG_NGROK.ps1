$ErrorActionPreference = 'Stop'
$domain = 'https://glitzy-confusion-casualty.ngrok-free.dev'
try { $tunnels = (Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels } catch { $tunnels = @() }
if ($tunnels.public_url -contains $domain) { Write-Host 'Tunnel SMH da chay.'; exit 0 }
if ($tunnels.Count -gt 0) { throw 'Dang co tunnel khac; kiem tra truoc khi mo them.' }
& ngrok http --url=$domain 5173
