$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
git rev-parse --is-inside-work-tree | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Not a Git checkout.' }
$branch = git symbolic-ref --quiet --short HEAD
if ($LASTEXITCODE -ne 0 -or -not $branch) { throw 'Select a branch before updating.' }
$changes = git status --porcelain
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Commit or stash local changes before updating.' }
Write-Host "Updating Studio branch: $branch"
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Fast-forward update unsuccessful.' }
& (Join-Path $PSScriptRoot 'setup.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Studio setup unsuccessful.' }
Write-Host '[PASS] Studio updated.'
