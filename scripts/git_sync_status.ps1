$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

if ((git rev-parse --is-inside-work-tree 2>$null) -ne "true") {
    throw "Not inside a Git repository."
}
$branch = git branch --show-current
if (-not $branch) { throw "Detached HEAD." }
Write-Host "Branch: $branch"

$status = git status --short
if ($status) {
    Write-Host "Worktree has uncommitted changes; run the checkpoint workflow after checks pass."
    $status
    exit 2
}
if (-not (git remote get-url origin 2>$null)) {
    throw "origin is not configured."
}
git fetch --prune origin
if ($LASTEXITCODE) { throw "origin is not reachable." }

$upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
if (-not $upstream) {
    Write-Host "No upstream is configured for $branch."
    exit 3
}
$counts = (git rev-list --left-right --count "$upstream...HEAD") -split '\s+'
$behind = [int]$counts[0]
$ahead = [int]$counts[1]
Write-Host "Ahead: $ahead; Behind: $behind"
if ($behind -gt 0) {
    Write-Host "Remote changes require review; no automatic pull was performed."
    exit 4
}
if ($ahead -gt 0) {
    python scripts/git_safety_check.py --tracked
    if ($LASTEXITCODE) { throw "Tracked safety check failed." }
    git push
    if ($LASTEXITCODE) { throw "Push failed." }
}
