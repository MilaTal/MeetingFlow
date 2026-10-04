# Запуск сервера MeetFlow на локальной машине. Порты 8000/8001 заняты Проектом ERP и Планёркой.
#
# Инструмент подключения модели выбирается при развёртывании (решение владельца 03.10.26):
#   -Llm mock        стенд без модели, на каждом экране плашка
#   -Llm ollama      локальная модель; имена моделей — в теме (llm.generator / llm.verifier, пока заглушки)
#   -Llm openrouter  модели из темы (llm.openrouter.*); ключ OPENROUTER_API_KEY
#
# Ключ OpenRouter: если переменная уже задана — берётся она. Иначе — строка OPENROUTER_API_KEY из файла
# -KeyFrom (по умолчанию .env.local Планёрки, разрешение владельца 03.10.26 «обращаться к тем же ключам»).
# Из файла читается только эта строка; значение не печатается и не пишется на диск.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_dev.ps1 -Theme erp_rollout -Port 8002 -Llm openrouter
param([string]$Theme = "it_product", [int]$Port = 8002, [string]$Db = "data\meetflow.db",
      [ValidateSet("mock", "ollama", "openrouter")][string]$Llm = "mock",
      [string]$KeyFrom = "$env:USERPROFILE\Documents\ITMO_planerka\webapp\.env.local")
$env:PYTHONIOENCODING = "utf-8"
$env:MEETFLOW_LLM = $Llm
$env:HF_HUB_OFFLINE = "1"
$env:PYANNOTE_METRICS_ENABLED = "false"
# свой .env.local MeetFlow главнее: зависимость от файла Планёрки — только запасной путь (письмо meeting-registry 22)
$own = Join-Path (Split-Path $PSScriptRoot -Parent) ".env.local"
if (-not $PSBoundParameters.ContainsKey("KeyFrom") -and (Test-Path $own)) { $KeyFrom = $own }
if ($Llm -eq "openrouter" -and -not $env:OPENROUTER_API_KEY) {
    if (-not (Test-Path $KeyFrom)) { Write-Error "Ключ OpenRouter не задан, файла $KeyFrom нет."; exit 2 }
    $line = Get-Content -LiteralPath $KeyFrom -Encoding UTF8 | Where-Object { $_ -match '^\s*OPENROUTER_API_KEY\s*=' } | Select-Object -First 1
    if (-not $line) { Write-Error "В $KeyFrom нет строки OPENROUTER_API_KEY."; exit 2 }
    $env:OPENROUTER_API_KEY = ($line -replace '^\s*OPENROUTER_API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'")
    Write-Host "Ключ OpenRouter взят из $KeyFrom (значение не показывается)."
}
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m meetflow serve --theme $Theme --db $Db --port $Port
