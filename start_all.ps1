# start_all.ps1
param(
    [switch]$Restart
)

$root = (Get-Location).Path
$logDir = Join-Path $root "logs"

if (!(Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Write-Host ""
Write-Host "=== Demographics Agent - Start All Services ===" -ForegroundColor Cyan
Write-Host "Root: $root" -ForegroundColor DarkGray
Write-Host ""

function Test-PortInUse {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -ne $conn
}

function Stop-PortProcess {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $pids) {
            Write-Host "Stopping PID $pid on port $Port ..." -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }
}

if ($Restart) {
    Write-Host "[CLEANUP] Killing anything on 8001 / 8002 ..." -ForegroundColor Yellow
    Stop-PortProcess -Port 8001
    Stop-PortProcess -Port 8002
}

# 1. Tools Service
Write-Host "[1/3] Starting Tools Service on http://localhost:8001 ..." -ForegroundColor Green
$toolsLog = Join-Path $logDir "tools_service.log"
Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$root'; uvicorn services.tools_service.app.main:app --host 0.0.0.0 --port 8001 *> '$toolsLog'`"" `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

# 2. Orchestration Service
Write-Host "[2/3] Starting Orchestration Service on http://localhost:8002 ..." -ForegroundColor Green
$orchLog = Join-Path $logDir "orchestration_service.log"
Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$root'; uvicorn services.orchestration_service.app.main:app --host 0.0.0.0 --port 8002 *> '$orchLog'`"" `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

# 3. Workflow Scheduler
Write-Host "[3/3] Starting Workflow Scheduler ..." -ForegroundColor Green
$schedLog = Join-Path $logDir "workflow_scheduler.log"
Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$root'; python -m services.workflow_service.app.main *> '$schedLog'`"" `
    -WindowStyle Hidden

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "Started. Log files:" -ForegroundColor Cyan
Write-Host "  $toolsLog"
Write-Host "  $orchLog"
Write-Host "  $schedLog"
Write-Host ""
Write-Host "Health checks:" -ForegroundColor Yellow
Write-Host "  curl http://localhost:8001/health"
Write-Host "  curl http://localhost:8002/health"
Write-Host ""
Write-Host "To stop all: .\stop_all.ps1" -ForegroundColor Yellow
Write-Host ""