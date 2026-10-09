# MeetFlow — framework «проект ведётся по совещаниям»

Абстрактная база, выделенная из Проекта ERP и приложения «Планёрка» и сведённая с веткой meeting-registry. Запись или текст встречи превращается в протокол и реестр задач, а всё, что код не решил сам, уходит человеку карточкой. Задача при этом не теряется: если неясно, кто исполнитель, она заводится сразу, а выбор приходит рядом. Тематика задаётся JSON-темой, внешние системы подключаются коннекторами. Модель — через OpenRouter или локально (Ollama), выбор при развёртывании. Распознавание голоса — только локальное.

## Документы

| Файл | Для кого и о чём |
|---|---|
| `docs/DEPLOYMENT.md` | **развёртывание и требования к окружению** |
| `OPERATOR_TODO.md` | **открытые задачи оператора** — что ждёт решения человека |
| `FRAMEWORK_REPORT.md` | итоговый отчёт: что сделано, цифры, уроки |
| `docs/ARCHITECTURE.md` | устройство: слои, конвейер встречи, данные, права |
| `docs/CONNECTOR_SPEC.md`, `docs/PLUGIN_GUIDE.md` | коннекторы и как добавить свой |
| `docs/DESIGN_SYSTEM.md` | дизайн-система и палитры |
| `docs/TEST_LOG.md` | журнал тестов и правок — по каждому письму и решению |
| `docs/METHODOLOGY_10_STEPS.md`, `docs/ERP_DECOMPOSITION.md` | методика курса и разбор исходного проекта |
| `eval/README.md` | наборы проверки ветки meeting-registry |
| `skill/meetflow/` | скилл meetflow: правила разбора встречи, тематика, модели и маршруты, движок `engine/` с тестами и eval (копия; источник — `~/.claude/skills`) |

## Быстрый старт

```bash
pip install -e ".[test,morph]"
python -m pytest tests -q                                   # 516 тестов
python -m meetflow themes                                   # erp_rollout, daily_ops, it_product
python -m meetflow demo --theme it_product --db data/demo.db
python -m meetflow serve --theme it_product --db data/demo.db --port 8002
```

Откройте `http://127.0.0.1:8002` и в левом нижнем углу выберите роль «Супер-админ». Без `MEETFLOW_LLM` работает заглушка модели, на каждом экране висит плашка «Стенд без модели». Работа с моделью: `MEETFLOW_LLM=openrouter` и ключ, или `MEETFLOW_LLM=ollama` — см. `docs/DEPLOYMENT.md`.

На Windows удобнее сценарий запуска:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_dev.ps1 -Theme erp_rollout -Port 8002 -Llm openrouter
```

## Состав

| Путь | Что там |
|---|---|
| `meetflow/core/` | ядро: типы, проверки кодом (шлюз задачи, кодовые проверки черновика), правило отрицаний и морфология, люди и «Команда», даты, вид источника, реестр, карточки, память оператора, потолки, промпты, безопасность, конвейер, единицы встречи, Дорожная карта, поиск, приём из папки, сводка прогонов |
| `meetflow/connectors/` | текст, docx, Whisper (локально), Vision (Ollama), модель через Ollama и через OpenRouter, заглушка модели, выгрузка md и docx, папка-приёмник, база голосов, реестр плагинов |
| `meetflow/web/` | FastAPI и интерфейс без сборки |
| `themes/` | `_default` и три тематики |
| `tests/` | 516 тестов: функциональные, безопасность, нагрузка, по каждому письму сведения |
| `eval/` | наборы проверки и cost-атаки (ветка meeting-registry) |
| `scripts/` | запуск сервера и тестов |

## Зависимости

Python 3.11+ (проверено на 3.13). Обязательные — fastapi, uvicorn, pydantic, python-docx, python-multipart, httpx. Необязательные:
- pymorphy3 — признак выполнения по форме глагола;
- faster-whisper и imageio-ffmpeg — распознавание записей; без них записи ждут.

Сборки фронтенда нет. CI только локальный (`Makefile`, `scripts/run_tests.*`); GitHub Actions запрещён манифестом проекта.
