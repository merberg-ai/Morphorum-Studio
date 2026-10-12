# Launch native Studio; never starts or stops the backend.
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Studio is not installed. Run .\setup.ps1 first.' }
& $python -m morphorum_studio @args
exit $LASTEXITCODE
