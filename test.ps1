# ═══════════════════════════════════════════════════════════
# ComptaPro — Runner de tests anti-régression (Windows)
# Usage: .\test.ps1           # Quick check (no server)
#        .\test.ps1 --full    # Full check (needs server running)
#        .\test.ps1 --ci      # CI mode (JSON output)
# ═══════════════════════════════════════════════════════════
param(
    [string]$Mode = "--quick"
)

$env:PYTHONIOENCODING = "utf-8"

Write-Host "=== ComptaPro Regression Tests ===" -ForegroundColor Cyan
Write-Host "Mode: $Mode"
Write-Host ""

python regression_tests.py $Mode
$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "OK All regression tests passed" -ForegroundColor Green
} else {
    Write-Host "FAIL REGRESSION DETECTED — do not deploy!" -ForegroundColor Red
    exit $exitCode
}
