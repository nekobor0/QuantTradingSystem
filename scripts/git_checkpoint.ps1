param(
    [Parameter(Mandatory = $true)]
    [string]$Message
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

if ($Message -match '^\s*(update|changes|backup|save)\s*$') {
    throw "Use a descriptive checkpoint message."
}
if ((git rev-parse --is-inside-work-tree 2>$null) -ne "true") {
    throw "Not inside a Git repository."
}
$branch = git branch --show-current
if (-not $branch) { throw "Detached HEAD is not allowed." }
if ($branch -in @("main", "master")) { throw "Checkpoint commits are prohibited on $branch." }
if (git diff --name-only --diff-filter=U) { throw "Resolve merge conflicts first." }
if (git diff --cached --name-only) { throw "The index already contains staged work; review it manually first." }

python scripts/git_safety_check.py --worktree
if ($LASTEXITCODE) { throw "Worktree safety check failed." }
python -m compileall -q src scripts
if ($LASTEXITCODE) { throw "Syntax check failed." }
python -m mypy src\quant_trading_system --exclude 'src[\\/]quant_trading_system[\\/]research[\\/]'
if ($LASTEXITCODE) { throw "Type check failed." }
python -m pytest -q tests/risk tests/execution_ledger tests/api_ui
if ($LASTEXITCODE) { throw "Quick tests failed." }

git add -A
python scripts/git_safety_check.py --staged
if ($LASTEXITCODE) {
    git reset
    throw "Staged safety check failed; staging was cleared without changing files."
}
if (-not (git diff --cached --name-only)) {
    Write-Host "No changes to checkpoint."
    exit 0
}
git diff --cached --name-status
git diff --cached --stat
git commit -m $Message
if ($LASTEXITCODE) { throw "Commit failed." }
git push -u origin $branch
if ($LASTEXITCODE) { throw "Push failed; the local commit is preserved." }
git rev-parse HEAD
