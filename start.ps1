param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$ProjectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython)) {
    Write-Host 'Creating a project virtual environment...'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}
& $ProjectPython -c 'import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in ["fastapi", "uvicorn", "multipart"]) else 1)'
if ($LASTEXITCODE -ne 0) {
    & $ProjectPython -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies.' }
}
Write-Host "Open http://127.0.0.1:$Port (Ctrl+C to stop)."
& $ProjectPython -m uvicorn app:app --host 127.0.0.1 --port $Port
