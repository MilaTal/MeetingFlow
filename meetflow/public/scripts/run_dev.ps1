# Запуск сервера MeetFlow: http://127.0.0.1:8002 (порт меняется параметром -Port).
#
# Данные — вне папки пакета, в ~/.meetflow: база, маршруты моделей models.json, журналы. Обновление пакета их не
# трогает. Инструмент подключения модели:
#   -Llm mock        стенд без модели, на каждом экране плашка
#   -Llm ollama      локальная модель из темы (llm.generator / llm.verifier)
#   -Llm openrouter  облачные модели из темы (llm.openrouter.*); ключ OPENROUTER_API_KEY
#   -Llm routes      цепочки точек по ролям из ~/.meetflow/models.json, образец — docs/models.example.json
#
# Ключ берётся из переменной OPENROUTER_API_KEY, иначе — строка из ~/.meetflow/.env.local. Значение не печатается.
#   powershell -ExecutionPolicy Bypass -File scripts\run_dev.ps1 -Theme it_product -Llm routes
param([string]$Theme = "it_product", [int]$Port = 8002,
      [ValidateSet("mock", "ollama", "openrouter", "routes")][string]$Llm = "mock")
$data = Join-Path $HOME ".meetflow"
New-Item -ItemType Directory -Force $data | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:MEETFLOW_LLM = $Llm
$env:MODEL_ROUTES_PATH = Join-Path $data "models.json"
$env:MEETFLOW_JOURNAL = Join-Path $data "logs\llm_calls.jsonl"
$env:HF_HUB_OFFLINE = "1"
$needKey = ($Llm -eq "openrouter") -or ($Llm -eq "routes" -and (Test-Path $env:MODEL_ROUTES_PATH) -and
           ((Get-Content -LiteralPath $env:MODEL_ROUTES_PATH -Raw -Encoding UTF8) -match '"kind"\s*:\s*"openrouter"'))
$envFile = Join-Path $data ".env.local"
if ($needKey -and -not $env:OPENROUTER_API_KEY) {
    if (-not (Test-Path $envFile)) { Write-Error "Ключ не задан: переменная OPENROUTER_API_KEY или $envFile"; exit 2 }
    $line = Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -match '^\s*OPENROUTER_API_KEY\s*=' } | Select-Object -First 1
    if (-not $line) { Write-Error "В $envFile нет строки OPENROUTER_API_KEY."; exit 2 }
    $env:OPENROUTER_API_KEY = ($line -replace '^\s*OPENROUTER_API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'")
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Порт $Port занят. Остановите прежний экземпляр или запустите с другим -Port."; exit 1
}
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m meetflow serve --theme $Theme --db (Join-Path $data "meetflow.db") --port $Port
