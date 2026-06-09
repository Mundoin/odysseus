param(
    [int]$Port = 7000
)

$ErrorActionPreference = "Continue"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title =="
}

function Invoke-Git {
    param([string[]]$GitArgs)
    & git @GitArgs
}

$ScriptRepoRoot = Split-Path -Parent $PSScriptRoot
$CurrentDirectory = (Get-Location).Path
$GitRoot = $null

try {
    $GitRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
} catch {
    $GitRoot = $null
}

if (-not $GitRoot) {
    $GitRoot = $ScriptRepoRoot
    Write-Warning "Not currently inside a Git worktree. Falling back to script repo root: $GitRoot"
}

Write-Section "Workspace"
Write-Host "Current directory : $CurrentDirectory"
Write-Host "Script repo root  : $ScriptRepoRoot"
Write-Host "Git repo root     : $GitRoot"
if ((Resolve-Path -LiteralPath $GitRoot).Path -eq (Resolve-Path -LiteralPath $ScriptRepoRoot).Path) {
    Write-Host "Repo root check   : OK"
} else {
    Write-Warning "Repo root check   : current Git root differs from this script's repo root"
}

Push-Location $GitRoot
try {
    Write-Section "Git Safety"
    Write-Host "Current branch:"
    Invoke-Git @("branch", "--show-current")

    Write-Host ""
    Write-Host "Status --short:"
    Invoke-Git @("status", "--short")

    Write-Host ""
    Write-Host "Latest 6 commits:"
    Invoke-Git @("log", "--oneline", "-6")

    Write-Host ""
    Write-Host "Remotes:"
    Invoke-Git @("remote", "-v")

    $Remotes = @(& git remote)
    $HasOrigin = $Remotes -contains "origin"
    $HasMundoin = $Remotes -contains "mundoin"
    Write-Host ""
    Write-Host "origin remote  : $HasOrigin"
    Write-Host "mundoin remote : $HasMundoin"
    Write-Warning "Push safety: this branch is Bujar's Mundoin fork work. Push to 'mundoin', not 'origin'."

    Write-Section "Python"
    $VenvPython = Join-Path $GitRoot "venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPython) {
        Write-Host "venv python : present ($VenvPython)"
        & $VenvPython --version
    } else {
        Write-Warning "venv python : missing ($VenvPython)"
    }

    Write-Section "Local Helpers"
    $Helpers = @(
        "launch-windows.ps1",
        "start-odysseus-hidden.ps1",
        "stop-odysseus.ps1",
        "tools\run-guard-tests.ps1"
    )
    foreach ($Helper in $Helpers) {
        $Path = Join-Path $GitRoot $Helper
        if (Test-Path -LiteralPath $Path) {
            Write-Host "present : $Helper"
        } else {
            Write-Host "missing : $Helper"
        }
    }

    Write-Section "Process And Port"
    Write-Host "Port checked : $Port"
    try {
        $Listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
    } catch {
        $Listeners = @()
        Write-Warning "Get-NetTCPConnection unavailable or failed: $($_.Exception.Message)"
    }

    if ($Listeners.Count -gt 0) {
        foreach ($Listener in $Listeners) {
            $Proc = Get-Process -Id $Listener.OwningProcess -ErrorAction SilentlyContinue
            $Name = if ($Proc) { $Proc.ProcessName } else { "unknown" }
            Write-Host "listening : PID $($Listener.OwningProcess) ($Name) on $($Listener.LocalAddress):$($Listener.LocalPort)"
        }
    } else {
        $NetstatRows = @(netstat -ano 2>$null | Select-String -Pattern ":$Port\s+.*LISTENING")
        if ($NetstatRows.Count -gt 0) {
            foreach ($Row in $NetstatRows) {
                Write-Host "listening : $($Row.Line.Trim())"
            }
        } else {
            Write-Host "listening : none detected"
        }
    }

    try {
        $OdysseusProcs = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "$Port"
        })
        if ($OdysseusProcs.Count -gt 0) {
            foreach ($Proc in $OdysseusProcs) {
                Write-Host "uvicorn   : PID $($Proc.ProcessId) $($Proc.CommandLine)"
            }
        } else {
            Write-Host "uvicorn   : none detected for port $Port"
        }
    } catch {
        Write-Warning "Process query failed: $($_.Exception.Message)"
    }
} finally {
    Pop-Location
}
