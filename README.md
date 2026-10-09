# MeetingFlow

Инструмент «проект ведётся по совещаниям»: запись или текст встречи превращается в протокол и реестр задач. Всё, что код не решил сам, уходит оператору карточкой, задача при этом не теряется. Модели подключаются маршрутами — у генерации, проверки и распознавания речи своя цепочка точек с переходом на запасную; локально (Ollama, LM Studio) или через OpenRouter. Распознавание голоса — только локальное или в сервисе внутренней сети.

В репозитории две части одной работы и один скилл.

| Папка | Что это | С чего начать |
|---|---|---|
| `meetflow/` | **MeetFlow** — основа: ядро, коннекторы, веб-интерфейс, тематики, маршруты моделей и пульт «Модели», 540 тестов | `meetflow/README.md`, развёртывание — `meetflow/docs/DEPLOYMENT.md`, открытые задачи оператора — `meetflow/OPERATOR_TODO.md` |
| `meetflow/skill/meetflow/` | **Скилл meetflow** (с 09.10.26 — один вместо meetflow-project и meeting-registry): правила разбора встречи, тематика, модели и маршруты, движок `engine/` с тестами и наборами eval, приведённый к решениям владельца | `meetflow/skill/meetflow/SKILL.md`, разборы с числами — `СЛУЧАИ.md`, контракты — `references/контракты.md` |
| `meeting-registry/` | **meeting-registry** — эталон состояния на 03.10.26: паспорт агента, решения владельца, журналы, независимая проверка MeetFlow. Скилл отсюда заменён скиллом meetflow | `meeting-registry/README.md`, открытые задачи — `meeting-registry/ОТКРЫТЫЕ ЗАДАЧИ — для оператора.md` |

## Быстрая проверка

```bash
git clone https://github.com/MilaTal/MeetingFlow
cd MeetingFlow/meetflow
pip install -e ".[test,morph]"
python -m pytest tests -q                                          # MeetFlow: 540 passed, 2 skipped
cd skill/meetflow/engine
python -m pytest tests -q -p no:cacheprovider                      # движок скилла meetflow: 123 passed
python eval/run_eval.py --label проверка --set cases               # наборы eval: 15 из 15, cases_live 12 из 12, cases_blind 7 из 10
cd "../../../../meeting-registry/10_Независимая проверка MeetFlow"
python -m pytest -q -p no:cacheprovider                            # независимая проверка MeetFlow: 62 passed
```

Два пропуска в MeetFlow — тесты К17/К18 на наборе вехи 4, который в репозиторий не входит (переменная `MEETFLOW_SUITE_V2`). Слепой набор движка без модели — 7 из 10: три пропущенных поручения, ложных записей ноль. Независимая проверка находит MeetFlow в соседней папке `meetflow/` сама; другой путь задаётся переменной `MEETFLOW_PATH`.

## Данные

Ключи (`.env.local`), базы, рабочие файлы маршрутов (`data/models.json`), журналы вызовов и записи встреч в репозиторий не попадают. Ключ в маршрутах — только имя переменной окружения. Имена людей в примерах и тестах вымышленные.
