# Windows developer installation; does not install or launch Morphorum backend.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } else { throw 'Python 3.12 or 3.13 is required. Install Python and rerun setup.ps1.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
}
& $python -m pip install -e '.'
if ($LASTEXITCODE -ne 0) { throw 'Studio dependency installation failed.' }
& $python -m morphorum_studio --version
if ($LASTEXITCODE -ne 0) { throw 'Studio version smoke test failed.' }
Write-Host '[PASS] Morphorum Studio installed. Run .\run.ps1'
