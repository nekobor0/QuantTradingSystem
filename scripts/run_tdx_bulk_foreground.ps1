$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$host.UI.RawUI.WindowTitle = "QuantTradingSystem - TDX full daily-bar import"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$passwordPath = Join-Path $projectRoot "deploy\secrets\db_password.txt"
if (-not (Test-Path -LiteralPath $passwordPath)) {
    throw "Missing PostgreSQL password file: $passwordPath"
}
$password = [Uri]::EscapeDataString((Get-Content -Raw -LiteralPath $passwordPath).Trim())
$env:QTS_DATABASE_URL = "postgresql+psycopg://qts:$password@127.0.0.1:5432/qts"

$checkpointPath = Join-Path $projectRoot "artifacts\tdx_bridge\bulk_checkpoint.json"
if (Test-Path -LiteralPath $checkpointPath) {
    $checkpoint = Get-Content -Raw -LiteralPath $checkpointPath | ConvertFrom-Json
    Write-Host "Resuming TDX import: $($checkpoint.completed.Count) / $($checkpoint.total), failures: $($checkpoint.failures.PSObject.Properties.Count)" -ForegroundColor Cyan
}

Write-Host "Keep Docker Desktop and the TDX terminal open." -ForegroundColor Yellow
Write-Host "Using 4 parallel workers. Progress is checkpointed after every batch." -ForegroundColor Yellow
Write-Host "Ctrl+C stops safely; run this script again to resume." -ForegroundColor Yellow

& ".\.venv\Scripts\python.exe" "scripts\tdx_bridge.py" `
    --raw-dir "artifacts\tdx_bridge\raw" `
    --timeout-seconds 180 `
    bulk-backfill `
    --symbols-file "artifacts\tdx_bridge\universe_a_etf.csv" `
    --start 2005-01-01 `
    --end 2026-07-28 `
    --batch-size 4 `
    --workers 4 `
    --max-retries 2 `
    --checkpoint "artifacts\tdx_bridge\bulk_checkpoint.json" `
    --report "artifacts\tdx_bridge\bulk_report.json"

$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) {
    Write-Host "TDX full import finished successfully. See artifacts\tdx_bridge\bulk_report.json" -ForegroundColor Green
} elseif ($exitCode -eq 3) {
    Write-Host "TDX full import finished with individual failures. Review bulk_report.json." -ForegroundColor Yellow
} else {
    Write-Host "TDX full import stopped with exit code $exitCode. Re-run this script to resume." -ForegroundColor Red
}
