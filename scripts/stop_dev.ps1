$ErrorActionPreference = "SilentlyContinue"

foreach ($port in @(8000, 5173)) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen
    $owners = $connections | Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($ownerPid in $owners) {
        if (-not $ownerPid) { continue }
        Write-Host "停止端口 $port 的进程 $ownerPid" -ForegroundColor Yellow
        Stop-Process -Id $ownerPid -Force
    }
}

Write-Host "前后端进程已停止。" -ForegroundColor Green
