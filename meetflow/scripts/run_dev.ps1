# Запуск сервера MeetFlow. Порты 8000/8001 заняты Проектом ERP и Планёркой, новые фронты — с 8010 (владелец 09.10.26).
#
# Модели по умолчанию нет (правило владельца 13.10.26, ответ 15.10.26):
#   -Llm routes      (умолчание) модели назначает супер-администратор в «Моделях» (data\models.json); пока не
#                    назначены — роль «не настроена», вызовов нет; ключ можно ввести значением прямо в «Моделях»
#   -Llm mock        стенд без модели, на каждом экране плашка — только явно
#   -Llm ollama      локальная модель из темы (llm.generator / llm.verifier), в теме по умолчанию пусто
#   -Llm openrouter  модели из темы (llm.openrouter.*), в теме по умолчанию пусто; ключ OPENROUTER_API_KEY
#
# Ключ OpenRouter: если переменная уже задана — берётся она. Иначе — строка OPENROUTER_API_KEY из файла
# -KeyFrom (по умолчанию .env.local Планёрки, разрешение владельца 03.10.26 «обращаться к тем же ключам»).
# Из файла читается только эта строка; значение не печатается и не пишется на диск.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_dev.ps1 -Theme erp_rollout -Port 8002 -Llm openrouter
param([string]$Theme = "it_product", [int]$Port = 8002, [string]$Db = "data\meetflow.db",
      [ValidateSet("mock", "ollama", "openrouter", "routes")][string]$Llm = "routes",
      [string]$KeyFrom = "$env:USERPROFILE\Documents\ITMO_planerka\webapp\.env.local")
$env:PYTHONIOENCODING = "utf-8"
$env:MEETFLOW_LLM = $Llm
$env:HF_HUB_OFFLINE = "1"
$env:PYANNOTE_METRICS_ENABLED = "false"
# свой .env.local MeetFlow главнее: зависимость от файла Планёрки — только запасной путь (письмо meeting-registry 22)
$own = Join-Path (Split-Path $PSScriptRoot -Parent) ".env.local"
if (-not $PSBoundParameters.ContainsKey("KeyFrom") -and (Test-Path $own)) { $KeyFrom = $own }
# routes: ключ нужен, только если в маршрутах есть точка OpenRouter — в закрытом контуре с локальными моделями его
# нет, и запуск не должен падать (прогон по скиллу 09.10.26)
$routesFile = if ($env:MODEL_ROUTES_PATH) { $env:MODEL_ROUTES_PATH } else { Join-Path (Split-Path $PSScriptRoot -Parent) "data\models.json" }
$needKey = ($Llm -eq "openrouter") -or ($Llm -eq "routes" -and (Test-Path $routesFile) -and
           ((Get-Content -LiteralPath $routesFile -Raw -Encoding UTF8) -match '"kind"\s*:\s*"openrouter"'))
if ($needKey -and -not $env:OPENROUTER_API_KEY -and $Llm -eq "routes" -and -not (Test-Path $KeyFrom)) {
    # в маршрутах ключ можно ввести значением в «Моделях» — без переменной запуск не останавливаем
    Write-Warning "Переменной OPENROUTER_API_KEY нет: точкам OpenRouter нужен ключ значением в «Моделях»."
    $needKey = $false
}
if ($needKey -and -not $env:OPENROUTER_API_KEY) {
    if (-not (Test-Path $KeyFrom)) { Write-Error "Ключ OpenRouter не задан, файла $KeyFrom нет."; exit 2 }
    $line = Get-Content -LiteralPath $KeyFrom -Encoding UTF8 | Where-Object { $_ -match '^\s*OPENROUTER_API_KEY\s*=' } | Select-Object -First 1
    if (-not $line) {
        # routes: ключ можно ввести значением в «Моделях» — без строки в файле запуск не останавливаем
        # (24.10.2026: автозапуск на 8005 падал из-за этого, хотя ключ не нужен)
        if ($Llm -eq "routes") {
            Write-Warning "В $KeyFrom нет строки OPENROUTER_API_KEY: точкам OpenRouter нужен ключ значением в «Моделях»."
        } else {
            Write-Error "В $KeyFrom нет строки OPENROUTER_API_KEY."; exit 2
        }
    } else {
        $env:OPENROUTER_API_KEY = ($line -replace '^\s*OPENROUTER_API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'")
        Write-Host "Ключ OpenRouter взят из $KeyFrom (значение не показывается)."
    }
}
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m meetflow serve --theme $Theme --db $Db --port $Port
