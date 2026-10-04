# MeetingFlow

Инструмент «проект ведётся по совещаниям»: запись или текст встречи превращается в протокол и реестр задач. Всё, что код не решил сам, уходит оператору карточкой, задача при этом не теряется. Модель подключается через OpenRouter или локально (Ollama); распознавание голоса — только локальное.

В репозитории две части одной работы.

| Папка | Что это | С чего начать |
|---|---|---|
| `meetflow/` | **MeetFlow** — основа: ядро, коннекторы, веб-интерфейс, тематики, 516 тестов | `meetflow/README.md`, развёртывание — `meetflow/docs/DEPLOYMENT.md`, открытые задачи оператора — `meetflow/OPERATOR_TODO.md` |
| `meeting-registry/` | **meeting-registry** — скилл и движок реестра, решения владельца, наборы проверки, независимая проверка MeetFlow | `meeting-registry/README.md`, развёртывание — `meeting-registry/DEPLOY.md`, открытые задачи — `meeting-registry/ОТКРЫТЫЕ ЗАДАЧИ — для оператора.md` |

## Быстрая проверка

```bash
git clone https://github.com/MilaTal/MeetingFlow
cd MeetingFlow/meetflow
pip install -e ".[test,morph]"
python -m pytest tests -q                                          # MeetFlow: 514 passed, 2 skipped
cd ../meeting-registry/skill/meeting-registry/engine
python -m pytest tests -q -p no:cacheprovider                      # движок meeting-registry: 119 passed
cd "../../../10_Независимая проверка MeetFlow"
python -m pytest -q -p no:cacheprovider                            # независимая проверка MeetFlow: 62 passed
```

Два пропуска в MeetFlow — тесты К17/К18 на наборе вехи 4, который в репозиторий не входит (переменная `MEETFLOW_SUITE_V2`). Независимая проверка находит MeetFlow в соседней папке `meetflow/` сама; другой путь задаётся переменной `MEETFLOW_PATH`.

## Данные

Ключи (`.env.local`), базы, журналы вызовов и записи встреч в репозиторий не попадают. Имена людей в примерах и тестах вымышленные.
