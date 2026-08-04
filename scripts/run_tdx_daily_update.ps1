param(
    [datetime]$TradingDate = ([TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
        [DateTime]::UtcNow,
        "China Standard Time"
    ).Date),
    [ValidateRange(1, 4)]
    [int]$Workers = 4
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$chinaNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
    [DateTime]::UtcNow,
    "China Standard Time"
)
$targetDate = $TradingDate.Date
if ($targetDate -gt $chinaNow.Date) {
    throw "TradingDate cannot be in the future: $($targetDate.ToString('yyyy-MM-dd'))"
}
if ($targetDate.DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)) {
    throw "TradingDate is a weekend: $($targetDate.ToString('yyyy-MM-dd'))"
}
if ($targetDate -eq $chinaNow.Date -and $chinaNow.TimeOfDay -lt [TimeSpan]::FromHours(15.5)) {
    throw "Today's update may run only after 15:30 China Standard Time"
}

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$passwordPath = Join-Path $projectRoot "deploy\secrets\db_password.txt"
$universePath = Join-Path $projectRoot "artifacts\tdx_bridge\universe_a_etf.csv"
foreach ($requiredPath in @($pythonPath, $passwordPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Missing required file: $requiredPath"
    }
}

$dockerStatus = & docker ps --filter "publish=5432" --format "{{.Names}}|{{.Status}}"
if ($LASTEXITCODE -ne 0 -or -not $dockerStatus) {
    throw "No running Docker PostgreSQL container publishes port 5432"
}
if (-not (Get-Process TdxW -ErrorAction SilentlyContinue)) {
    throw "TdxW.exe is not running; start and log in to the TDX terminal first"
}
if (-not (Test-NetConnection 127.0.0.1 -Port 17709 -InformationLevel Quiet)) {
    throw "TDX local endpoint 127.0.0.1:17709 is not listening"
}

$dateText = $targetDate.ToString("yyyy-MM-dd")
$dailyRoot = Join-Path $projectRoot "artifacts\tdx_bridge\daily\$dateText"
New-Item -ItemType Directory -Force -Path $dailyRoot | Out-Null

Write-Host "Refreshing the current A-share and ETF universe from TDX..." -ForegroundColor Cyan
& $pythonPath "scripts\tdx_bridge.py" `
    --timeout-seconds 180 `
    export-symbols `
    --markets 5 31 `
    --output $universePath
if ($LASTEXITCODE -ne 0) {
    throw "TDX universe refresh failed with exit code $LASTEXITCODE"
}

$password = [Uri]::EscapeDataString((Get-Content -Raw -LiteralPath $passwordPath).Trim())
$env:QTS_DATABASE_URL = "postgresql+psycopg://qts:$password@127.0.0.1:5432/qts"
$checkpointPath = Join-Path $dailyRoot "checkpoint.json"
$reportPath = Join-Path $dailyRoot "report.json"

Write-Host "Updating TDX daily bars for $dateText with $Workers workers..." -ForegroundColor Cyan
& $pythonPath "scripts\tdx_bridge.py" `
    --raw-dir "artifacts\tdx_bridge\raw" `
    --timeout-seconds 180 `
    bulk-backfill `
    --symbols-file $universePath `
    --start $dateText `
    --end $dateText `
    --batch-size 20 `
    --workers $Workers `
    --max-retries 2 `
    --checkpoint $checkpointPath `
    --report $reportPath

$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) {
    Write-Host "TDX daily update completed: $reportPath" -ForegroundColor Green
} elseif ($exitCode -eq 3) {
    Write-Host "TDX daily update completed with individual failures: $reportPath" -ForegroundColor Yellow
} else {
    Write-Host "TDX daily update failed with exit code $exitCode" -ForegroundColor Red
}
exit $exitCode
