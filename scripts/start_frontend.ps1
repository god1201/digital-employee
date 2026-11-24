$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
Set-Location $frontend

if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "首次运行，安装前端依赖..." -ForegroundColor Yellow
    npm install
}

Write-Host "启动前端：$frontend" -ForegroundColor Cyan
npm run dev
