# Локальный прогон всех тестов (make на машине нет). Запуск из корня framework:
#   powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1 [-Marker security]
param([string]$Marker = "")
$env:PYTHONIOENCODING = "utf-8"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Marker) {
    python -m pytest tests -q -m $Marker -p no:cacheprovider -W ignore::DeprecationWarning
} else {
    python -m pytest tests -q -p no:cacheprovider -W ignore::DeprecationWarning
}
exit $LASTEXITCODE
