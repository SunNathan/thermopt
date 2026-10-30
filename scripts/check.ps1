# Lance localement exactement ce que fait le job « quality » de la CI.
# Usage :  .\scripts\check.ps1
$ErrorActionPreference = "Stop"

$python = ".\.venv313\Scripts\python.exe"
$ruff = ".\.venv313\Scripts\ruff.exe"

if (-not (Test-Path $python)) {
    Write-Error "Environnement introuvable. Crée-le avec : py -3.13 -m venv .venv313 ; .\.venv313\Scripts\python.exe -m pip install -r requirements_dev.txt"
}

Write-Host "==> ruff check" -ForegroundColor Cyan
& $ruff check custom_components tests
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> ruff format --check" -ForegroundColor Cyan
& $ruff format --check custom_components tests
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> mypy" -ForegroundColor Cyan
& $python -m mypy custom_components/thermopt
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "==> pytest" -ForegroundColor Cyan
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "OK — la CI devrait passer." -ForegroundColor Green
