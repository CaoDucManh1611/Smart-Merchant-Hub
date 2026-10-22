param(
  [string]$Python = "python",
  [Parameter(Mandatory = $true)][string]$BackendUrl,
  [Parameter(Mandatory = $true)][string]$FrontendUrl
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "build_tiktok_exe.ps1") -Python $Python -BackendUrl $BackendUrl -FrontendUrl $FrontendUrl -ExecutionMode server
if ($LASTEXITCODE -ne 0) { throw "Đóng gói TikTok server connector thất bại." }
& (Join-Path $PSScriptRoot "build_shopee_exe.ps1") -Python $Python -BackendUrl $BackendUrl -FrontendUrl $FrontendUrl -ExecutionMode server
if ($LASTEXITCODE -ne 0) { throw "Đóng gói Shopee server connector thất bại." }
& (Join-Path $PSScriptRoot "build_meta_business_suite_exe.ps1") -Python $Python -BackendUrl $BackendUrl -FrontendUrl $FrontendUrl -ExecutionMode server
if ($LASTEXITCODE -ne 0) { throw "Đóng gói Meta server connectors thất bại." }
Write-Host "Đã tạo server-mode ZIP payload sources trong scripts/dist/*-server."
