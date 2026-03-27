# stop_all.ps1
Write-Host ""
Write-Host "=== Demographics Agent - Stop All Services ===" -ForegroundColor Cyan
Write-Host ""

function Stop-PortProcess {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $pids) {
            Write-Host "Stopping PID $pid on port $Port ..." -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "No process found on port $Port" -ForegroundColor DarkGray
    }
}

Stop-PortProcess -Port 8001
Stop-PortProcess -Port 8002

# Best effort: stop scheduler python started from this project
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Where-Object {
    $_.CommandLine -like "*services.workflow_service.app.main*"
} | ForEach-Object {
    Write-Host "Stopping scheduler PID $($_.ProcessId) ..." -ForegroundColor Yellow
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host ""