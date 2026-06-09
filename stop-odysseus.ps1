$Repo = "D:\Repos\odysseus\odysseus"
$Port = 7000
$DataDir = Join-Path $Repo "data"
$PidFile = Join-Path $DataDir "odysseus-launcher.pid"

$procs = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -match "uvicorn" -and
        $_.CommandLine -match "7000"
    }

if (-not $procs) {
    Write-Host "Odysseus not running on port $Port."
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    exit
}

foreach ($proc in $procs) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped PID $($proc.ProcessId)"
}

if (Test-Path $PidFile) {
    $launcherPid = Get-Content $PidFile -Raw
    $launcherPid = $launcherPid.Trim()
    if ($launcherPid -match '^\d+$') {
        Stop-Process -Id ([int]$launcherPid) -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped launcher PID $launcherPid"
    }
    Remove-Item $PidFile -Force
}

Write-Host "Odysseus stopped."
