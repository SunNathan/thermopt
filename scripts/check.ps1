# Run exactly what the CI "quality" job runs.
# Usage:  .\scripts\check.ps1
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI.
$ErrorActionPreference = "Stop"

$python = ".\.venv313\Scripts\python.exe"
$ruff = ".\.venv313\Scripts\ruff.exe"

if (-not (Test-Path $python)) {
    Write-Error "Environment missing. Create it with: py -3.13 -m venv .venv313 ; .\.venv313\Scripts\python.exe -m pip install -r requirements_dev.txt"
}

Write-Host "==> ruff check" -ForegroundColor Cyan
& $ruff check lib thermopt_app tests
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> ruff format --check" -ForegroundColor Cyan
& $ruff format --check lib thermopt_app tests
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> mypy" -ForegroundColor Cyan
& $python -m mypy lib/thermopt_lib thermopt_app/app
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> pytest" -ForegroundColor Cyan
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "OK - CI should pass." -ForegroundColor Green
