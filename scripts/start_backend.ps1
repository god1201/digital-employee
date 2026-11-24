$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONUTF8 = "1"

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "未找到虚拟环境：$python，请先执行 python -m venv .venv 并安装依赖。"
}

Write-Host "启动后端：$root" -ForegroundColor Cyan
& $python -m app.main
