param(
    [string]$Config = "D:\Claude_work_Territory\MvpSelect\configs\settings.yaml",
    [string]$OutputDir = "artifacts/data_backfill_v6/v2",
    [int]$CallsPerMinute = 60,
    [int]$Workers = 2,
    [string]$StartPhase = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"
$lockPath = "artifacts/data_backfill_v6/.backfill.lock"

while (Test-Path -LiteralPath $lockPath) {
    Start-Sleep -Seconds 15
}

function Invoke-PhaseAudit([string]$Phase) {
    python -m scripts.v6.audit_tushare_backfill_phase_v6 `
        --phase $Phase `
        --output-dir $OutputDir `
        --audit-output "artifacts/data_audits/tushare_backfill_${Phase}_v6.json"
    if ($LASTEXITCODE -ne 0) {
        throw "Audit failed for phase $Phase"
    }
}

function Complete-Phase([string]$Phase) {
    $completed = $false
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        python -m scripts.v6.backfill_tushare_v6 `
            --execute `
            --phase $Phase `
            --output-dir $OutputDir `
            --config $Config `
            --workers $Workers `
            --calls-per-minute $CallsPerMinute `
            --request-timeout 15
        if ($LASTEXITCODE -eq 0) {
            $completed = $true
            break
        }
    }
    if (-not $completed) {
        throw "Phase $Phase remained incomplete after two attempts"
    }
    Invoke-PhaseAudit $Phase
}

$phases = @(
    "adj_factor",
    "daily_basic",
    "moneyflow",
    "margin_detail",
    "stk_limit",
    "stock_st",
    "financial",
    "index",
    "event"
)

if ($StartPhase) {
    $startIndex = [Array]::IndexOf($phases, $StartPhase)
    if ($startIndex -lt 0) {
        throw "Unknown start phase: $StartPhase"
    }
    $phases = $phases[$startIndex..($phases.Count - 1)]
}

foreach ($phase in $phases) {
    Complete-Phase $phase
}
