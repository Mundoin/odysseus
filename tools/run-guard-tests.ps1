$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Python venv not found: $Python"
}

Push-Location $RepoRoot
try {
    Write-Host "Running guardrail suites..."
    & $Python -m pytest -q `
        tests/test_external_action_guards.py `
        tests/test_mcp_dispatch_guards.py `
        tests/test_live_browser_guardrail_smoke.py `
        tests/test_guard_preview_quality.py

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "Running focused agent operating-rules prompt test..."
    & $Python -m pytest -q tests/test_agent_loop.py -k external_action_confirmation_contract

    exit $LASTEXITCODE
} finally {
    Pop-Location
}
