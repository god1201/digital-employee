$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

Write-Host "启动后端窗口..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "start_backend.ps1")
)

Start-Sleep -Seconds 2

Write-Host "启动前端窗口..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "start_frontend.ps1")
)

Write-Host ""
Write-Host "前端：http://localhost:5173" -ForegroundColor Green
Write-Host "后端：http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "停止：powershell -ExecutionPolicy Bypass -File scripts\stop_dev.ps1" -ForegroundColor DarkGray
