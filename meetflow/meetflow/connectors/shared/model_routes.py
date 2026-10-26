# -*- coding: utf-8 -*-
"""Маршруты моделей: какие серверы моделей у системы есть, кто какую роль играет и куда уходить, если сервер лёг.

Решение владельца 09.10.26: модели не должны быть жёстко вшиты в переменные окружения — на проде нужно быстро
переключиться, если какая-то модель недоступна. Файл одинаков до байта в Планёрке
(`webapp/app/services/model_routes.py`) и в ERP (`system/scripts/model_routes.py`) — это держат тесты-сторожа.

Устройство — по образцу маршрутизаторов моделей в агентных системах (LiteLLM Router, OpenRouter fallbacks,
шлюзы моделей): у каждой РОЛИ — генерация, проверка — упорядоченная цепочка ИМЕНОВАННЫХ точек; первая
доступная обслуживает вызов. Точка, которая не ответила (нет связи, 5xx/429 после повторов, модель молчит или
выгружена), выводится из цепочки на время охлаждения — «предохранитель» (circuit breaker), — и вызов уходит на
следующую. Ошибка самого запроса (400, неверный ключ) на другую точку не переносится: она повторится и там.

Файл маршрутов — `models.json` (путь — переменная MODEL_ROUTES_PATH, иначе `data/models.json` продукта). Он
перечитывается при изменении — переключение без перезапуска. Ключи в файле не хранятся, только ИМЯ переменной
окружения с ключом (или ключ значением, см. ниже).

Нет тихой подстановки модели (решение владельца 16.10.26, Д2; правило 13.10.26 «у роли нет модели по умолчанию»). Файла
нет, он не читается или в нём у роли генерации или проверки нет точки — роль «не настроена»: `chain` поднимает
`RoleNotConfigured` («модель не настроена — назначьте в «Моделях»»), продукт не делает ни одного вызова, сборка встаёт
карточкой «Ожидает ввода», пульт «Модели» показывает причину (`not_configured`). Переменные окружения (LLM_PROVIDER,
QWEN_MODEL, QWEN_VERIFY_MODEL, LLM_BASE_URL, OPENROUTER_API_KEY…) модель роли больше не задают: до 16.10.26 без файла
маршрут собирался из них, и сборка молча шла на модель, которую в «Моделях» никто не назначал. Исключение владельца
13.10.26 остаётся: у проверки без своей точки — точки генерации, назначенные в «Моделях»; пульт показывает это явно
(`inherited`). Распознавание речи (роль `asr`) этим не затронуто: без своей точки — как раньше, WEBAPP_WHISPER_MODEL
на этой машине. Файла нет — пульт начинает его с пустого: первое подключение и назначение роли создают models.json.

Роль «Договорённости (отдельный вызов)» — `agreements` (решение владелицы 18.10.2026, «надо доработать выбор модели»):
назначается в пульте «Модели», как остальные; без своей точки идёт на точки генерации («как у черновика», `inherited`),
других ролей не подменяет. Последнюю точку из неё можно убрать — роль снова «как у черновика». Роль необязательная
(`OPTIONAL_ROLES`): пульт показывает её, если продукт её включил (`show_role` — Планёрка, с 19.10.2026 и ERP —
`legacy_bridge`) или она уже есть в файле. Пробный запрос перед сборкой опрашивает её точку, если роль назначена.

Формат:
    {
      "endpoints": {
        "or-qwen-plus":  {"kind": "openrouter", "model": "qwen/qwen-plus", "key_env": "OPENROUTER_API_KEY"},
        "lmstudio-27b":  {"kind": "openai", "url": "http://192.168.100.59:1234", "model": "qwen3.8-27b"},
        "ollama-muse":   {"kind": "openai", "url": "http://172.21.21.30:11434", "model": "muse-glimmer"}
      },
      "roles": {
        "generate": ["or-qwen-plus", "lmstudio-27b"],
        "verify":   ["ollama-muse", "or-muse"]
      },
      "cooldown_sec": 300
    }

Распознавание речи — роль `asr` (решение владельца 09.10.26). Её точки — не модели на сервере, а то, ЧЕМ распознаём,
на этой же машине (голос не покидает периметр, облачных точек у роли нет):
    "whisper-gpu":  {"kind": "faster-whisper", "model": "large-v3", "device": "cuda"}
    "whisper-cpu":  {"kind": "faster-whisper", "model": "D:/models/whisper-large-v3", "device": "cpu"}
    "свой-движок":  {"kind": "python", "callable": "мой_пакет.asr:transcribe"}
`model` у faster-whisper — имя («large-v3», папка ищется в VOICE_MODELS_DIR) или путь к папке модели; `device` —
auto (видеокарта, при сбое процессор), cuda или cpu. `python` — ссылка на код «модуль:функция»: функция получает путь
к wav и параметры (language, initial_prompt, hotwords, …) и возвращает (текст, сводка). Роли `asr` в файле нет —
распознавание как раньше, по WEBAPP_WHISPER_MODEL.
Ещё два рода точек распознавания (просьба владельца 09.10.26 — «другая модель или ссылка на адрес, где лежит код»):
    "свой-движок":  {"kind": "python", "callable": "asr_engine:transcribe", "path": "D:/asr/код"}
    "сервис-asr":   {"kind": "asr-service", "url": "http://192.168.100.60:9000/transcribe"}
`path` — папка с кодом, если он не установлен пакетом. `asr-service` — сервис распознавания во внутренней сети:
ему уходит wav (POST, audio/wav, параметры — в строке запроса), он отвечает JSON {"text": …, "meta": {…}}. Адрес
только внутренний (localhost, 10.*, 172.16–31.*, 192.168.*, имя без точки или *.local): голос не покидает периметр.

Справочник и работа оператора (09.10.26, по образцу шлюзов моделей — LiteLLM, Portkey, Kong/Envoy AI Gateway):
- подключение заводится заранее, даже без адреса — заготовка «не настроена» в роль не попадает;
- порядок оператора: заполнить → «Проверить связь» до сохранения → сохранить → сделать основной или запасной;
- ключ — только имя переменной окружения; значение, похожее на сам ключ, файл не принимает;
- каждое изменение кладёт прежнюю версию в `models.history/` рядом с файлом, «Откатить» возвращает её;
  в `models.log.jsonl` — когда, что и кто.

Ключ значением (решение владельца 14.10.26, обходной путь для сборки протоколов внешней моделью). У точки рода
openai или openrouter поле `key_source`: `env` (по умолчанию — ключ в переменной окружения `key_env`, как раньше)
или `value` — сам ключ ввёл супер-администратор в «Моделях». Значение лежит в отдельном файле
`model_keys.local.json` рядом с models.json, а не в нём: в models.history/ и в журнал ключ не попадает, «Откатить»
его не трогает. Наружу ключ не отдаётся никогда — только «ключ задан · …XXXX»; из текстов ошибок и журналов его
вычищает `scrub`. Внешняя точка (openrouter; openai/ollama с адресом вне внутренней сети) ходит через системный
прокси (`proxy`: system по умолчанию или none), локальные — мимо прокси. Роль `asr` внешнюю точку не принимает
ни при какой записи и ни при загрузке файла: голос не покидает периметр.

Прокси точки адресом (решение владельца 16.10.26: Claude с локальной машины доступен только через прокси компании,
а прокси для всей Windows или в .env.local не включаем). Третье значение поля `proxy` — сам адрес прокси,
`http://хост:порт` или `https://хост:порт`, например `http://172.17.17.97:3128`. Через него идут только запросы этой
точки: рабочий вызов, пробный запрос перед сборкой, «Проверить связь»; остальные точки и весь прочий процесс — как
раньше. Список обхода системных настроек к адресу точки не применяется. Адрес с логином и паролем, с путём или без
порта — отказ при загрузке и записи файла: «прокси с паролем не поддерживается». Точка во внутренней сети ходит
напрямую, даже если адрес прокси у неё задан: адрес не ломает запись, но к своей машине не применяется. У точек
распознавания прокси-адреса нет. В форме «Моделей» — вариант «адрес» и строка `proxy_url`, файл хранит сам адрес.

Рассуждение модели у внешней точки (решение владельца 14.10.26): поле `reasoning` у точки рода openai —
`auto` (умолчание, поле не отправляется) или `none` — выключить рассуждение, чтобы ход мысли не съедал потолок
ответа (`reasoning_effort: "none"`, проверено на DeepSeek). Моделям с обязательным рассуждением (`muse`) опция
не подставляется: см. `reasoning_effort` ниже. Та же опция у точки openrouter — её прежним способом,
`reasoning: {"enabled": false}`; в пробном запросе и «Проверить связь» — тем же телом (`reasoning_body`). Значение,
кроме auto и none, и none у muse — отказ при загрузке и записи файла, как у остальных полей.
С 15.10.26 (решение владельца) ещё два значения: `low` и `high` — ход мысли короче или полностью. У openai — тело
`reasoning_effort: "low"` / `"high"` (у DeepSeek по документации effort бывает low/high/max, по умолчанию high), у
openrouter — `reasoning: {"effort": …}` поверх настройки продукта (`apply_reasoning`). У muse `none` по-прежнему
нельзя, `low` и `high` — можно: это не выключение. Рассуждение тратит тот же потолок ответа — при low/high потолок
у точки (`max_tokens`) стоит задать побольше.

Claude по ключу через OpenAI-совместимый адрес Anthropic (15.10.26; документация
platform.claude.com/docs/en/api/openai-sdk, проверено 15.10.2026). У Claude 4.7 и новее `temperature` ниже 1 и `top_p`
кроме 0,99 — ответ 400, оба поля вместе — тоже 400, а продукты шлют temperature 0–0,2 во всех вызовах: ни один вызов
не прошёл бы. Поэтому у модели Claude (имя начинается с `claude-` или содержит `anthropic/claude`, как у OpenRouter) на
точке openai и openrouter оба поля из тела убираются — `apply_model_limits`, в рабочем вызове, пробном запросе и
«Проверить связь». Новой настройки у точки нет: решает имя модели. Поле `reasoning_effort` адрес Anthropic молча не
читает (рассуждение у Claude 5.x включено по умолчанию, у claude-opus-5-5 не выключается вовсе), так что low/high/none
там — видимость управления. У точки с адресом на api.anthropic.com `reasoning`, кроме auto, — отказ при загрузке и
записи файла, а `reasoning_effort` такой точке поле не отдаёт. У OpenRouter с моделью Claude рассуждение прежнее: у
него свой формат. `response_format` адрес тоже не читает, кэш подсказок через него не работает (цена из кэша = цене
входа, см. справочник в `llm_cost`).

С 26.10.2026 точка с адресом api.anthropic.com ходит в родной Messages API (`/v1/messages`), а не в OpenAI-совместимый
вход (отчёт ЛМ «Claude/Sonnet: пробы прошли, генерация пустая»: черновик 12.10 на claude-sonnet-5-5 — 134 422 знака
входа, 0 знаков ответа, completion_tokens 32 000, finish_reason length, 0,446 $; скрытое рассуждение при усилии `high` по
умолчанию съело весь потолок). Совместимый вход усилием не управляется, а родной принимает `output_config.effort`
(skill claude-api, разделы Thinking & Effort и Migrating to Claude Sonnet 5.5 → Choosing an effort level: `low` для
генерации текста и извлечения; там же — не опираться на OpenAI-совместимые прослойки). Тело продукта остаётся прежним,
перевод — в одном месте, `wire_request`: системная подсказка — полем `system`, ключ — в `x-api-key`, заголовок
`anthropic-version`, усилие — `CLAUDE_EFFORT_DEFAULT` (`low`) или переменная `LLM_CLAUDE_EFFORT`; temperature, top_p,
stream_options, reasoning_effort, response_format не уходят; `thinking` не задаётся (адаптивное по умолчанию, `disabled`
у Sonnet 5.5 и Opus 5.5 — 400). Поток Messages API понимает `stream_piece`, расход в словах OpenAI — `normalize_usage`.

Переход на запасную модель (задание владелицы 20.10.2026, «закончились лимиты на дипсик — система бы переключилась?»).
Запасная — вторая точка роли («Добавить запасной»), назначает администратор, по умолчанию её нет: правило 13.10.26 не
нарушается, молчаливой подстановки нет. Переход — только по недоступности основной (402, 401, 403, 404, 429 и 5xx после
повторов, таймаут, отказ соединения); не-формат и 400 — не переход. О переходе продукт говорит строкой «Основная модель
недоступна (причина), работа идёт на запасной «…»» — один раз за срыв (`fallback_notice`), в журнале вызовов строка
ответа запасной несёт `role` и `fallback_from` (`fallback_of`). Через охлаждение (`cooldown_sec`) вызовы снова идут на
основную; ответила — `mark_up`, следующий срыв снова даст строку.

Роль «Досмотр реплик к системе» — `guard` (решение владелицы 20.10.2026, «да»): второй слой защиты от реплик,
обращённых к программе. Необязательная, генерацию не наследует: без своей точки «не настроена», и работают только
правила. Модель видит только предложения, которые правила сочли подозрительными, и отвечает ДА/НЕТ (потолок ответа —
`GUARD_MAX_TOKENS_CEILING`).

Пробный запрос перед сборкой (решение владельца 14.10.26): перед сборкой Протокола и Плана первой доступной точке
роли уходит настоящее начало первого запроса сборки — о неготовой модели известно сразу, а не после 25–36 минут
повторов; готова — по первому признаку жизни. Настройки — раздел "probe" в файле (рядом с cooldown_sec) или
переменные MODEL_PROBE*; first_sign_sec не задан — берётся порог молчания сборки:
    "probe": {"enabled": true, "first_sign_sec": 600, "fresh_sec": 600, "max_tokens": 64}
Подробно — у `probe_settings` и `probe_role` ниже.

Вырожденный ответ (сбой пересборки 14.10.26, отчёт локальной машины): «deepseek-flash» на проверке черновика отдал
278 077 знаков и упёрся в потолок точки (96 000 токенов) — нормальный ответ любого шага в десятки раз короче, и потолок
точки один на все шаги. Поток ответа проверяется на зацикливание (`degenerate_loop`): один и тот же абзац или блок
абзацев подряд не меньше LOOP_MIN_REPEATS раз и на LOOP_MIN_CHARS знаков (отличающиеся только числами — «№ 12», «№ 13» —
не меньше LOOP_MIN_REPEATS_DIGITS раз). Найдено — чтение обрывается (платить за остаток не за что), одна повторная попытка с `LOOP_REMINDER`, снова
зациклилось — шаг останавливается карточкой «модель ответила не в формате», без новых платных попыток. Оба продукта
зовут одну функцию.

Переключение: поменять порядок в `roles` (первая — основная) или командой
    python model_routes.py show [--path data/models.json] — роли, точки, состояние предохранителей
    python model_routes.py use generate lmstudio-27b  — поставить точку первой в роли
    python model_routes.py check                      — короткий запрос на каждую точку
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import zlib
import uuid
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:   # стоимость вызова и тарифы точек (15.10.26) — общий модуль рядом, одинаковый до байта в обоих продуктах
    from . import llm_cost       # Планёрка: модуль в пакете app.services
except ImportError:
    import llm_cost              # ERP и scripts/: модуль лежит рядом, папка в sys.path

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
KINDS = ("openrouter", "openai", "ollama")
ASR_KINDS = ("faster-whisper", "python", "asr-service")   # распознавание — на этой машине или во внутренней сети
CODE_ASR_KINDS = ("python", "asr-service")                 # распознаёт чужой движок: функция или сервис
ROLES = ("generate", "verify", "asr", "agreements", "guard")
ROLE_TITLES = {"asr": "Распознавание речи", "generate": "Генерация черновика", "verify": "Проверка черновика",
               "agreements": "Договорённости (отдельный вызов)", "guard": "Досмотр реплик к системе"}
# Роли, которые без своей точки идут на точки генерации: проверка (исключение владельца 13.10.26) и договорённости
# (решение владелицы 18.10.2026: отдельный вызов договорённостей, своя модель назначается в «Моделях», не назначена —
# «как у черновика»). Других ролей это не касается: генерация без точки — «не настроена», распознавание — по переменной.
INHERIT_GENERATE = ("verify", "agreements")
# Роли сверх трёх основных показываются в пульте, только если продукт их включил (`show_role`) или они уже есть в файле:
# файл одинаков до байта в Планёрке и ERP, а договорённости пока есть только в Планёрке (18.10.2026).
# «Досмотр» (guard, решение владелицы 20.10.2026) — тоже необязательная, но НЕ наследует генерацию: без своей точки она
# «не настроена», и реплики к системе разбирают только правила (`repliki_k_sisteme`), как до 20.10.
OPTIONAL_ROLES = ("agreements", "guard")
_shown_roles: set[str] = set()
_BASE_KEYS = ("kind", "model", "url", "key_env")
DEFAULT_COOLDOWN_SEC = 300
HISTORY_KEEP = 30
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEYS_FILE = "model_keys.local.json"        # ключи значением — рядом с models.json, в git и выгрузки не идут
KEY_SOURCES = ("env", "value")              # имя переменной окружения или само значение (14.10.26)
PROXY_MODES = ("system", "none")            # внешняя точка: через системный прокси (по умолчанию) или напрямую
PROXY_ADDRESS = "address"                   # третий вариант формы (16.10.26): в файле вместо него — сам адрес прокси
PROXY_CHOICES = PROXY_MODES + (PROXY_ADDRESS,)
PROXY_HINT = "http://172.17.17.97:3128"
REASONING_MODES = ("auto", "low", "high", "none")   # как у модели (умолчание), low, high (15.10.26), выключено (14.10.26)
REASONING_EFFORTS = ("low", "high")
REASONING_MANDATORY = ("muse",)             # у этих рассуждение обязательное — опцию им не передаём (ответят 400)
REASONING_KINDS = ("openai", "openrouter")  # у ollama и распознавания этого поля нет
# Claude по ключу (15.10.26): адрес Anthropic reasoning_effort не читает; у моделей Claude temperature ниже 1 и top_p — 400
ANTHROPIC_HOSTS = ("api.anthropic.com",)
SAMPLING_FIELDS = ("temperature", "top_p")
_REASONING_FIELD = {"key": "reasoning", "label": "Рассуждение модели", "choices": list(REASONING_MODES),
                    "choice_titles": {"auto": "как у модели (по умолчанию)",
                                      "low": "понемногу (low) — ход мысли короче",
                                      "high": "полностью (high)",
                                      "none": "выключено — весь потолок ответа уходит на ответ"},
                    # подсказка под списком в пульте «Модели» (14.10.26; low/high — 15.10.26)
                    "help": "выключено — модель отвечает сразу, без хода мысли; весь потолок ответа уходит на ответ. "
                            "Для DeepSeek проверено. Для muse нельзя. Рассуждение тратит тот же потолок ответа — "
                            "при low/high задайте потолок у точки побольше"}
# Тариф точки (решение владельца 15.10.26): цены за 1 млн токенов и часы пик — в поле `tariff` точки. В форме — две
# строки; пустые — у точки своего тарифа нет, и для модели из справочника открытых прейскурантов берётся он.
_TARIFF_FIELDS = (
    {"key": "tariff_prices", "label": "Тариф, $ за 1 млн токенов: вход / из кэша / выход", "hint": "0,15 / 0,003 / 0,60",
     "tariff": True,
     "help": "Нужен, если поставщик не возвращает цену вызова (DeepSeek). Пусто — для модели из справочника берётся "
             "открытый прейскурант поставщика, иначе стоимость не считается («тариф не задан»)."},
    {"key": "tariff_peak", "label": "Часы пик, UTC, понедельник–пятница: промежутки и множитель", "hint": "1-4, 6-10 ×2",
     "tariff": True, "help": llm_cost.ПОДСКАЗКА_ПИКА},
)
# Потолок ответа у точки (решение владельца 15.10.26): действует на всех шагах этой точки вместо таблицы потолков по
# шагам и переменных LLM_MAX_TOKENS_<ШАГ> — может и поднять, и опустить (DeepSeek 96 000, qwen с окном 32 768 — 8 000).
# Пусто — как раньше, по умолчанию системы. Пробный запрос свой предел (64) не меняет.
_MAX_TOKENS_FIELD = {"key": "max_tokens", "label": "Потолок ответа, токенов — если у сервера свой предел", "hint": "16384",
                     "help": "потолок ответа для этой модели на всех шагах; пусто — по умолчанию системы"}
# Предел расхода в месяц (решение владельца 15.10.26): по поставщику, а не общий. Задан у точки — действует на всех
# точки того же поставщика; у OpenRouter без предела у точки — прежний бюджет из переменной окружения
# OPENROUTER_WORKSPACE_BUDGET_USD, если она задана. Чисел в коде нет: не задан — только счёт.
_MONTH_LIMIT_FIELD = {"key": "month_limit_usd", "label": "Предел расхода в месяц, $ — по поставщику", "hint": "20",
                      "tariff": True,
                      "help": "Пусто — система только считает и показывает потраченное. Задан — на 90 % предупреждение, "
                              "на 100 % платные вызовы этого поставщика останавливаются до следующего месяца; другие "
                              "поставщики работают. Предел один на поставщика: у нескольких его точек берётся меньший."}
OPENROUTER_BUDGET_ENV = "OPENROUTER_WORKSPACE_BUDGET_USD"
KEY_MAX_LEN = 400
HIDDEN = "[ключ скрыт]"
_KEY_FIELDS = (
    {"key": "key_source", "label": "Ключ", "choices": list(KEY_SOURCES),
     "choice_titles": {"env": "имя переменной окружения", "value": "значение"}},
    {"key": "proxy", "label": "Прокси — для внешней точки", "choices": list(PROXY_CHOICES),
     "choice_titles": {"system": "системный", "none": "без прокси", PROXY_ADDRESS: "адрес"},
     # вариант «адрес» (16.10.26): строка ввода адреса — поле proxy_url формы, в файл идёт сам адрес в proxy
     "address_key": "proxy_url", "address_hint": PROXY_HINT,
     "address_help": f"например {PROXY_HINT} — прокси компании; через него пойдут только вызовы этой точки"},
)
# Подсказки адреса внешнего OpenAI-совместимого поставщика; адрес — без /v1, как у своего сервера.
EXTERNAL_URL_HINTS = [
    {"title": "OpenRouter", "url": "https://openrouter.ai/api"},
    {"title": "DeepSeek", "url": "https://api.deepseek.com"},
    {"title": "Alibaba DashScope (qwen-plus)", "url": "https://dashscope-intl.aliyuncs.com/compatible-mode"},
    {"title": "OpenAI", "url": "https://api.openai.com"},
    {"title": "Z.ai (GLM), международный", "url": "https://api.z.ai/api/paas/v4"},
    {"title": "Anthropic (Claude)", "url": "https://api.anthropic.com"},
]

# Формат звука, который точка `asr-service` отправляет сервису (26.10.2026): расширение файла, тип, кодек ffmpeg.
# wav — по умолчанию, как было; m4a и ogg — сжатие перед отправкой. Повод — отчёт локальной машины 26.10.2026: «Транс»
# закрывал соединение на wav 16 кГц с подсказкой и принимал тот же отрезок в m4a с той же подсказкой.
АУДИО_ФОРМАТЫ = {
    "wav": (".wav", "audio/wav", None),
    "m4a": (".m4a", "audio/mp4", ["-c:a", "aac", "-b:a", "64k"]),
    "ogg": (".ogg", "audio/ogg", ["-c:a", "libopus", "-b:a", "32k"]),
}
# Поля подсказки распознаванию: длинный текст, в строку запроса по умолчанию не идёт (26.10.2026)
ПОДСКАЗКА_ПОЛЯ = ("initial_prompt", "hotwords")

# Что оператор заполняет у точки каждого рода. По этому описанию панель строит форму «Подключение» — новый род
# появляется в форме сам, без правки экрана.
KIND_FIELDS = {
    "openai": {"title": "Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1) или внешний поставщик",
               "for": "text", "url_hints": EXTERNAL_URL_HINTS,
               "fields": [{"key": "url", "label": "Адрес сервера, без /v1 (если путь поставщика с номером версии, как у Z.ai …/paas/v4, — целиком)", "hint": "http://192.168.100.59:1234", "required": True},
                          {"key": "model", "label": "Модель на сервере", "hint": "deepseek-flash", "required": True},
                          _KEY_FIELDS[0],
                          {"key": "key_env", "label": "Переменная окружения с ключом, если сервер его просит", "hint": "LLM_API_KEY"},
                          _KEY_FIELDS[1],
                          _REASONING_FIELD, _MAX_TOKENS_FIELD, *_TARIFF_FIELDS, _MONTH_LIMIT_FIELD]},
    "ollama": {"title": "Ollama, родной протокол", "for": "text",
               "fields": [{"key": "url", "label": "Адрес сервера", "hint": "http://localhost:11434", "required": True},
                          {"key": "model", "label": "Модель", "hint": "qwen3:8b", "required": True},
                          _MAX_TOKENS_FIELD]},
    "openrouter": {"title": "OpenRouter — облако, только для текста", "for": "text",
                   "fields": [{"key": "model", "label": "Модель OpenRouter", "hint": "qwen/qwen-plus", "required": True},
                              _KEY_FIELDS[0],
                              {"key": "key_env", "label": "Переменная окружения с ключом", "hint": "OPENROUTER_API_KEY", "default": "OPENROUTER_API_KEY"},
                              _KEY_FIELDS[1], _REASONING_FIELD, _MAX_TOKENS_FIELD, *_TARIFF_FIELDS, _MONTH_LIMIT_FIELD]},
    "faster-whisper": {"title": "Whisper на этой машине (faster-whisper)", "for": "asr",
                       "fields": [{"key": "model", "label": "Модель: имя или путь к папке", "hint": "large-v3 или D:/models/whisper-large-v3", "required": True},
                                  {"key": "device", "label": "Устройство", "choices": ["auto", "cuda", "cpu"], "default": "auto"}]},
    "python": {"title": "Свой код распознавания на этой машине", "for": "asr",
               "fields": [{"key": "callable", "label": "Функция: модуль:функция", "hint": "asr_engine:transcribe", "required": True},
                          {"key": "path", "label": "Папка с кодом, если код не установлен пакетом", "hint": "D:/asr/engine"}]},
    "asr-service": {"title": "Сервис распознавания во внутренней сети", "for": "asr",
                    "fields": [{"key": "url", "label": "Адрес сервиса (только внутренняя сеть)", "hint": "http://192.168.100.60:9000/transcribe", "required": True},
                               {"key": "form", "label": "Форма запроса", "choices": ["raw", "multipart"],
                                "default": "raw",
                                "hint": "raw — wav телом, параметры в строке (прежний протокол); multipart — поля формы и file (audioCintezPro /transcribe)"},
                               # 26.10.2026 (отчёт локальной машины: «Транс» рвёт wav 16 кГц + подсказка, m4a + подсказка принимает)
                               {"key": "audio", "label": "Звук для сервиса", "choices": list(АУДИО_ФОРМАТЫ),
                                "default": "wav",
                                "hint": "wav — как раньше; m4a или ogg — сжать ffmpeg перед отправкой (в 5–10 раз меньше)"},
                               {"key": "prompt_in", "label": "Подсказка распознаванию при форме raw", "choices": ["form", "query"],
                                "default": "form",
                                "hint": "form — подсказка и запись полями формы (в строку запроса подсказка не идёт); query — подсказка в строке запроса, как до 26.10.2026"}]},
}


_ВЕРСИЯ_В_АДРЕСЕ = re.compile(r"/v\d+$")


def api_base(url: str) -> str:
    """База OpenAI-совместимого API: к адресу без номера версии дописывается /v1 (свой сервер, DeepSeek), адрес,
    который уже кончается номером версии, берётся как есть — у Z.ai (GLM) путь https://api.z.ai/api/paas/v4, и /v1
    поверх давал бы 404 (14.10.26). Так же принимается адрес своего сервера, вписанный с /v1."""
    база = (url or "").strip().rstrip("/")
    return база if _ВЕРСИЯ_В_АДРЕСЕ.search(база) else база + "/v1"


@dataclass(frozen=True)
class Route:
    name: str
    kind: str                      # openrouter | openai (свой OpenAI-совместимый сервер) | ollama (родной протокол)
    model: str | None              # None — модель берёт вызывающий (режим «из переменных»)
    url: str = ""                  # база сервера без /v1; для openrouter не нужна
    key_env: str = ""              # имя переменной окружения с ключом, не сам ключ
    from_env: bool = False         # маршрут собран из переменных окружения, файла нет
    options: tuple = ()            # прочие поля точки (device, callable…) — парами, чтобы точка оставалась неизменной

    def opt(self, key: str, default=None):
        return dict(self.options).get(key, default)

    @property
    def endpoint(self) -> str:
        if self.kind in ASR_KINDS:
            return ""
        if self.kind == "openrouter":
            return OPENROUTER_URL
        if self.kind == "ollama":
            return self.url.rstrip("/") + "/api/chat"
        if messages_api(self):
            return api_base(self.url) + "/messages"   # родной Messages API у точки Anthropic (26.10.2026)
        return api_base(self.url) + "/chat/completions"

    @property
    def api_key(self) -> str:
        """Ключ для вызова модели. Только для заголовка запроса: в ответы API, журналы и тексты не идёт."""
        if self.opt("key_source") == "value":
            return key_get(self.name)
        return os.environ.get(self.key_env, "") if self.key_env else ""

    @property
    def is_openrouter(self) -> bool:
        return self.kind == "openrouter"

    @property
    def external(self) -> bool:
        """Точка за пределами контура компании — по роду и адресу, а не флажком: пометке нельзя солгать."""
        return is_external({"kind": self.kind, "url": self.url})

    @property
    def uses_proxy(self) -> bool:
        """Внешняя точка ходит через системный прокси или прокси точки (если не выключен у точки); локальная — мимо."""
        return self.external and self.opt("proxy", "system") != "none"

    @property
    def proxy_address(self) -> str:
        """Адрес прокси этой точки (16.10.26); пусто — системный, без прокси или точка во внутренней сети."""
        value = str(self.opt("proxy", "") or "")
        return value if self.external and value.startswith(("http://", "https://")) else ""

    @property
    def label(self) -> str:
        """Для текстов ошибок: «OpenRouter вернул…», «http://… (lmstudio-27b) вернул…»."""
        if self.kind == "openrouter":
            return "OpenRouter" if self.from_env else f"OpenRouter ({self.name})"
        if self.kind in ASR_KINDS:
            return f"{self.opt('callable') or self.model or self.url or 'распознавание'} ({self.name})"
        return f"{self.url} ({self.name})"


@dataclass
class _State:
    path: Path | None = None
    mtime: float | None = None
    data: dict = field(default_factory=dict)
    default_provider: str = "openrouter"            # LLM_PROVIDER по умолчанию у продукта (ERP — ollama)
    asr_check: object = None                        # проверка модели распознавания продуктом: (модель) -> (ok, почему)
    down_until: dict = field(default_factory=dict)   # имя точки -> время, до которого она выведена
    last_error: dict = field(default_factory=dict)   # имя точки -> текст последней ошибки
    probe_ok: dict = field(default_factory=dict)     # (точка, адрес, модель) -> время удачного пробного запроса
    noticed: set = field(default_factory=set)        # (роль, основная) — о переходе на запасную уже сказано (20.10.2026)


_state = _State()
_lock = threading.RLock()   # mark_down → cooldown_sec → _load берут его повторно


class RoutesError(RuntimeError):
    """Файл маршрутов неверен: ошибка понятна человеку, а не трассировкой."""


def routes_path() -> Path | None:
    explicit = os.environ.get("MODEL_ROUTES_PATH", "").strip()
    if explicit:
        return Path(explicit)
    return None


def configure(path: Path, default_provider: str, asr_check=None) -> None:
    """Продукт сообщает, где у него `data/models.json` (если MODEL_ROUTES_PATH не задан), какой LLM_PROVIDER у
    него по умолчанию — у Планёрки openrouter, у ERP ollama, — и чем проверять модель распознавания."""
    _state.path = Path(path)
    _state.default_provider = default_provider
    if asr_check is not None:
        _state.asr_check = asr_check


def _current_path() -> Path | None:
    return routes_path() or _state.path


def _internal_url(url: str) -> bool:
    """Адрес во внутренней сети: localhost, частные диапазоны, имя без точки или *.local / *.lan / *.internal."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host == "localhost" or "." not in host or host.endswith((".local", ".lan", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def is_external(ep: dict) -> bool:
    """Внешняя точка — за пределами контура: openrouter всегда; openai и ollama — если адрес не внутренний.
    Точки распознавания внешними не бывают: asr-service принимается только с внутренним адресом."""
    kind = ep.get("kind")
    if kind == "openrouter":
        return True
    if kind in ("openai", "ollama"):
        url = str(ep.get("url") or "")
        return bool(url) and not _internal_url(url)
    return False


# --- Сеть: внешние точки — через системный прокси, локальные — мимо (14.10.26) ---------------------------------
# Запрос к модели помечается `mark_request`; общий открыватель urllib смотрит на пометку. Непомеченные запросы
# (всё остальное в процессе) идут как раньше — обычным ProxyHandler по системным настройкам.

class _ProxyByRoute(urllib.request.ProxyHandler):
    # Прокси точки адресом (16.10.26): запрос, помеченный `_model_routes_proxy`, идёт на адрес точки, а не на
    # системный прокси. Системного прокси может не быть вовсе — тогда у ProxyHandler нет http_open/https_open, и
    # ставим их сами: непомеченные запросы проходят мимо, как и раньше.
    def __init__(self, proxies=None):
        super().__init__(proxies)
        for вид in ("http", "https"):
            if вид not in self.proxies:
                setattr(self, f"{вид}_open", lambda r, вид=вид: self._point_open(r, вид))

    def proxy_open(self, req, proxy, type):  # noqa: A002 — подпись urllib
        if getattr(req, "_model_routes_proxy", None):
            return self._point_open(req, type)   # у точки свой прокси — системный и его список обхода не нужны
        if getattr(req, "_model_routes_direct", False):
            return None                       # мимо прокси: следующий обработчик откроет соединение напрямую
        return super().proxy_open(req, proxy, type)

    def _point_open(self, req, type):  # noqa: A002
        адрес = getattr(req, "_model_routes_proxy", None)
        if not адрес or req.has_proxy() or getattr(req, "_tunnel_host", None):
            return None                       # не помечен или прокси уже назначен — дальше обычным путём
        часть = urllib.parse.urlparse(адрес)
        req.set_proxy(часть.netloc, часть.scheme)   # https-точка — туннелем CONNECT через прокси, как у urllib
        if type == часть.scheme or type == "https":
            return None
        return self.parent.open(req, timeout=req.timeout)


def _install_opener() -> None:
    if getattr(urllib.request, "_model_routes_opener", False):
        return
    urllib.request.install_opener(urllib.request.build_opener(_ProxyByRoute()))
    urllib.request._model_routes_opener = True


_install_opener()


def mark_request(req: urllib.request.Request, route: "Route") -> urllib.request.Request:
    """Пометить запрос к точке: локальная или внешняя без прокси — напрямую, внешняя — через системный прокси,
    внешняя с адресом прокси (16.10.26) — через этот адрес."""
    req._model_routes_direct = not route.uses_proxy
    req._model_routes_proxy = route.proxy_address or None
    return req


def proxy_problem(value) -> str:
    """Что не так с адресом прокси точки; пусто — годен. Только http(s)://хост:порт, без логина и пароля."""
    адрес = str(value or "").strip()
    if not адрес.startswith(("http://", "https://")):
        return f"адрес прокси — http://хост:порт или https://хост:порт, например {PROXY_HINT}"
    часть = urllib.parse.urlparse(адрес)
    if "@" in часть.netloc:
        return f"прокси с паролем не поддерживается — укажите адрес без логина и пароля, например {PROXY_HINT}"
    try:
        порт = часть.port
    except ValueError:
        порт = None
    if not часть.hostname or not порт or часть.path not in ("", "/") or часть.query or часть.fragment \
            or часть.params:
        return f"адрес прокси — только хост и порт, без пути: http://хост:порт, например {PROXY_HINT}"
    return ""


def reasoning_effort(route: "Route") -> str | None:
    """Значение `reasoning_effort` для тела запроса по настройке точки; None — поле не отправляем.

    `auto` (умолчание, как было раньше) — поле не отправляется вовсе, модель работает по своему умолчанию.
    `none` — выключить рассуждение у внешней точки: у модели с обязательным рассуждением ход мысли съедает
    потолок ответа, и на сам ответ места не остаётся — 14.10.26 проверка черновика получала пустой `content`
    при `finish_reason: length`. Проверено живым запросом к DeepSeek 14.10.26: с `reasoning_effort: "none"`
    знаков хода мысли 0 против 171, весь потолок уходит на ответ (1 токен против 47 на том же вопросе).
    Моделям из `REASONING_MANDATORY` опция не подставляется: у них рассуждение обязательное, выключение
    даёт ошибку 400 — им поле не отправляем ни при какой настройке.
    Точке с адресом Anthropic поле не отправляем никогда (15.10.26): адрес его не читает, рассуждение задаёт модель."""
    if anthropic_url(route.url):
        return None
    режим = str(route.opt("reasoning", "auto") or "auto").strip().lower()
    if режим in REASONING_EFFORTS:
        return режим           # low / high (15.10.26) — не выключение, у muse тоже можно
    if any(метка in (route.model or "").lower() for метка in REASONING_MANDATORY):
        return None
    return "none" if режим == "none" else None


def reasoning_mandatory(model) -> bool:
    """У модели рассуждение обязательное — выключить его нельзя (ответ 400). Метки — `REASONING_MANDATORY`."""
    name = str(model or "").strip().lower()
    return any(метка in name for метка in REASONING_MANDATORY)


def reasoning_body(route: "Route") -> dict:
    """Поля тела запроса по настройке рассуждения точки — для пробного запроса, «Проверить связь» и точки openrouter.
    Решение о выключении — то же, что у рабочего вызова: `reasoning_effort(route)`. openai — reasoning_effort: "none";
    openrouter — его прежний способ выключения, reasoning: {"enabled": false} (как reasoning_setting() при
    LLM_REASONING=off). Иначе — пусто, поле не отправляется."""
    усилие = reasoning_effort(route)
    if not усилие:
        return {}
    if route.kind == "openai":
        return {"reasoning_effort": усилие}
    if route.kind == "openrouter":
        return {"reasoning": {"enabled": False}} if усилие == "none" else {"reasoning": {"effort": усилие}}
    return {}


def apply_reasoning(body: dict, route: "Route") -> dict:
    """Положить настройку рассуждения точки в тело запроса. low/high у openrouter — поверх того, что уже положил
    продукт (`reasoning_setting`: например exclude у muse): уровень меняется, остальное остаётся; «выключено» —
    прежним способом, целиком. Возвращает то же тело."""
    поля = reasoning_body(route)
    прежнее = body.get("reasoning")
    if isinstance(поля.get("reasoning"), dict) and "effort" in поля["reasoning"] and isinstance(прежнее, dict):
        поля = {"reasoning": {**{к: з for к, з in прежнее.items() if к != "enabled"}, **поля["reasoning"]}}
    body.update(поля)
    return body


def anthropic_url(url) -> bool:
    """Адрес точки — OpenAI-совместимый адрес Anthropic (15.10.26): по имени сервера, а не по подстроке."""
    try:
        host = (urllib.parse.urlparse(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    return host in ANTHROPIC_HOSTS


def is_claude(model) -> bool:
    """Модель Claude: имя у Anthropic начинается с `claude-`, у OpenRouter — `anthropic/claude…`."""
    name = str(model or "").strip().lower()
    return name.startswith("claude-") or "anthropic/claude" in name


def apply_model_limits(body: dict, route: "Route", model: str | None = None) -> dict:
    """Убрать из тела поля, которые модель не принимает (15.10.26). У Claude 4.7 и новее `temperature` ниже 1 и
    `top_p` кроме 0,99 дают ответ 400 (документация Anthropic, platform.claude.com/docs/en/api/openai-sdk), а продукты
    шлют temperature 0–0,2 — у модели Claude на точке openai и openrouter оба поля убираются. Модель — из вызова, иначе
    из тела, иначе у точки. Вызывается везде, где собирается тело к openai/openrouter: рабочий вызов, пробный запрос,
    «Проверить связь». Возвращает то же тело."""
    if route.kind in ("openai", "openrouter") and is_claude(model or body.get("model") or route.model):
        for поле in SAMPLING_FIELDS:
            body.pop(поле, None)
    return body


# --- Родной Messages API у точки Anthropic (26.10.2026) ----------------------------------------------------------------
#
# Черновик 12.10 на claude-sonnet-5-5 через OpenAI-совместимый вход: 0 знаков ответа при completion_tokens 32 000 —
# рассуждение на усилии по умолчанию (`high` у Sonnet 5.5) съело весь потолок. Усилие задаётся только родным входом:
# `output_config.effort` (skill claude-api, Thinking & Effort; Migrating to Claude Sonnet 5.5 → Choosing an effort
# level — `low` для генерации текста, извлечения и классификации). Рассуждение и при `low` тратит тот же потолок, но на
# простом шаге модель его обычно пропускает, на большом — держит коротким.
ANTHROPIC_VERSION = "2023-06-01"
CLAUDE_EFFORT_ENV = "LLM_CLAUDE_EFFORT"
CLAUDE_EFFORT_DEFAULT = "low"
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Модели, у которых усилия нет (skill claude-api: на Sonnet 4.5 и Haiku 4.5 поле даёт ошибку) — поле им не шлём.
CLAUDE_БЕЗ_УСИЛИЯ = ("claude-3", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-sonnet-4-0", "claude-sonnet-4-2",
                     "claude-opus-4-0", "claude-opus-4-1", "claude-opus-4-2")
СИСТЕМА_РАЗДЕЛИТЕЛЬ = chr(10) * 2


def messages_api(route) -> bool:
    """Точка ходит в родной Messages API Anthropic: род openai и адрес api.anthropic.com (26.10.2026)."""
    return getattr(route, "kind", None) == "openai" and anthropic_url(getattr(route, "url", ""))


def claude_effort() -> str:
    """Усилие рассуждения Claude: `LLM_CLAUDE_EFFORT`, если значение из `CLAUDE_EFFORTS`, иначе `CLAUDE_EFFORT_DEFAULT`."""
    значение = str(os.environ.get(CLAUDE_EFFORT_ENV) or "").strip().lower()
    return значение if значение in CLAUDE_EFFORTS else CLAUDE_EFFORT_DEFAULT


def to_messages_api(body: dict) -> dict:
    """Тело OpenAI-совместимого вызова продукта → тело Messages API. Системные реплики — полем `system`, остальные
    реплики как есть; потолок, модель и поток — те же; усилие — `claude_effort()`. Поля совместимого входа (temperature,
    top_p, stream_options, reasoning_effort, response_format, usage) не переносятся. `thinking` не задаётся: у Sonnet 5.5 и
    Opus 5.5 рассуждение адаптивное по умолчанию, а `disabled` — 400."""
    система, реплики = [], []
    for реплика in body.get("messages") or []:
        if реплика.get("role") == "system":
            система.append(str(реплика.get("content") or ""))
        else:
            реплики.append({"role": реплика.get("role"), "content": реплика.get("content")})
    итог = {"model": body.get("model"), "max_tokens": int(body.get("max_tokens") or 16000), "messages": реплики}
    if система:
        итог["system"] = СИСТЕМА_РАЗДЕЛИТЕЛЬ.join(система)
    if body.get("stream"):
        итог["stream"] = True
    модель = str(body.get("model") or "").strip().lower()
    if not модель.startswith(CLAUDE_БЕЗ_УСИЛИЯ):
        итог["output_config"] = {"effort": claude_effort()}
    return итог


def wire_request(route, body: dict, api_key: str | None = "") -> tuple[str, dict, dict]:
    """(адрес, тело, заголовки) запроса к точке. Одно место для рабочего вызова обоих продуктов, пробы и «Проверить
    связь»: у точки Anthropic — родной Messages API (`x-api-key`, `anthropic-version`, `to_messages_api`), у прочих —
    тело как есть и `Authorization: Bearer`. Ключ идёт только в заголовок."""
    headers = {"Content-Type": "application/json"}
    if messages_api(route):
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
        return route.endpoint, to_messages_api(body), headers
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return route.endpoint, body, headers


def _целое_токенов(значение) -> int:
    return значение if isinstance(значение, int) and not isinstance(значение, bool) else 0


def normalize_usage(usage) -> dict:
    """Расход Messages API (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`)
    в словах OpenAI, которые читают журнал и `llm_cost`: prompt_tokens — весь вход вместе с кэшем, completion_tokens —
    весь выход вместе со скрытым рассуждением. Расход OpenAI-совместимого входа возвращается как есть."""
    if not isinstance(usage, dict):
        return {}
    if "prompt_tokens" in usage or not ({"input_tokens", "output_tokens"} & set(usage)):
        return usage
    из_кэша = _целое_токенов(usage.get("cache_read_input_tokens"))
    вход = _целое_токенов(usage.get("input_tokens")) + из_кэша + _целое_токенов(usage.get("cache_creation_input_tokens"))
    выход = _целое_токенов(usage.get("output_tokens"))
    return {**usage, "prompt_tokens": вход, "completion_tokens": выход, "total_tokens": вход + выход,
            "prompt_tokens_details": {"cached_tokens": из_кэша}}


def response_text(raw) -> str:
    """Текст ответа без потока: Messages API (`content` — список блоков, текст — в блоках text), OpenAI-совместимый
    (`choices[0].message.content`) и родной Ollama (`message.content`)."""
    if not isinstance(raw, dict):
        return ""
    if isinstance(raw.get("content"), list):
        return "".join(str(б.get("text") or "") for б in raw["content"]
                       if isinstance(б, dict) and б.get("type") == "text")
    if isinstance(raw.get("message"), dict) and not raw.get("choices"):
        return str(raw["message"].get("content") or "")
    return str((((raw.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or "")


def forbidden_reason(detail, extra=()) -> str:
    """Отказ 403 — человеку (14.10.26). Прежде 401 и 403 сводились в «ключ не принят поставщиком», а 403 бывает и
    при верном ключе: OpenRouter с сервера компании отвечает {"success": false, "error": "Access denied by security
    policy."} — запрет по адресу, а не по ключу. Поэтому — ответ поставщика как есть, первые 200 знаков, ключ
    вычищен ДО обрезки (иначе обрезанный ключ не узнать по значению)."""
    тело = " ".join(scrub(detail, extra).split())[:200]
    return "доступ запрещён поставщиком (HTTP 403)" + (f": {тело}" if тело else "")


КЛЮЧ_НЕ_ПРИНЯТ_СОВЕТ = "проверьте ключ и срок его действия"


def key_rejected_reason(detail, extra=()) -> str:
    """Отказ 401 — человеку с ответом поставщика, как у 403 (решение владельца 15.10.26). Поставщик часто говорит, что
    именно не так: Z.ai — {"error":{"code":"401","message":"token expired or incorrect"}}, BigModel — то же по-китайски;
    одной фразой «ключ не принят» это не отличить от опечатки. Первые 200 знаков, ключ вычищен ДО обрезки. Тела нет —
    прежний текст."""
    тело = " ".join(scrub(detail, extra).split())[:200]
    return ("ключ не принят поставщиком (HTTP 401)" + (f": {тело}" if тело else "")
            + " — " + КЛЮЧ_НЕ_ПРИНЯТ_СОВЕТ)


# --- Хранилище ключей значением: model_keys.local.json рядом с models.json (14.10.26) --------------------------

_keys_cache: dict = {"path": None, "mtime": None, "data": {}}


def keys_path() -> Path | None:
    path = _current_path()
    return path.with_name(KEYS_FILE) if path else None


def _keys_read() -> dict:
    path = keys_path()
    if not path or not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
        if _keys_cache["path"] != str(path) or _keys_cache["mtime"] != mtime:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _keys_cache.update(path=str(path), mtime=mtime,
                               data={str(k): str(v) for k, v in (raw.get("keys") or {}).items() if v})
        return dict(_keys_cache["data"])
    except (OSError, ValueError, AttributeError):
        return {}


def _keys_write(data: dict) -> None:
    path = keys_path()
    if not path:
        raise RoutesError("файла маршрутов нет — ключ хранить негде; создайте models.json")
    tmp = path.with_name(KEYS_FILE + ".tmp")
    tmp.write_text(json.dumps({"keys": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    _keys_cache.update(path=None, mtime=None, data={})


def _key_check(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise RoutesError("ключ пустой — вставьте ключ, полученный у поставщика")
    if any(ch.isspace() for ch in value):
        raise RoutesError("в ключе есть пробел или перевод строки — вставьте ключ целиком, одной строкой")
    if len(value) > KEY_MAX_LEN:
        raise RoutesError(f"ключ длиннее {KEY_MAX_LEN} знаков — похоже, вставлено лишнее")
    return value


def key_has(point: str) -> bool:
    return bool(_keys_read().get(point))


def key_get(point: str) -> str:
    """Значение ключа — только для вызова модели. В ответы API не идёт."""
    return _keys_read().get(point, "")


def key_set(point: str, value: str, by: str = "") -> str:
    """Задать или заменить ключ точки. В журнал — только «задан / заменён», кто и когда."""
    value = _key_check(value)
    path = _current_path()
    if not path or not path.exists():
        raise RoutesError("файла маршрутов нет — ключ хранить негде; создайте models.json")
    with _lock:
        data = _keys_read()
        action = "key_replace" if data.get(point) else "key_set"
        data[point] = value
        _keys_write(data)
    _log(path, {"action": action, "point": point, "by": by})
    return "replace" if action == "key_replace" else "set"


def key_delete(point: str, by: str = "") -> bool:
    with _lock:
        data = _keys_read()
        if point not in data:
            return False
        del data[point]
        _keys_write(data)
    path = _current_path()
    if path:
        _log(path, {"action": "key_delete", "point": point, "by": by})
    return True


def key_rename(old: str, new: str) -> None:
    with _lock:
        data = _keys_read()
        if old in data and old != new:
            data[new] = data.pop(old)
            _keys_write(data)


def key_masked(point: str, full: bool) -> str:
    value = key_get(point)
    if not value:
        return "ключа нет"
    return f"ключ задан · …{value[-4:]}" if full else "ключ задан"


_SCRUB_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s\"'<>,;\[\]]{4,}"),
    re.compile(r"(?i)((?:authorization|x-api-key|api[-_]?key)[\"']?\s*[:=]\s*[\"']?)(?!bearer\b)[^\s\"'<>,;\[\]]{4,}"),
    re.compile(r"()\bsk-[A-Za-z0-9_\-]{12,}"),
)


def scrub(text, extra=()) -> str:
    """Вычистить ключи из текста ошибки или журнала: ответ поставщика может эхом вернуть заголовок.
    Заменяются сохранённые значения, ключи из переменных окружения точек, `extra` (ключ из формы «Проверить
    связь») и всё после «Bearer » / «Authorization:»."""
    if text is None:
        return ""
    s = str(text)
    if not s:
        return s
    values = list(_keys_read().values()) + [str(v) for v in (extra or ()) if v]
    try:
        names = {"OPENROUTER_API_KEY", "LLM_API_KEY", "LLM_VERIFY_API_KEY"}
        data = _state.data or {}
        names |= {str(ep.get("key_env")) for ep in (data.get("endpoints") or {}).values() if ep.get("key_env")}
        values += [os.environ.get(n, "") for n in names]
    except Exception:  # noqa: BLE001 — фильтр не должен ронять запись
        pass
    for v in sorted({v for v in values if v and len(v) >= 6}, key=len, reverse=True):
        s = s.replace(v, HIDDEN)
    for pattern in _SCRUB_PATTERNS:
        s = pattern.sub(lambda m: m.group(1) + HIDDEN, s)
    return s


def missing(ep: dict) -> str:
    """Чего не хватает точке, чтобы работать; пусто — готова. Заготовка без адреса допустима в справочнике,
    но в роль не попадает."""
    kind = ep.get("kind")
    need = [f["key"] for f in KIND_FIELDS.get(kind, {}).get("fields", []) if f.get("required")]
    gaps = [k for k in need if not str(ep.get(k) or "").strip()]
    names = {"url": "не задан адрес (url)", "model": "не задана модель (model)", "callable": "не задана функция (callable)"}
    return "; ".join(names.get(k, f"не задано поле {k}") for k in gaps)


def _check_point(name: str, ep: dict) -> None:
    """Неверно заполненное поле — ошибка сразу; пустое обязательное — заготовка (см. missing)."""
    kind = ep.get("kind")
    if kind not in KINDS + ASR_KINDS:
        raise RoutesError(f"точка «{name}»: kind должен быть одним из {', '.join(KINDS + ASR_KINDS)}, а не «{kind}»")
    for bad in ("key", "api_key", "token", "password"):
        if ep.get(bad):
            raise RoutesError(f"точка «{name}»: ключи в файле не хранятся — укажите имя переменной окружения в key_env")
    key_env = str(ep.get("key_env") or "")
    if key_env and (not _ENV_NAME.match(key_env) or len(key_env) > 60):
        raise RoutesError(f"точка «{name}»: key_env — имя переменной окружения (например OPENROUTER_API_KEY), "
                          f"а не сам ключ")
    key_source = ep.get("key_source", "env")
    if key_source not in KEY_SOURCES:
        raise RoutesError(f"точка «{name}»: key_source — env (имя переменной) или value (значение)")
    if key_source == "value" and key_env:
        raise RoutesError(f"точка «{name}»: ключ задан двумя способами — оставьте имя переменной или значение")
    proxy = ep.get("proxy", "system")
    if proxy not in PROXY_MODES:
        if not isinstance(proxy, str) or not proxy.startswith(("http://", "https://")):
            raise RoutesError(f"точка «{name}»: proxy — system (системный прокси), none (без прокси) или адрес "
                              f"прокси http://хост:порт")
        if proxy_problem(proxy):
            raise RoutesError(f"точка «{name}»: {proxy_problem(proxy)}")
        if kind in ASR_KINDS:
            raise RoutesError(f"точка «{name}»: у распознавания прокси нет — голос не покидает периметр")
    reasoning = ep.get("reasoning", "auto")
    if reasoning not in REASONING_MODES:
        raise RoutesError(f"точка «{name}»: reasoning — auto (как задаёт модель), low, high или none (выключено), "
                          f"а не «{reasoning}»")
    if reasoning != "auto" and kind not in REASONING_KINDS:
        raise RoutesError(f"точка «{name}»: рассуждение выключается только у точек openai и openrouter")
    if reasoning == "none" and reasoning_mandatory(ep.get("model")):
        raise RoutesError(f"точка «{name}»: у модели «{ep.get('model')}» обязательное рассуждение — выключить нельзя")
    if reasoning != "auto" and anthropic_url(ep.get("url")):
        raise RoutesError(f"точка «{name}»: у адреса Anthropic рассуждение задаёт сама модель — поле «Рассуждение "
                          f"модели» оставьте «как у модели»")
    if kind == "python" and ep.get("callable") and ":" not in str(ep["callable"]):
        raise RoutesError(f"точка «{name}»: для python нужна ссылка на код callable вида «модуль:функция»")
    url = str(ep.get("url") or "")
    if url and not url.startswith(("http://", "https://")):
        raise RoutesError(f"точка «{name}»: адрес начинается с http:// или https://")
    if kind == "asr-service" and url and not _internal_url(url):
        raise RoutesError(f"точка «{name}»: сервис распознавания — только во внутренней сети, голос не покидает "
                          f"периметр")
    if kind == "faster-whisper" and ep.get("device", "auto") not in ("auto", "cuda", "cpu"):
        raise RoutesError(f"точка «{name}»: device — auto, cuda или cpu")
    if "max_tokens" in ep:
        if kind in ASR_KINDS:
            raise RoutesError(f"точка «{name}»: потолок ответа бывает только у точки модели")
        потолок = ep["max_tokens"]
        if isinstance(потолок, bool) or not isinstance(потолок, int) or потолок <= 0:
            raise RoutesError(f"точка «{name}»: потолок ответа — целое число токенов больше нуля")
    if "month_limit_usd" in ep:
        if kind in ASR_KINDS:
            raise RoutesError(f"точка «{name}»: предел расхода бывает только у точки модели")
        предел = ep["month_limit_usd"]
        if isinstance(предел, bool) or not isinstance(предел, (int, float)) or not предел > 0:
            raise RoutesError(f"точка «{name}»: предел расхода в месяц — число долларов больше нуля")
    if ep.get("tariff") is not None:
        if kind in ASR_KINDS:
            raise RoutesError(f"точка «{name}»: тариф бывает только у точки модели, у распознавания его нет")
        try:
            llm_cost.проверить_тариф(ep["tariff"])
        except llm_cost.ТарифНеВерен as exc:
            raise RoutesError(f"точка «{name}»: {exc}") from None


def show_role(role: str) -> None:
    """Продукт включает в пульте «Модели» необязательную роль (`OPTIONAL_ROLES`): Планёрка — договорённости (18.10.2026)."""
    if role in OPTIONAL_ROLES:
        _shown_roles.add(role)


def own_chain(role: str) -> bool:
    """Есть ли у роли своя цепочка в файле маршрутов (а не унаследованная от генерации); файл не читается — нет."""
    try:
        data = _load()
    except (RoutesError, ValueError, OSError):
        return False
    return bool(data and (data.get("roles") or {}).get(role))


def _validate(data: dict) -> dict:
    eps = data.get("endpoints")
    roles = data.get("roles")
    # С 16.10.26 (решение владельца, Д2) пустой справочник и роль без точки — не ошибка файла, а «роль не настроена»:
    # пульт начинает файл с пустого, а сборка без назначенной модели не идёт (`chain` → RoleNotConfigured).
    if not isinstance(eps, dict):
        raise RoutesError("в models.json нет раздела endpoints")
    if not isinstance(roles, dict):
        raise RoutesError("в models.json нет раздела roles")
    for name, ep in eps.items():
        _check_point(name, ep)
    if "probe" in data:
        _probe_check(data["probe"])     # пробный запрос перед сборкой (14.10.26)
    for role, chain in roles.items():
        if not isinstance(chain, list) or not chain:
            raise RoutesError(f"роль «{role}»: нужна непустая цепочка точек")
        unknown = [n for n in chain if n not in eps]
        if unknown:
            raise RoutesError(f"роль «{role}»: неизвестные точки {', '.join(unknown)}")
        outside = [n for n in chain if role == "asr" and is_external(eps[n])]
        if outside:
            # Голос не покидает периметр — в коде, а не в подсказке (14.10.26): эта проверка идёт и при загрузке
            # файла, и при любой записи (пульт, API, команда use), так что правкой models.json её не обойти.
            raise RoutesError(f"распознавание — только внутри контура: точка «{outside[0]}» внешняя; "
                              "распознавание идёт только через faster-whisper, свой код или сервис внутренней сети")
        wrong = [n for n in chain if (eps[n]["kind"] in ASR_KINDS) != (role == "asr")]
        if wrong:
            raise RoutesError(f"роль «{role}»: точки {', '.join(wrong)} другого типа подключения — "
                              + ("распознавание идёт только через faster-whisper, свой код или сервис внутренней сети"
                                 if role == "asr" else "точка распознавания не может писать текст"))
        for n in chain:
            gap = missing(eps[n])
            if gap:
                raise RoutesError(f"роль «{role}»: точка «{n}» не настроена — {gap}")
    return data


def _load() -> dict | None:
    """Файл маршрутов, перечитанный при изменении. None — файла нет, работаем по переменным окружения."""
    path = _current_path()
    if not path or not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _lock:
        if _state.mtime != mtime or not _state.data:
            data = json.loads(path.read_text(encoding="utf-8"))
            _state.data = _validate(data)
            _state.mtime = mtime
        return _state.data


NOT_CONFIGURED = "модель не настроена — назначьте в «Моделях»"


class RoleNotConfigured(RoutesError):
    """У роли генерации или проверки нет назначенной модели (решение владельца 16.10.26, Д2): ни одного вызова, причина —
    человеку. Наследует RoutesError: прежние перехваты ошибок маршрутов её видят."""

    def __init__(self, role: str, reason: str):
        self.role, self.reason = role, reason
        super().__init__(f"Роль «{ROLE_TITLES.get(role, role)}»: {NOT_CONFIGURED} ({reason}).")


def _from_env(role: str, env: dict | None = None) -> list[Route]:
    """Распознавание речи без своей точки в файле — как раньше, по WEBAPP_WHISPER_MODEL на этой машине.

    До 16.10.26 здесь же из переменных (LLM_PROVIDER, LLM_BASE_URL, QWEN_MODEL…) собирались роли генерации и проверки.
    Решение владельца 16.10.26 (Д2): переменные модель роли не задают — роль «не настроена» (`RoleNotConfigured`)."""
    if role == "asr":
        return [Route("env-asr", "faster-whisper", None, from_env=True)]
    raise RoleNotConfigured(role, "в «Моделях» роли не назначена модель")


def not_configured(role: str) -> str:
    """Почему у роли нет модели (для пульта, мониторинга и карточки) или пустая строка — роль настроена. Распознавание
    всегда настроено: без своей точки — WEBAPP_WHISPER_MODEL."""
    try:
        chain(role)
    except RoleNotConfigured as exc:
        return exc.reason
    except (RoutesError, ValueError, OSError):
        return ""            # распознавание с неверным файлом — его ошибка покажется своим путём, как раньше
    return ""


def primary(role: str, env: dict | None = None) -> "Route | None":
    """Основная точка роли или None — роль не настроена (мониторинг, строки панели: показать причину, а не упасть)."""
    try:
        return chain(role, env)[0]
    except RoleNotConfigured:
        return None


def names(role: str) -> list[str]:
    """Имена точек цепочки роли или [] — роль не настроена (журнал смены модели в пульте, 16.10.26)."""
    try:
        return [r.name for r in chain(role)]
    except RoleNotConfigured:
        return []


LOOP_MIN_REPEATS = 8          # один и тот же абзац или блок — подряд не меньше стольких раз
LOOP_MIN_REPEATS_DIGITS = 20  # отличаются только числами («№ 12», «№ 13») — подряд не меньше стольких раз
LOOP_MIN_CHARS = 2000         # и не меньше стольких знаков повтора (короткие одинаковые строки таблицы — не цикл)
LOOP_CHECK_EVERY = 4000       # поток проверяется каждые столько новых знаков ответа
LOOP_MAX_BLOCK = 12           # самый длинный повторяющийся блок, абзацев
LOOP_TAIL = 40000             # проверяется хвост ответа такой длины
# Третий способ (заход 5 хаос-тестов, 20.10.2026): почти одинаковые куски — находки проверки с разными цитатами и одним
# пояснением, без переносов и точек между ними. Первые два способа их не ловят (куски не совпадают дословно), и проверка
# на стенде писала до потолка. Хвост от LOOP_ZIP_MIN_CHARS знаков, который сжимается лучше LOOP_ZIP_RATIO, — цикл.
# Замер 20.10.2026 на 2 695 окнах по 20–40 тыс. знаков документов, протоколов, черновиков и журналов трёх рабочих папок:
# самое плотное окно настоящего текста — 0,051 (сырой вывод атаки вехи 3), черновики и сверки — от 0,083; ниже порога
# только нарочно повторяющиеся загрузки хаос-тестов (0,002). Находки проверки с одним пояснением и случайными цитатами
# (400 штук) — 0,039.
LOOP_ZIP_MIN_CHARS = 20000
LOOP_ZIP_RATIO = 0.045
LOOP_REMINDER = ("\n\nВажно: прошлая попытка ответа зациклилась — один и тот же абзац повторялся без конца. Не "
                 "повторяй строки и абзацы: каждое поручение, находку и абзац пиши один раз и закончи ответ, когда всё "
                 "сказано, строго в требуемом формате.")
_LOOP_SPLIT = re.compile(r"\n+|(?<=[.!?;])\s+")


def _loop_norm(unit: str, без_цифр: bool) -> str:
    """Кусок для сравнения: пробелы схлопнуты; `без_цифр` — числа не различаются, но только у куска с текстом (20+ букв):
    строки из одних чисел (таблица итогов) сравниваются как есть, иначе разные числа сошли бы за повтор."""
    кусок = re.sub(r"\s+", " ", unit).strip()
    if без_цифр and len(re.findall(r"[^\W\d_]", кусок)) >= 20:
        кусок = re.sub(r"\d+", "#", кусок)
    return кусок


def _loop_blocks(куски: list[str], нужно: int) -> str:
    for q in range(1, LOOP_MAX_BLOCK + 1):
        if len(куски) < q * нужно:
            break
        блок = куски[-q:]
        раз, i = 1, len(куски) - 2 * q
        while i >= 0 and куски[i:i + q] == блок:
            раз += 1
            i -= q
        if раз >= нужно and sum(len(k) for k in блок) * раз >= LOOP_MIN_CHARS:
            что = "абзац" if q == 1 else f"блок из {q} абзацев"
            return f"один и тот же {что} повторяется {раз} раз подряд: «{блок[0][:120]}»"
    return ""


def degenerate_loop(text: str) -> str:
    """Признак вырожденного (зациклившегося) ответа модели: пустая строка — нет, иначе описание для журнала и карточки.

    Три способа, все по хвосту ответа (третий — сжатие, см. LOOP_ZIP_RATIO, 20.10.2026): (1) абзацы и предложения — один и тот же блок из 1–LOOP_MAX_BLOCK кусков подряд
    не меньше LOOP_MIN_REPEATS раз, а отличающийся только числами — не меньше LOOP_MIN_REPEATS_DIGITS раз; (2) точный повтор знаков без переносов и точек — хвост
    периодичен. Порог по знакам — не меньше LOOP_MIN_CHARS: восемь одинаковых коротких строк таблицы циклом не считаются."""
    хвост = (text or "")[-LOOP_TAIL:]
    if len(хвост) < LOOP_MIN_CHARS:
        return ""
    сырые = _LOOP_SPLIT.split(хвост)[:-1]                              # последний кусок может быть недописан
    for без_цифр, нужно in ((False, LOOP_MIN_REPEATS), (True, LOOP_MIN_REPEATS_DIGITS)):
        найдено = _loop_blocks([k for k in (_loop_norm(x, без_цифр) for x in сырые) if k], нужно)
        if найдено:
            return найдено
    образец = хвост[-200:]
    прежний = хвост.rfind(образец, 0, len(хвост) - len(образец))
    if прежний >= 0:
        период = len(хвост) - len(образец) - прежний
        if период > 0:
            кусок = хвост[-период:]
            раз, i = 1, len(хвост) - период
            while i - период >= 0 and хвост[i - период:i] == кусок:
                раз += 1
                i -= период
            if раз >= LOOP_MIN_REPEATS and период * раз >= LOOP_MIN_CHARS:
                return f"один и тот же отрезок в {период} знаков повторяется {раз} раз подряд: «{кусок.strip()[:120]}»"
    if len(хвост) >= LOOP_ZIP_MIN_CHARS:
        байты = хвост.encode("utf-8")
        доля = len(zlib.compress(байты, 6)) / len(байты)
        if доля < LOOP_ZIP_RATIO:
            return (f"почти одинаковые куски: хвост в {len(хвост)} знаков сжимается до {доля:.3f} "
                    f"(порог {LOOP_ZIP_RATIO}): «{хвост[-120:].strip()}»")
    return ""


# Негодный ответ — пустой или зациклившийся (26.10.2026, вариант Д на 12.10 «Т», стенд Планёрки): на шаг вызова не больше
# стольких платных обращений с таким ответом, сколько бы точек ни было в цепочке. Было: на последней (и единственной)
# точке цепочки число попыток бралось из ожидания выгруженной модели (`LLM_UNLOADED_ATTEMPTS`, 5), и пустой ответ
# переспрашивался до пяти раз — каждое обращение до потолка ответа и до часа без строки журнала, сборка «не кончалась».
# Сетевые сбои, 429/5xx и выгруженная модель по-прежнему ждут своё число попыток: там повтор лечит, здесь — нет.
BAD_ANSWERS_PER_CALL = 2


def stop_line(step: str | None, attempt: int | None, chars_text: int, chars_reasoning: int, finish_reason: str | None,
              reason: str, detail: str = "") -> str:
    """Строка о попытке, отброшенной транспортом, — одинаковая в журнале вызовов, журнале сервера и итоге прогона
    (26.10.2026): шаг, попытка, что вернула модель (знаков ответа и рассуждения, `finish_reason`) и причина остановки.
    Без текста встречи; `detail` — описание зацикливания или ошибки, не длиннее 200 знаков."""
    подробно = " ".join(str(detail or "").split())[:200]
    return (f"шаг «{step or '?'}», попытка {attempt or '?'}: ответ {chars_text} знаков, рассуждение {chars_reasoning} "
            f"знаков, finish_reason {finish_reason or '—'}; остановлено: {reason}" + (f" — {подробно}" if подробно else ""))


def chain(role: str, env: dict | None = None) -> list[Route]:
    """Цепочка точек роли по порядку; выведенные предохранителем — в конце (если живых нет, пробуем и их).

    Генерация и проверка без назначенной модели — `RoleNotConfigured` (решение владельца 16.10.26, Д2): файла нет, он не
    читается или у роли нет точки. Переменные окружения (`env`, LLM_PROVIDER, QWEN_MODEL…) модель не задают; параметр
    оставлен для совместимости вызовов. Проверка без своей точки — точки генерации (исключение владельца 13.10.26)."""
    if role == "asr":
        data = _load()                       # неверный файл распознаванию — ошибкой, как раньше
        if data is None or "asr" not in data["roles"]:
            return _from_env(role, env)      # распознавание в файл не вынесено — как раньше, WEBAPP_WHISPER_MODEL
        names = data["roles"]["asr"]
    else:
        try:
            data = _load()
        except (RoutesError, ValueError, OSError) as exc:
            raise RoleNotConfigured(role, f"файл маршрутов {_current_path()} не читается: {scrub(str(exc))[:300]}") from exc
        if data is None:
            raise RoleNotConfigured(role, f"файла маршрутов нет ({_current_path() or 'data/models.json'})")
        names = data["roles"].get(role) or (data["roles"].get("generate") if role in INHERIT_GENERATE else None)
        if not names:
            raise RoleNotConfigured(role, "в «Моделях» роли не назначена модель")
    routes = [_route(n, data["endpoints"][n]) for n in names]
    now = time.time()
    live = [r for r in routes if _state.down_until.get(r.name, 0) <= now]
    resting = [r for r in routes if _state.down_until.get(r.name, 0) > now]
    return live + resting


def _route(name: str, ep: dict) -> Route:
    return Route(name, ep["kind"], ep.get("model") or ep.get("callable"), ep.get("url", ""), ep.get("key_env", ""),
                 options=tuple(sorted((k, v) for k, v in ep.items() if k not in _BASE_KEYS and isinstance(v, (str, int, float, bool)))))


def provider_of(route: Route | None) -> str | None:
    """Поставщик платной (внешней) точки — для предела расхода; своя машина в контуре — None."""
    if route is None or not route.external:
        return None
    return llm_cost.поставщик(route.kind, route.url)


def provider_limit(provider: str | None) -> float | None:
    """Предел расхода поставщика в месяц: меньший из заданных у его точек; у OpenRouter без своего — переменная
    OPENROUTER_WORKSPACE_BUDGET_USD, если задана. Нет — None (только счёт)."""
    if not provider:
        return None
    try:
        data = _load()
    except (RoutesError, ValueError, OSError):
        data = None
    пределы = [ep["month_limit_usd"] for ep in ((data or {}).get("endpoints") or {}).values()
               if ep.get("month_limit_usd") and ep.get("kind") in KINDS and is_external(ep)
               and llm_cost.поставщик(ep.get("kind"), ep.get("url", "")) == provider]
    if пределы:
        return float(min(пределы))
    if provider == llm_cost.OPENROUTER:
        try:
            return llm_cost.предел_из_текста(os.environ.get(OPENROUTER_BUDGET_ENV, ""))
        except llm_cost.ТарифНеВерен:
            return None
    return None


def provider_limit_state(route: Route | None, journal_path, time_utc: bool) -> dict | None:
    """Состояние предела поставщика этой точки по журналу вызовов продукта; None — точка не платная."""
    provider = provider_of(route)
    if not provider:
        return None
    потрачено = llm_cost.расход_по_поставщикам(llm_cost.строки_журнала(journal_path), время_utc=time_utc).get(provider, 0.0)
    return llm_cost.состояние_предела(provider, потрачено, provider_limit(provider))


def provider_limits_panel(spent: dict) -> list[dict]:
    """Строки мониторинга по каждому поставщику: внешние точки из файла и все, у кого был расход в этом месяце."""
    try:
        data = _load()
    except (RoutesError, ValueError, OSError):
        data = None
    поставщики = {llm_cost.поставщик(ep.get("kind"), ep.get("url", ""))
                  for ep in ((data or {}).get("endpoints") or {}).values() if ep.get("kind") in KINDS and is_external(ep)}
    поставщики |= set(spent)
    поставщики.discard("")
    return [llm_cost.состояние_предела(п, spent.get(п, 0.0), provider_limit(п))
            for п in sorted(поставщики, key=llm_cost.название_поставщика)]


def max_tokens_of(route: Route | None) -> int | None:
    """Потолок ответа точки (15.10.26) или None — тогда потолок по шагу, как раньше."""
    потолок = route.opt("max_tokens") if route is not None else None
    if isinstance(потолок, bool) or not isinstance(потолок, int) or потолок <= 0:
        return None
    return потолок


# Потолок ответа проверки черновика поверх точки и переменной шага (заход 5 хаос-тестов, 20.10.2026). Проверка на стенде
# Планёрки дважды писала до потолка точки 96 000 токенов (276 912 знаков, finish_reason: length, 0,119 $), хотя её
# нормальный ответ — вердикт и находки: по журналам 263 вызовов проверки 880–9 925 токенов, у deepseek-flash на стенде
# 8 208–22 946. 16 000 по таблице шага мало (deepseek, 14.10.26 — обрыв), 32 000 — запас в 1,4 раза над наибольшим
# нормальным ответом. Переменная `LLM_VERIFY_MAX_TOKENS_CEILING` поднимает или опускает потолок без правки кода.
VERIFY_MAX_TOKENS_CEILING = 32000


GUARD_MAX_TOKENS_CEILING = 256   # досмотр отвечает одним словом ДА/НЕТ (20.10.2026); запас — на короткое рассуждение


# Потолок ответа черновика поверх точки и переменной шага (обрыв черновика на большом входе, 25.10.2026). Прогон набора на
# стенде Планёрки, встреча 12.10.2026, вход «К» (протокол секретаря и обе расшифровки, 223 250 знаков): один вызов
# черновика написал 242 587 знаков и был отброшен. Потолок шага по таблице — 48 000 токенов, но потолок точки в «Моделях»
# (96 000 у deepseek-flash на стенде) главнее таблицы, и черновику было разрешено вдвое больше. Нормальный черновик —
# 10–40 тыс. знаков (deepseek-flash пишет около 3 знаков на токен, 1 245 вызовов в «Рабочем»), 48 000 токенов — около
# 150 тыс. знаков, запас втрое и место под рассуждение. Переменная `LLM_GENERATE_MAX_TOKENS_CEILING` меняет потолок без
# правки кода; 0 — без потолка поверх точки.
GENERATE_MAX_TOKENS_CEILING = 48000


def _потолок_из_переменной(имя: str, по_умолчанию: int) -> int:
    try:
        return int(os.environ.get(имя) or по_умолчанию)
    except ValueError:
        return по_умолчанию


def step_ceiling(purpose: str | None, tokens: int) -> int:
    """Потолок ответа шага после точки и переменной шага: проверке черновика — не выше `VERIFY_MAX_TOKENS_CEILING`
    (или `LLM_VERIFY_MAX_TOKENS_CEILING`); черновику — не выше `GENERATE_MAX_TOKENS_CEILING` (или
    `LLM_GENERATE_MAX_TOKENS_CEILING`, 25.10.2026); досмотру реплик — не выше `GUARD_MAX_TOKENS_CEILING`; остальным — как было."""
    шаг = (purpose or "").strip().lower()
    if шаг == "guard":
        return min(tokens, GUARD_MAX_TOKENS_CEILING)
    if шаг == "generate":
        потолок = _потолок_из_переменной("LLM_GENERATE_MAX_TOKENS_CEILING", GENERATE_MAX_TOKENS_CEILING)
        return min(tokens, потолок) if потолок > 0 else tokens
    if шаг != "verify":
        return tokens
    потолок = _потолок_из_переменной("LLM_VERIFY_MAX_TOKENS_CEILING", VERIFY_MAX_TOKENS_CEILING)
    return min(tokens, потолок) if потолок > 0 else tokens


def tariff_for(route: Route, model: str | None = None) -> tuple[dict | None, str]:
    """Тариф точки для расчёта стоимости вызова (15.10.26): (тариф, откуда) — «точка», «справочник» или «».
    Заданный у точки в models.json — он; иначе — справочник по модели вызова и адресу точки."""
    ep = None
    if not route.from_env:
        try:
            data = _load()
        except (RoutesError, ValueError, OSError):
            data = None
        ep = ((data or {}).get("endpoints") or {}).get(route.name)
    if ep is None:
        ep = {"kind": route.kind, "model": route.model, "url": route.url}
    return llm_cost.тариф_точки(ep, model or route.model or ep.get("model"), route.url or ep.get("url", ""))


def _tariff_panel(ep: dict) -> dict:
    """Тариф для пульта «Модели»: поля формы (свои или из справочника) и откуда цифры."""
    try:
        tariff, origin = llm_cost.тариф_точки(ep)
    except llm_cost.ТарифНеВерен:
        tariff, origin = None, ""
    if not tariff:
        return {"form": llm_cost.тариф_в_поля(None), "origin": "", "text": "тариф не задан — стоимость не считается, "
                "если поставщик её не вернёт"}
    откуда = "задан у точки" if origin == "точка" else "из справочника открытых прейскурантов"
    return {"form": llm_cost.тариф_в_поля(tariff), "origin": origin, "source": tariff.get("source", ""),
            "as_of": tariff.get("as_of", ""),
            "text": f"тариф {откуда}: {tariff.get('source', '')}" + (f", {tariff['as_of']}" if tariff.get("as_of") else "")}


def cooldown_sec() -> int:
    data = _load()
    return int((data or {}).get("cooldown_sec", DEFAULT_COOLDOWN_SEC))


def mark_down(route: Route, error: str) -> None:
    """Точка не ответила — вывести её на время охлаждения, следующий вызов пойдёт на другую."""
    with _lock:
        _state.down_until[route.name] = time.time() + cooldown_sec()
        _state.last_error[route.name] = scrub(error)[:300]


def mark_up(route: Route) -> None:
    with _lock:
        _state.down_until.pop(route.name, None)
        # Основная снова ответила — следующий её срыв снова даст строку о переходе (20.10.2026).
        _state.noticed = {к for к in _state.noticed if к[1] != route.name}


# --- Переход на запасную модель (задание владелицы 20.10.2026) -------------------------------------------------------
#
# Запасная модель роли — вторая и следующие точки цепочки («Добавить запасной» в «Моделях»); назначает администратор, по
# умолчанию её нет (правило 13.10.26: нет модели по умолчанию). Переход делает сам вызов: точка, не ответившая по
# недоступности (402, 401, 403, 404, 429 и 5xx после повторов, таймаут, отказ соединения), уходит на охлаждение, вызов —
# на следующую. Ответ не в формате и ошибка самого запроса (400) переходом не считаются. Здесь — только то, что нужно
# продукту, чтобы сказать о переходе: какая точка основная, какой ответ — от запасной, почему, и сказать один раз за срыв.
def configured_primary(role: str) -> str | None:
    """Основная точка роли по порядку в «Моделях» (без учёта охлаждения) или None — роль не настроена. Проверка и
    договорённости без своей точки — основная точка генерации (как `chain`)."""
    try:
        data = _load()
    except (RoutesError, ValueError, OSError):
        return None
    if not data:
        return None
    roles = data.get("roles") or {}
    names = roles.get(role) or (roles.get("generate") if role in INHERIT_GENERATE else None)
    return names[0] if names else None


def fallback_of(role: str, answered: str) -> str | None:
    """Ответ точки `answered` — работа на запасной? Да — имя основной точки роли (она сейчас выведена предохранителем),
    иначе None. Не-формат уходит на следующую точку без охлаждения основной — это не переход (решение 13.10.26)."""
    основная = configured_primary(role)
    if not основная or основная == answered:
        return None
    with _lock:
        выведена = _state.down_until.get(основная, 0) > time.time()
    return основная if выведена else None


def fallback_notice(role: str, answered: str) -> dict | None:
    """Сказать ли о переходе на запасную: один раз за срыв основной (до её возврата — `mark_up`). Возвращает
    {"role", "role_title", "primary", "spare", "reason", "reason_full"} или None. Ключа в тексте нет (`scrub`)."""
    основная = fallback_of(role, answered)
    if not основная:
        return None
    with _lock:
        if (role, основная) in _state.noticed:
            return None
        _state.noticed.add((role, основная))
        полная = _state.last_error.get(основная, "")
    return {"role": role, "role_title": ROLE_TITLES.get(role, role), "primary": основная, "spare": answered,
            "reason": unavailability_reason(полная), "reason_full": scrub(полная)[:300]}


_КОД_ОШИБКИ = re.compile(r"(?:ошибк[уаи]|HTTP)\s*(\d{3})\b")


def unavailability_reason(text) -> str:
    """Почему основная недоступна — коротко, для заголовка строки «Основная модель недоступна (…)»."""
    t = str(text or "")
    m = _КОД_ОШИБКИ.search(t)
    if m:
        код = int(m.group(1))
        if код >= 500:
            return f"сбой сервера модели (HTTP {код})"
        return {402: "на счёте поставщика нет денег (HTTP 402)", 401: "ключ не принят (HTTP 401)",
                403: "доступ запрещён (HTTP 403)", 404: "модели нет на сервере (HTTP 404)",
                429: "перегрузка поставщика (HTTP 429)"}.get(код, f"отказ поставщика (HTTP {код})")
    низ = t.lower()
    if any(п in низ for п in ("timed out", "timeout", "таймаут", "перестал отвечать", "нет ответа за",
                              "не ответила за", "первого признака")):
        return "модель не ответила вовремя (таймаут)"
    if any(п in низ for п in ("не удалось обратиться", "refused", "urlopen error", "10061", "10060", "getaddrinfo",
                              "нет связи", "connection")):
        return "нет связи с сервером модели"
    if "выгружена" in низ:
        return "модель выгружена из памяти сервера"
    return "модель не ответила"


def model_for(route: Route, requested: str | None, defaults: tuple, primary: bool) -> str:
    """Какую модель просить у точки. В режиме «из переменных» — как раньше, ту, что передал вызывающий.
    В режиме файла — модель точки; явное переопределение вызывающего (например, отдельная модель Карты в ERP)
    действует только на первой точке цепочки: на запасном сервере такой модели может не быть."""
    if route.model is None:
        return requested or defaults[0]
    if primary and requested and requested not in defaults:
        return requested
    return route.model


def status() -> dict:
    """Для мониторинга и команды show: роли, точки, предохранители."""
    data = _load()
    now = time.time()
    if data is None:
        # Файла нет (16.10.26, Д2): модели ролей не назначены, переменные окружения их не задают.
        return {"source": "не настроено", "path": str(_current_path() or ""),
                "roles": {r: ([x.name for x in _from_env(r)] if r == "asr" else []) for r in ROLES},
                "not_configured": {r: not_configured(r) for r in ("generate", "verify")}, "down": {}}
    return {"source": "файл", "path": str(_current_path()), "roles": data["roles"],
            "endpoints": {n: {k: v for k, v in ep.items() if k != "key"} for n, ep in data["endpoints"].items()},
            "down": {n: int(t - now) for n, t in _state.down_until.items() if t > now},
            "last_error": dict(_state.last_error)}


def _editable() -> tuple[Path, dict]:
    path = _current_path()
    if path is None:
        raise RoutesError("путь к файлу маршрутов не задан — править нечего")
    data = _load()
    if data is None:
        # Файла нет (16.10.26, Д2): пульт начинает его с пустого — первое подключение и назначение роли создают файл.
        return path, {"endpoints": {}, "roles": {}}
    return path, json.loads(json.dumps(data))          # копия: ошибка проверки не портит загруженное


def _log(path: Path, record: dict) -> None:
    try:
        with open(path.with_name("models.log.jsonl"), "a", encoding="utf-8") as f:
            f.write(scrub(json.dumps(dict({"at": time.strftime("%Y-%m-%d %H:%M:%S")}, **record), ensure_ascii=False)) + "\n")
    except OSError:
        pass   # журнал — справка; его сбой не должен отменять изменение


def _write(path: Path, data: dict, record: dict, backup: bool = True) -> dict:
    """Проверить, сохранить прежнюю версию в models.history/, записать атомарно, отметить в журнале."""
    _validate(data)
    if backup and path.exists():
        hist = path.with_name("models.history")
        hist.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        # Две записи в одну миллисекунду не затирают копию друг друга (вопрос ERP 15.10.26, стенд Планёрки 510c07b):
        # суффикс «_01», «_02» сортируется ПОСЛЕ основного имени — откат по-прежнему берёт последнюю по имени.
        копия, n = hist / f"models-{stamp}.json", 0
        while копия.exists():
            n += 1
            копия = hist / f"models-{stamp}_{n:02d}.json"
        копия.write_bytes(path.read_bytes())
        for old in sorted(hist.glob("models-*.json"))[:-HISTORY_KEEP]:
            old.unlink()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    with _lock:
        _state.mtime = None
    _log(path, record)
    return data


def _role_and_point(data: dict, role: str, name: str) -> None:
    if role not in ROLES:
        raise RoutesError(f"нет роли «{role}»")
    if name not in data["endpoints"]:
        raise RoutesError(f"нет точки «{name}»")


def use(role: str, name: str, by: str = "") -> dict:
    """Поставить точку первой в роли и записать файл (переключение без перезапуска). Каждое переключение
    пишется строкой в `models.log.jsonl` рядом с файлом: когда, какая роль, какая точка, кто."""
    path, data = _editable()
    _role_and_point(data, role, name)
    if data["roles"].get(role, [])[:1] == [name]:
        # Точка и так первая — ничего не пишем (Д1 цикла «Мониторинга», 15.10.26; стенд Планёрки 510c07b): иначе новая
        # копия и строка журнала, а «Откатить» потом ничего не меняет — откатывает «смену» на то же самое.
        return data["roles"]
    data["roles"][role] = [name] + [n for n in data["roles"].get(role, []) if n != name]
    _write(path, data, {"action": "use", "role": role, "point": name, "by": by})
    with _lock:
        _state.down_until.pop(name, None)
    return data["roles"]


def add_to_role(role: str, name: str, by: str = "") -> dict:
    """Добавить точку в конец цепочки роли — запасной."""
    path, data = _editable()
    _role_and_point(data, role, name)
    chain_ = data["roles"].get(role, [])
    if name in chain_:
        raise RoutesError(f"точка «{name}» уже в роли «{ROLE_TITLES.get(role, role)}»")
    data["roles"][role] = chain_ + [name]
    _write(path, data, {"action": "add", "role": role, "point": name, "by": by})
    return data["roles"]


def remove_from_role(role: str, name: str, by: str = "") -> dict:
    """Убрать точку из цепочки роли; последняя точка роли остаётся — роль без точек работать не может."""
    path, data = _editable()
    _role_and_point(data, role, name)
    chain_ = data["roles"].get(role, [])
    if name not in chain_:
        raise RoutesError(f"точки «{name}» нет в роли «{ROLE_TITLES.get(role, role)}»")
    if len(chain_) == 1 and role not in OPTIONAL_ROLES:
        raise RoutesError(f"«{name}» — единственная точка роли «{ROLE_TITLES.get(role, role)}»: сначала добавьте другую")
    data["roles"][role] = [n for n in chain_ if n != name]
    if not data["roles"][role]:
        # Необязательная роль без точек (договорённости, 18.10.2026) — снова «как у черновика»: роль уходит из файла.
        del data["roles"][role]
    _write(path, data, {"action": "remove", "role": role, "point": name, "by": by})
    return data["roles"]


def clean_point(fields: dict) -> dict:
    """Поля формы → точка: только поля её рода и пояснение, пустые необязательные отброшены."""
    kind = str(fields.get("kind") or "").strip()
    if kind not in KIND_FIELDS:
        raise RoutesError(f"тип подключения — один из: {', '.join(KIND_FIELDS)}")
    ep = {"kind": kind}
    for f in KIND_FIELDS[kind]["fields"]:
        value = str(fields.get(f["key"]) or "").strip() or f.get("default", "")
        if value or f.get("required"):
            ep[f["key"]] = value
    note = str(fields.get("note") or "").strip()
    if note:
        ep["note"] = note[:300]
    if "max_tokens" in ep:                     # потолок ответа точки (15.10.26) — целое больше нуля
        текст = str(ep["max_tokens"]).replace(" ", "").replace(" ", "")
        if not текст.isdigit() or int(текст) <= 0:
            raise RoutesError("потолок ответа — целое число токенов больше нуля, например 96000; пусто — по умолчанию системы")
        ep["max_tokens"] = int(текст)
    if "month_limit_usd" in ep:                # предел расхода поставщика в месяц (15.10.26)
        try:
            ep["month_limit_usd"] = llm_cost.предел_из_текста(ep["month_limit_usd"])
        except llm_cost.ТарифНеВерен as exc:
            raise RoutesError(str(exc)) from None
        if ep["month_limit_usd"] is None:
            ep.pop("month_limit_usd")
    # Тариф (15.10.26): две строки формы → поле `tariff`. Цены те же, что в справочнике для этой модели и адреса, —
    # в файл не пишем: точка и дальше следует справочнику. Иначе это тариф администратора, справочник его не перекроет.
    prices, peak = ep.pop("tariff_prices", ""), ep.pop("tariff_peak", "")
    try:
        tariff = llm_cost.тариф_из_полей(prices, peak)
    except llm_cost.ТарифНеВерен as exc:
        raise RoutesError(str(exc) if str(exc).startswith("тариф") else f"тариф: {exc}") from None
    if tariff and not llm_cost.те_же_цены(tariff, llm_cost.тариф_справочника(ep.get("model"), ep.get("url", ""))):
        ep["tariff"] = tariff
    # Значения по умолчанию в файл не пишем: точка без key_source/proxy работает как раньше (env, системный прокси).
    if ep.get("key_source") == "value":
        ep.pop("key_env", None)                # ключ значением — имени переменной у точки нет
    elif "key_source" in ep:
        ep.pop("key_source")
    if ep.get("proxy") == "system":
        ep.pop("proxy")
    elif ep.get("proxy") == PROXY_ADDRESS:     # вариант «адрес» (16.10.26): в файл — сам адрес из строки формы
        адрес = str(fields.get("proxy_url") or "").strip().rstrip("/")
        if not адрес:
            raise RoutesError(f"прокси «адрес»: впишите адрес прокси, например {PROXY_HINT}")
        if proxy_problem(адрес):
            raise RoutesError(proxy_problem(адрес))
        ep["proxy"] = адрес
    if ep.get("reasoning") == "auto":
        ep.pop("reasoning")                    # как у модели — поле в запрос не идёт, в файл тоже
    return ep


def save_point(name: str, fields: dict, by: str = "", old_name: str = "", key_value: str | None = None) -> dict:
    """Завести или изменить подключение. Без адреса или модели — заготовка «не настроена», в роль её не поставить.
    Переименование правит и цепочки ролей и переносит ключ. `key_value` — ключ значением из формы (только при
    key_source=value): пишется в model_keys.local.json, в models.json его нет."""
    name = (name or "").strip()
    if not name or len(name) > 60 or "|" in name:
        raise RoutesError("имя подключения — до 60 знаков, без «|»")
    path, data = _editable()
    ep = clean_point(fields)
    _check_point(name, ep)
    if key_value:
        if ep.get("key_source") != "value":
            raise RoutesError("ключ значением передан, а у подключения выбрано «имя переменной окружения»")
        key_value = _key_check(key_value)      # проверить до записи файла, чтобы не осталось половины
    old_name = (old_name or "").strip()
    if old_name and old_name not in data["endpoints"]:
        raise RoutesError(f"нет точки «{old_name}»")
    if name in data["endpoints"] and name != old_name:
        raise RoutesError(f"подключение «{name}» уже есть — выберите другое имя или измените его")
    if old_name and old_name != name:
        data["endpoints"] = {(name if k == old_name else k): v for k, v in data["endpoints"].items()}
        data["roles"] = {r: [name if n == old_name else n for n in ch] for r, ch in data["roles"].items()}
    прежняя = data["endpoints"].get(old_name or name) or {}
    if ep.get("tariff") and llm_cost.те_же_цены(ep["tariff"], прежняя.get("tariff")):
        # цены не менялись — источник и дата остаются прежними, а не «сегодня»
        ep["tariff"] = dict(ep["tariff"], source=прежняя["tariff"].get("source") or ep["tariff"]["source"],
                            as_of=прежняя["tariff"].get("as_of") or ep["tariff"]["as_of"])
    data["endpoints"][name] = ep
    _write(path, data, {"action": "edit" if old_name else "new", "point": name,
                        **({"was": old_name} if old_name and old_name != name else {}), "by": by})
    if old_name and old_name != name:
        key_rename(old_name, name)
    if ep.get("key_source") == "value":
        if key_value:
            key_set(name, key_value, by=by)
    elif key_has(name):
        key_delete(name, by=by)                # перешли на имя переменной — значение больше не нужно
    with _lock:
        _state.down_until.pop(name, None)
        _state.last_error.pop(name, None)
    return data["endpoints"][name]


def set_point_key(name: str, value: str, by: str = "") -> str:
    """«Заменить ключ» в строке подключения: точка должна быть с ключом значением."""
    _, data = _editable()
    ep = data["endpoints"].get(name)
    if ep is None:
        raise RoutesError(f"нет точки «{name}»")
    if ep.get("key_source") != "value":
        raise RoutesError(f"у подключения «{name}» ключ берётся из переменной окружения — выберите «значение» в форме")
    result = key_set(name, value, by=by)
    with _lock:
        _state.down_until.pop(name, None)
        _state.last_error.pop(name, None)
    return result


def delete_point_key(name: str, by: str = "") -> bool:
    """«Удалить ключ» в строке подключения. Точка остаётся, вызовы на неё пойдут без ключа."""
    _, data = _editable()
    if name not in data["endpoints"]:
        raise RoutesError(f"нет точки «{name}»")
    return key_delete(name, by=by)


def delete_point(name: str, by: str = "") -> None:
    """Удалить подключение; из ролей оно уходит само, но единственную точку роли удалить нельзя."""
    path, data = _editable()
    if name not in data["endpoints"]:
        raise RoutesError(f"нет точки «{name}»")
    for role, chain_ in data["roles"].items():
        if chain_ == [name] and role not in OPTIONAL_ROLES:
            raise RoutesError(f"«{name}» — единственная точка роли «{ROLE_TITLES.get(role, role)}»: сначала добавьте "
                              f"в роль другую")
    data["roles"] = {r: [n for n in ch if n != name] for r, ch in data["roles"].items()}
    data["roles"] = {r: ch for r, ch in data["roles"].items() if ch or r not in OPTIONAL_ROLES}
    del data["endpoints"][name]
    _write(path, data, {"action": "delete", "point": name, "by": by})
    key_delete(name, by=by)


def test_point(fields: dict, key_value: str = "", name: str = "") -> tuple[bool, str]:
    """«Проверить связь» по полям формы — до сохранения. `key_value` — ключ, введённый в форму: идёт только в
    заголовок пробного запроса и никуда не записывается. Без него у сохранённой точки `name` берётся её ключ."""
    ep = clean_point(fields)
    _check_point("проверка", ep)
    gap = missing(ep)
    if gap:
        return False, f"не настроена — {gap}"
    key = None
    if ep.get("key_source") == "value":
        key = str(key_value or "").strip() or (key_get(name) if name else "")
        if not key:
            return False, "ключ не введён — вставьте ключ в поле «Ключ»"
        key = _key_check(key)
    ok, detail = ping(_route("проверка", ep), api_key=key)
    return ok, scrub(detail, extra=(key,) if key else ())


def history(limit: int = 8) -> list[dict]:
    """Последние изменения файла маршрутов из журнала, новые сверху."""
    path = _current_path()
    log = path.with_name("models.log.jsonl") if path else None
    if not log or not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[::-1]


def rollback(by: str = "") -> dict:
    """Вернуть файл к версии до последнего изменения. Повторный откат идёт ещё на шаг назад."""
    path, now = _editable()
    hist = path.with_name("models.history")
    versions = sorted(hist.glob("models-*.json")) if hist.exists() else []
    if not versions:
        raise RoutesError("прежних версий нет — откатывать нечего")
    last = versions[-1]
    data = _validate(json.loads(last.read_text(encoding="utf-8")))
    _write(path, data, {"action": "rollback", "point": last.name, "by": by}, backup=False)
    last.unlink()
    # Ключи в версиях не лежат, поэтому откат их не трогает (14.10.26). Единственное, что надо поправить, — имя:
    # если откатывается переименование, ключ возвращается к прежнему имени точки, иначе он остался бы у имени,
    # которого больше нет.
    ушли = set(now["endpoints"]) - set(data["endpoints"])
    пришли = set(data["endpoints"]) - set(now["endpoints"])
    if len(ушли) == 1 and len(пришли) == 1:
        было, стало = ушли.pop(), пришли.pop()
        if key_has(было) and not key_has(стало) and data["endpoints"][стало].get("key_source") == "value":
            key_rename(было, стало)
    return data["roles"]


def panel(full_keys: bool = False) -> dict:
    """Для панели «Мониторинг» супер-администратора: роли, точки по порядку, состояние каждой.
    Ключ не отдаётся никогда: `full_keys=True` (супер-администратор) — «ключ задан · …XXXX», иначе «ключ задан»."""
    try:
        data = _load()
    except (RoutesError, ValueError, OSError) as exc:
        # Файл не читается (16.10.26, Д2): сборка не идёт, править с пульта нечего — причина человеку.
        причина = f"файл маршрутов {_current_path()} не читается: {scrub(str(exc))[:300]}"
        return {"source": "error", "path": str(_current_path() or ""), "switchable": False,
                "note": f"Модели ролей не настроены — {причина}. Сборка документов не начнётся, вызовов модели нет. "
                        "Исправьте файл или откатите его из models.history/.",
                "not_configured": {r: причина for r in ("generate", "verify")}, "roles": {}}
    now = time.time()
    пустой = data is None
    if пустой:
        # Файла нет (16.10.26, Д2): переменные окружения модель не задают — роли «не настроены»; пульт начинает файл с
        # пустого (`_editable`), поэтому переключение доступно сразу.
        data = {"endpoints": {}, "roles": {}}
    roles = {}
    if "asr" not in data["roles"]:
        roles["asr"] = [{"name": "env-asr", "kind": "faster-whisper", "model": None, "url": "",
                         "state": "основная — из переменных (WEBAPP_WHISPER_MODEL)", "last_error": ""}]
    for role, names in data["roles"].items():
        rows = []
        for i, n in enumerate(names):
            ep = data["endpoints"][n]
            rest = int(_state.down_until.get(n, 0) - now)
            rows.append({"name": n, "kind": ep["kind"], "model": ep.get("model") or ep.get("callable"),
                         "url": ep.get("url", "") or (f"device: {ep.get('device', 'auto')}" if ep["kind"] == "faster-whisper" else ""),
                         "state": f"выведена ещё {rest} с" if rest > 0 else ("основная" if i == 0 else "запасная"),
                         "last_error": _state.last_error.get(n, ""), "external": is_external(ep),
                         "reasoning": ep.get("reasoning", "auto")})
        roles[role] = rows
    # Роль генерации или проверки без точки — «не настроена» (16.10.26, Д2): пустая цепочка и причина. Проверка без своей
    # точки идёт на точки генерации (исключение владельца 13.10.26) — показано явно, строками генерации с пометкой.
    # Договорённости (18.10.2026) — так же, как проверка: без своей точки — строки генерации с пометкой «как у черновика»;
    # в пульте роль видна, только если продукт её включил (`show_role`) или она уже есть в файле.
    inherited = {}
    for role in ("generate", "verify") + tuple(r for r in OPTIONAL_ROLES if r in _shown_roles or r in roles):
        if roles.get(role):
            continue
        if role in INHERIT_GENERATE and roles.get("generate"):
            roles[role] = [dict(r, state="как у черновика — " + r["state"]) for r in roles["generate"]]
            inherited[role] = "generate"
        else:
            roles[role] = []
    # Ручной выбор: для каждой роли — все готовые точки подходящего рода (у распознавания — только свои движки).
    options = {}
    for role in ROLES:
        options[role] = [{"name": n, "model": ep.get("model") or ep.get("callable") or ep.get("url"), "kind": ep["kind"],
                          "external": is_external(ep)}
                         for n, ep in data["endpoints"].items()
                         if (ep["kind"] in ASR_KINDS) == (role == "asr") and not missing(ep)
                         and not (role == "asr" and is_external(ep))]
    # Справочник подключений: все точки, где используются, готовы ли.
    endpoints = []
    for n, ep in data["endpoints"].items():
        external = is_external(ep)
        endpoints.append({"name": n, "kind": ep["kind"],
                          "kind_title": KIND_FIELDS[ep["kind"]]["title"],
                          "fields": {k: v for k, v in ep.items() if k != "kind"},
                          "roles": [r for r in ROLES if n in data["roles"].get(r, [])],
                          "missing": missing(ep), "last_error": _state.last_error.get(n, ""),
                          "external": external,
                          "key": key_masked(n, full_keys) if ep.get("key_source") == "value" else "",
                          **({"tariff": _tariff_panel(ep)} if ep["kind"] in KINDS else {})})
    hist = _current_path().with_name("models.history")
    return {"source": "none" if пустой else "file", "path": str(_current_path()), "switchable": True,
            "not_configured": {r: (f"файла маршрутов нет ({_current_path()})" if пустой else
                                   "в «Моделях» роли не назначена модель")
                               for r in ("generate", "verify") if not roles.get(r)},
            "inherited": inherited,
            "note": (f"Файла маршрутов нет ({_current_path()}): модели ролей не назначены, сборка документов не начнётся. "
                     "Заведите подключение и назначьте его роли — файл создастся." if пустой else ""),
            "cooldown_sec": int(data.get("cooldown_sec", DEFAULT_COOLDOWN_SEC)), "roles": roles, "options": options,
            "endpoints": endpoints, "kinds": KIND_FIELDS, "role_titles": ROLE_TITLES, "history": history(),
            "tariff_book": llm_cost.справочник_для_формы(),
            "versions": len(list(hist.glob("models-*.json"))) if hist.exists() else 0}


def check_all() -> list[dict]:
    """Короткий запрос на каждую точку обеих ролей (стоит долей цента на облачных точках)."""
    out, seen = [], set()
    for role in ROLES:
        if role in OPTIONAL_ROLES and not own_chain(role):
            continue                         # необязательная роль без своей точки идёт на точки генерации — они выше
        причина = not_configured(role)
        if причина:
            out.append({"name": f"роль «{ROLE_TITLES.get(role, role)}»", "model": "", "ok": False,
                        "detail": f"{NOT_CONFIGURED} ({причина})"})
            continue
        for r in chain(role):
            if r.name in seen:
                continue
            seen.add(r.name)
            ok, info = ping(r)
            out.append({"name": r.name, "model": r.model or "", "ok": ok, "detail": info})
    return out


def asr_callable(route: Route):
    """Чем распознавать на точке рода python или asr-service: функция (текст, сводка) = f(путь к wav, **параметры)."""
    if route.kind == "asr-service":
        return _asr_service(route)
    import importlib
    folder = str(route.opt("path") or "").strip()
    if folder:
        if not os.path.isdir(folder):
            raise RoutesError(f"папки с кодом нет: {folder}")
        if folder not in sys.path:
            sys.path.insert(0, folder)
    module, _, func = str(route.opt("callable") or route.model).partition(":")
    return getattr(importlib.import_module(module), func)


def _asr_service(route: Route):
    """Сервис распознавания во внутренней сети. Два протокола (12.10.26):

    * `form=multipart` — современный: multipart/form-data, поле `file`, параметры полями формы,
      `wait=true` — ждать результат сразу (поле `form` в точке). Так отвечает, например, audioCintezPro
      (`/transcribe`): поля `file`, `language`, `prompt`, `wait`, `diarization`, `identify_speakers`,
      ответ — JSON с `text`, `segments`, `speakers`, `duration`;
    * по умолчанию (`form` не задана) — прежний: POST телом `audio/wav`, параметры в строке запроса,
      ответ JSON `{text, meta}`. Он остаётся, потому что уже заведённые сервисы работают так.

    С 26.10.2026 (отчёт локальной машины: «Транс» рвёт соединение на wav 16 кГц + подсказка, m4a + подсказка принимает):
      * подсказка (`initial_prompt`, `hotwords`) в строку запроса не идёт. У формы raw с подсказкой запрос уходит
        multipart: запись полем `file`, параметры и подсказка полями формы под теми же именами. Без подсказки raw —
        как раньше, байт в байт. Прежний путь — `prompt_in=query` у точки;
      * `audio` у точки — формат звука: `wav` (по умолчанию, как было), `m4a` или `ogg` — сжать ffmpeg перед отправкой.
        Сжатие идёт во временную папку, она удаляется сразу после чтения; ffmpeg нет или он не справился — уходит wav,
        причина — в сводке (`audio_sent`).

    Разбор по голосам и разметку слов по умолчанию НЕ просим (`diarization=false`,
    `identify_speakers=false`, `word_timestamps=false`): их делает наш разбор, а лишняя работа на сервисе
    только удлиняет распознавание."""
    if not _internal_url(route.url):
        raise RoutesError("сервис распознавания — только во внутренней сети")
    форма = str(route.opt("form") or "").strip().lower()

    формат_звука = str(route.opt("audio") or "wav").strip().lower()
    подсказка_в_строке = str(route.opt("prompt_in") or "form").strip().lower() == "query"

    def run(wav_path, **params):
        данные, имя_файла, тип_звука, отправлено = _звук_для_сервиса(wav_path, формат_звука)
        язык = str(params.get("language") or "")
        подсказка = " ".join(ч for ч in (str(params.get("initial_prompt") or ""), str(params.get("hotwords") or "")) if ч)
        начало = time.monotonic()

        def собрать(raw: dict) -> tuple[str, dict]:
            """Текст и сводка в виде, который ждут продукты.

            Строки — «ЧЧ:ММ:СС<TAB>текст» из `segments`: продукты сопоставляют их с кусками речи по
            времени (`name_transcript_lines`), считают по ним строки и берут из них сроки встречи.
            Сплошной текст без меток ломал это (живой случай 12.10.26: «Транс» вернул один блок текста,
            имена говорящих не проставились), а отсутствие `model`/`device` в сводке роняло
            прикладывание расшифровки (`KeyError: 'model'`). Сводка всегда дополняется тем, что знает
            точка: имя точки — модель, «сервис в сети» — устройство, длительность — из ответа."""
            сегменты = raw.get("segments") if isinstance(raw.get("segments"), list) else []
            строки = []
            времена = []
            for сегмент in сегменты:
                if not isinstance(сегмент, dict):
                    continue
                реплика = str(сегмент.get("text") or "").strip()
                if not реплика:
                    continue
                старт = float(сегмент.get("start") or 0)
                конец = float(сегмент.get("end") or 0)
                секунды = int(старт)
                строки.append(f"{секунды // 3600:02d}:{секунды % 3600 // 60:02d}:{секунды % 60:02d}\t{реплика}")
                # Время каждой строки — для разделения по голосам: ERP подписывает строки и режет отрывки
                # «Разбора голосов» по этим меткам (иначе сервисная точка оставалась без голосов).
                времена.append([старт, конец if конец > старт else старт + 1.0])
            текст = "\n".join(строки) if строки else str(raw.get("text") or "")
            длительность = raw.get("duration") or raw.get("media_seconds") \
                or (raw.get("meta") or {}).get("media_seconds")
            мета = dict(raw.get("meta") or {})
            мета.setdefault("model", route.name)
            мета.setdefault("device", "сервис в сети")
            мета.update({
                "engine": route.url,
                "language": raw.get("language") or мета.get("language"),
                "duration": длительность,
                "media_seconds": round(float(длительность)) if длительность else None,
                "lines": len(строки) or len([строка for строка in текст.splitlines() if строка.strip()]),
                "elapsed_seconds": round(time.monotonic() - начало),
                "speakers": raw.get("speaker_count") or мета.get("speakers"),
                "segments": len(сегменты),
                "segment_lines": строки,
                "segment_times": времена,
            })
            мета.update(отправка)
            return текст, {k: v for k, v in мета.items() if v not in (None, [], "")}

        # Что ушло сервису — в сводку распознавания (26.10.2026): формат и размер звука, где была подсказка.
        отправка = {"audio_sent": отправлено, "audio_bytes": len(данные)}

        def отправить_форму(поля: list[tuple[str, str]]) -> dict:
            """multipart/form-data собираем руками: своя библиотека тут не нужна, а зависимостей не добавляем."""
            граница = "----webapp-asr-" + uuid.uuid4().hex
            поле_файла = str(route.opt("file_field") or "file")
            части: list[bytes] = []
            for имя, значение in поля:
                if значение == "":
                    continue
                части.append(f"--{граница}\r\nContent-Disposition: form-data; name=\"{имя}\"\r\n\r\n{значение}\r\n"
                             .encode("utf-8"))
            части.append(f"--{граница}\r\nContent-Disposition: form-data; name=\"{поле_файла}\"; "
                         f"filename=\"{имя_файла}\"\r\nContent-Type: {тип_звука}\r\n\r\n".encode("utf-8"))
            части.append(данные + b"\r\n")
            части.append(f"--{граница}--\r\n".encode("utf-8"))
            тело = b"".join(части)
            req = urllib.request.Request(route.url, data=тело, method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={граница}",
                                                  "Content-Length": str(len(тело))})
            with urllib.request.urlopen(req, timeout=float(route.opt("timeout_sec", 4 * 3600))) as resp:
                return json.loads(resp.read().decode("utf-8"))

        if форма != "multipart":
            query = {k: v for k, v in params.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != ""}
            есть_подсказка = any(query.get(k) for k in ПОДСКАЗКА_ПОЛЯ)
            if есть_подсказка and not подсказка_в_строке:
                # Подсказка в строке запроса — несколько килобайт после urlencode (кириллица — 6 знаков на букву): сервер
                # вправе оборвать такую строку. Подсказка и параметры — полями формы под прежними именами (26.10.2026).
                отправка["prompt_sent"] = "поле формы"
                return собрать(отправить_форму([(str(k), str(v)) for k, v in query.items()]))
            if есть_подсказка:
                отправка["prompt_sent"] = "строка запроса"
            url = route.url + (("&" if "?" in route.url else "?") + urllib.parse.urlencode(query) if query else "")
            req = urllib.request.Request(url, data=данные, headers={"Content-Type": тип_звука}, method="POST")
            with urllib.request.urlopen(req, timeout=float(route.opt("timeout_sec", 4 * 3600))) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            return собрать(raw)

        поля = [("language", язык), ("prompt", подсказка), ("wait", "true"),
                ("diarization", "false"), ("identify_speakers", "false"), ("word_timestamps", "false")]
        поля += [(str(k), str(v)) for k, v in (route.opt("extra_fields") or {}).items()]
        if подсказка:
            отправка["prompt_sent"] = "поле формы"
        return собрать(отправить_форму(поля))

    return run


def _ffmpeg() -> str | None:
    """ffmpeg для сжатия звука: тот же портативный, что вынимает звук из записи (imageio_ffmpeg), иначе из PATH."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 — нет пакета или в нём нет файла: ищем в PATH
        import shutil
        return shutil.which("ffmpeg")


def _звук_для_сервиса(wav_path, формат: str) -> tuple[bytes, str, str, str]:
    """Звук для точки `asr-service` (26.10.2026): (данные, имя файла, тип, что отправлено).

    wav — файл как есть (поведение до 26.10.2026). m4a или ogg — сжатие ffmpeg во временную папку, которая удаляется
    сразу после чтения: запись на диске не остаётся. ffmpeg нет или он не справился — уходит wav, а в «что отправлено»
    — причина: распознавание не встаёт из-за сжатия."""
    import subprocess
    import tempfile

    исходный = Path(wav_path)
    расширение, тип, кодек = АУДИО_ФОРМАТЫ.get(формат) or АУДИО_ФОРМАТЫ["wav"]
    как_есть = (исходный.read_bytes(), исходный.name or "audio.wav", "audio/wav")
    if кодек is None:
        return (*как_есть, "wav")
    exe = _ffmpeg()
    if not exe:
        return (*как_есть, f"wav (сжать в {формат} нечем: ffmpeg не найден)")
    # ogg: Opus, если в сборке ffmpeg его нет — Vorbis
    кодеки = [кодек] + ([["-c:a", "libvorbis", "-q:a", "3"]] if формат == "ogg" else [])
    причина = ""
    with tempfile.TemporaryDirectory(prefix="asr-") as папка:
        выход = Path(папка) / ("audio" + расширение)
        for к in кодеки:
            try:
                готово = subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(исходный), "-vn", "-ac", "1", *к,
                                         str(выход)], capture_output=True, timeout=1800)
            except Exception as exc:  # noqa: BLE001 — сжатие не должно останавливать распознавание
                причина = f"{type(exc).__name__}"
                continue
            if готово.returncode == 0 and выход.exists() and выход.stat().st_size > 0:
                return выход.read_bytes(), (исходный.stem or "audio") + расширение, тип, формат
            причина = (готово.stderr or b"").decode("utf-8", "replace").strip()[-200:] or f"код {готово.returncode}"
    return (*как_есть, f"wav (сжать в {формат} не удалось: {причина})")


def _тихий_wav(секунды: float = 0.1, частота: int = 16000) -> bytes:
    """Крошечный wav тишины — проба для проверки связи с сервисом распознавания."""
    import io
    import struct
    import wave

    буфер = io.BytesIO()
    with wave.open(буфер, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(частота)
        w.writeframes(struct.pack("<h", 0) * int(частота * секунды))
    return буфер.getvalue()


def ping(route: Route, timeout: float = 60, api_key: str | None = None) -> tuple[bool, str]:
    """Короткий запрос «ответь: да» — жива ли точка. Для распознавания — без звука: на месте ли модель, находится ли
    код. Для команды check и кнопки «Проверить связь», не для рабочих вызовов. `api_key` — ключ из формы
    «Проверить связь» (вместо ключа точки); в ответ и журналы он не попадает."""
    ok, detail = _ping(route, timeout, api_key)
    return ok, scrub(detail, extra=(api_key,) if api_key else ())


def _ping(route: Route, timeout: float, api_key: str | None) -> tuple[bool, str]:
    if route.kind == "python":
        try:
            asr_callable(route)
            return True, f"код найден: {route.opt('callable') or route.model}"
        except Exception as exc:  # noqa: BLE001
            return False, f"код не найден: {type(exc).__name__}: {exc}"
    if route.kind == "asr-service":
        if not _internal_url(route.url):
            return False, "адрес не во внутренней сети — голос туда не уйдёт"
        # Проверяем тем же путём, каким идёт работа: пробный запрос с крошечным звуком тишины (12.10.26).
        # Раньше шёл GET, и сервис распознавания (он принимает только запросы распознавания) отвечал 405 —
        # панель показывала это как ошибку, хотя сервис был жив. Теперь по ответу видно и связь, и то, что
        # сервис принял нашу форму запроса и ответил текстом.
        import concurrent.futures
        import tempfile

        путь = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(_тихий_wav())
                путь = f.name
            # Пробу ограничиваем по времени: у точки свой рабочий таймаут (часы), а проверка связи должна
            # отвечать за минуту — иначе «Проверить связь» на замершем сервисе висела бы часами.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as пул:
                итог = пул.submit(asr_callable(route), путь, language="ru")
                текст, _сводка = итог.result(timeout=min(timeout, 60))
            return True, f"сервис отвечает и принял пробный запрос (в ответе символов: {len(текст or '')})"
        except concurrent.futures.TimeoutError:
            return False, f"сервис не ответил за {min(timeout, 60):.0f} с — проверьте, работает ли он"
        except urllib.error.HTTPError as exc:
            тело = ""
            try:
                тело = exc.read().decode("utf-8", "replace")[:160]
            except Exception:  # noqa: BLE001 — тело нужно лишь для подсказки
                тело = ""
            return False, (f"сервис ответил, но запрос распознавания отклонён (HTTP {exc.code}"
                           + (f": {тело}" if тело else "") + ") — проверьте адрес и форму запроса у точки")
        except Exception as exc:  # noqa: BLE001
            return False, f"сервис не отвечает: {type(exc).__name__}: {exc}"
        finally:
            if путь:
                try:
                    os.unlink(путь)
                except OSError:
                    pass
    if route.kind == "faster-whisper":
        model = route.model or os.environ.get("WEBAPP_WHISPER_MODEL", "large-v3")
        if _state.asr_check is not None:
            ok, why = _state.asr_check(model)
            return bool(ok), (f"модель на месте: {model}, device {route.opt('device', 'auto')}" if ok else str(why))
        return os.path.isdir(model), f"папка модели {'есть' if os.path.isdir(model) else 'не найдена'}: {model}"
    model = route.model or os.environ.get("QWEN_MODEL", "")
    if route.kind == "ollama":
        body = {"model": model, "messages": [{"role": "user", "content": "Ответь одним словом: да"}], "stream": False}
    else:
        body = {"model": model, "messages": [{"role": "user", "content": "Ответь одним словом: да"}], "max_tokens": 20}
        apply_reasoning(body, route)   # «Проверить связь» — тем же телом, что рабочий вызов
        apply_model_limits(body, route, model)   # Claude: без temperature и top_p (15.10.26)
    key = route.api_key if api_key is None else api_key
    if route.kind == "ollama":
        адрес, headers = route.endpoint, {"Content-Type": "application/json"}
    else:
        адрес, body, headers = wire_request(route, body, key)   # у точки Anthropic — родной Messages API (26.10.2026)
    req = mark_request(urllib.request.Request(адрес, data=json.dumps(body).encode("utf-8"), headers=headers,
                                              method="POST"), route)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = response_text(raw)
        return True, f"ответ за {time.time() - started:.1f} с: {(text or '').strip()[:40]!r}"
    except urllib.error.HTTPError as exc:
        try:
            тело = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — тело нужно лишь для подсказки
            тело = ""
        if exc.code == 401:
            return False, key_rejected_reason(тело, extra=(key,) if key else ())
        if exc.code == 403:
            return False, forbidden_reason(тело, extra=(key,) if key else ())
        return False, f"HTTP {exc.code}: {scrub(тело, extra=(key,) if key else ())[:160]}"
    except Exception as exc:  # noqa: BLE001 — для проверки достаточно текста ошибки
        return False, f"{type(exc).__name__}: {exc}"


# --- Пробный запрос перед сборкой (решение владельца 14.10.26) ---------------------------------------------------
#
# Сборка Протокола и Плана узнавала о неготовой модели только через 25–36 минут повторов: каждая попытка ждала
# порог молчания, потом шли повторы и запасные точки. Замер 14.10.26 на qwen показал, почему короткая «Проверить
# связь» об этом не говорит: на 15 тыс. знаков первый кусок ответа приходит за 11 с, на 156 тыс. — ничего за 300 с.
# Готовность к БОЕВОМУ запросу проверяется только запросом боевого размера.
#
# Поэтому перед сборкой первой доступной точке роли уходит пробный запрос: настоящее начало первого запроса сборки
# (системная подсказка и запись встречи — тот же префикс, что уйдёт следом: сервер вроде Ollama держит кэш
# последнего запроса, и боевой вызов не читает запись заново). Ответа целиком проба не ждёт: первый признак жизни
# (content, reasoning_content, reasoning или thinking — как в чтении потока рабочих вызовов; с 26.10.2026 и скрытое
# рассуждение: остановка по потолку, расход выхода, блок рассуждения Anthropic — `stream_piece`) — точка готова, поток
# закрывается. Не готова — нет связи, 401 (ключ не принят), 403 (доступ запрещён), 400 и прочие отказы сервера, молчание дольше порога
# или поток, закончившийся без единого знака. Порог первого признака по умолчанию — порог молчания самой сборки
# (его передаёт продукт), чтобы проба не браковала модель, которую сборка дождалась бы. Предел ответа маленький
# (64 токена; у модели Claude — не меньше PROBE_CLAUDE_MIN_TOKENS, 26.10.2026): ответ обрывается на первом признаке.
#
# Настройки — в одном месте: умолчания ниже, переменные окружения MODEL_PROBE* и раздел "probe" в models.json
# (рядом с cooldown_sec, перечитывается без перезапуска). Файл сильнее переменных, переменные сильнее умолчаний.
PROBE_DEFAULTS = {
    "enabled": True,          # пробный запрос перед сборкой включён
    "first_sign_sec": None,   # первый признак жизни — не дольше; None — порог молчания сборки (передаёт продукт)
    "fresh_sec": 600,         # точка, прошедшая пробу недавно, повторно не проверяется
    "max_tokens": 64,         # предел ответа пробы: ответ обрывается на первом признаке жизни
    # Модель не готова — сборка ждёт (решение владельца 17.10.26, С5 сведения): повтор пробы каждые retry_sec, всего
    # не дольше wait_sec; потом — отказ «модель не готова» (карточка и сообщение, как прежде). 0 — не ждать.
    "retry_sec": 300,
    "wait_sec": 3600,
}
PROBE_FIRST_SIGN_FALLBACK = 600    # если продукт порог молчания не передал
PROBE_ENV = {"enabled": "MODEL_PROBE", "first_sign_sec": "MODEL_PROBE_FIRST_SIGN_SEC",
             "fresh_sec": "MODEL_PROBE_FRESH_SEC", "max_tokens": "MODEL_PROBE_MAX_TOKENS",
             "retry_sec": "MODEL_PROBE_RETRY_SEC", "wait_sec": "MODEL_PROBE_WAIT_SEC"}
PROBE_SYSTEM = ("Это пробный запрос: проверяется, готова ли модель принять запрос такого размера. "
                "Текст ниже не разбирай.")
_PROBE_FILLER = "\nПробный запрос проверки готовности модели перед сборкой документа."


def _как_да_нет(значение) -> bool | None:
    if isinstance(значение, bool):
        return значение
    низ = str(значение).strip().lower()
    if низ in ("1", "on", "yes", "true", "да", "вкл"):
        return True
    if низ in ("0", "off", "no", "false", "нет", "выкл"):
        return False
    return None


def _probe_check(section) -> None:
    """Раздел "probe" в models.json: неверное поле — ошибка сразу, как у остальных полей файла."""
    if not isinstance(section, dict):
        raise RoutesError("раздел probe — объект, например {\"enabled\": true, \"first_sign_sec\": 600}")
    for ключ, значение in section.items():
        if ключ not in PROBE_DEFAULTS:
            raise RoutesError(f"раздел probe: неизвестное поле «{ключ}» — допустимы {', '.join(PROBE_DEFAULTS)}")
        if ключ == "enabled":
            if _как_да_нет(значение) is None:
                raise RoutesError("раздел probe: enabled — true или false")
        elif isinstance(значение, bool) or not isinstance(значение, (int, float)) or значение <= 0:
            raise RoutesError(f"раздел probe: {ключ} — положительное число")


def probe_settings(silence_sec: float | None = None) -> dict:
    """Действующие настройки пробного запроса: умолчания, поверх — переменные окружения, поверх — models.json.
    `silence_sec` — порог молчания сборки у продукта: им становится порог первого признака, если он не задан."""
    итог = dict(PROBE_DEFAULTS)
    for ключ, имя in PROBE_ENV.items():
        сырое = os.environ.get(имя, "").strip()
        if not сырое:
            continue
        if ключ == "enabled":
            да = _как_да_нет(сырое)
            if да is not None:
                итог[ключ] = да
            continue
        try:
            число = float(сырое)
        except ValueError:
            continue
        if число > 0 or (ключ in ("retry_sec", "wait_sec") and число == 0):   # 0 — ожидание выключено
            итог[ключ] = число
    try:
        data = _load()
    except (RoutesError, OSError, ValueError):
        data = None
    for ключ, значение in ((data or {}).get("probe") or {}).items():
        if ключ == "enabled":
            итог[ключ] = bool(_как_да_нет(значение))
        elif ключ in итог:
            итог[ключ] = значение
    if not итог["first_sign_sec"]:
        # Не меньше 600 с, даже если порог молчания сборки короче (в старом коде он 300): первая попытка точки
        # в сборке ждёт 600 с, а qwen на сервере Ollama читает запись в 180 тыс. знаков минутами (14.10.26).
        итог["first_sign_sec"] = max(float(silence_sec or 0), PROBE_FIRST_SIGN_FALLBACK)
    итог["max_tokens"] = max(1, int(итог["max_tokens"]))
    return итог


def _probe_key(route: Route, model: str) -> tuple:
    return (route.name, route.url, model or route.model or "")


def probe_fresh(route: Route, model: str, settings: dict | None = None) -> bool:
    """Точка прошла пробу недавно — повторно не проверяем (соседние шаги одной сборки, пересборка)."""
    s = settings or probe_settings()
    with _lock:
        когда = _state.probe_ok.get(_probe_key(route, model))
    return когда is not None and time.time() - когда <= float(s["fresh_sec"])


def probe_forget() -> None:
    """Забыть удачные пробы (для тестов и после смены модели вручную)."""
    with _lock:
        _state.probe_ok.clear()


def probe_messages(chars: int, system: str | None = None, user: str | None = None) -> list[dict]:
    """Сообщения пробы. Есть настоящее начало первого запроса сборки (`system`, `user`) — оно и уходит, без единого
    изменения: тот же префикс, что у боевого вызова. Сборка сообщила, что её главный запрос длиннее (`chars`), — в
    конец дописывается служебный текст до этой длины (префикс при этом не меняется). Начала нет — служебный текст."""
    if system is None and user is None:
        system, user = PROBE_SYSTEM, ""
    system, user = system or "", user or ""
    нужно = int(chars) - len(system) - len(user)
    if нужно > 0:
        user += (_PROBE_FILLER * (нужно // len(_PROBE_FILLER) + 1))[:нужно]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _read_timeout(resp, секунд: float) -> None:
    """Предел ожидания следующего куска потока — остаток порога первого признака. Без этого строки служебных
    событий без токенов держали бы пробу дольше порога."""
    try:
        resp.fp.raw._sock.settimeout(max(0.05, секунд))
    except Exception:  # noqa: BLE001 — нет доступа к сокету: остаётся таймаут соединения
        pass


def _probe_http_reason(code: int, detail: str) -> str:
    if code == 401:
        return key_rejected_reason(detail)
    if code == 403:
        return forbidden_reason(detail)
    if code == 402:
        return "на счёте поставщика нет денег (HTTP 402)"
    if code == 404:
        return f"модели нет на сервере (HTTP 404): {detail[:160]}"
    if code == 429 or code >= 500:
        return f"сервер модели перегружен или не в порядке (HTTP {code}): {detail[:160]}"
    if code == 400 and any(п in detail.lower() for п in ("model unloaded", "model is unloaded", "not loaded",
                                                          "no model loaded")):
        return f"модель выгружена из памяти сервера (HTTP 400): {detail[:160]}"
    return f"запрос отклонён (HTTP {code}): {detail[:160]}"


# --- Разбор куска потока: OpenAI-совместимый, OpenRouter, Anthropic Messages API (26.10.2026) ------------------------
#
# Пустой поток Claude на стенде 26.10.26 (проба 133 593 знака, «поток закончился без единого знака ответа или
# рассуждения», сборка ушла на запасную). У Claude Sonnet 5.5 и Opus 5.5 рассуждение адаптивное и включено по
# умолчанию (выключить нельзя: `thinking: disabled` — 400), а его текст по умолчанию не отдаётся (`display: "omitted"`:
# блок рассуждения приходит пустым). Рассуждение тратит тот же потолок ответа (skill claude-api, разделы Thinking &
# Effort и Migrating to Claude Sonnet 5.5, сверено 26.10.2026). Потолок пробы 64 токена целиком ушёл на скрытый ход
# мысли: поток кончился остановкой по потолку без видимого знака, а проба считала признаком жизни только знак.
# Признак жизни — то, что модель пишет, а не только то, что нам видно: знак текста или рассуждения; остановка по
# потолку и расход выхода; блок, подпись или знак рассуждения Anthropic; зашифрованное рассуждение OpenRouter.
# Ошибка поставщика внутри уже открытого потока (`event: error` Anthropic, `{"error": …}` OpenAI) — отдельно.
STOP_REASON_AS_OPENAI = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
                         "tool_use": "tool_calls"}
STREAM_TEXT_FIELDS = ("content",)
STREAM_REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking")


def stream_piece(часть) -> dict:
    """Один разобранный кусок потока → {"text", "reasoning", "alive", "finish", "usage", "error", "end"}.

    `alive` — модель пишет (в том числе скрыто): для пробы это готовность, для сборки — признак жизни сторожу молчания.
    `finish` — причина остановки в словах OpenAI (stop / length / …), у Anthropic переведена. `end` — поставщик сам
    закрыл ответ (`message_stop` Anthropic): поток кончился штатно, а не оборвался."""
    итог = {"text": "", "reasoning": "", "alive": False, "finish": None, "usage": None, "error": "", "end": False}
    if not isinstance(часть, dict):
        return итог
    род = часть.get("type")
    if род == "error" or (род is None and isinstance(часть.get("error"), (dict, str))):
        ошибка = часть.get("error")
        if isinstance(ошибка, dict):
            итог["error"] = " ".join(str(ошибка.get(к)) for к in ("type", "code", "message") if ошибка.get(к)) or "error"
        else:
            итог["error"] = str(ошибка or "error")
        return итог
    if isinstance(род, str) and (род.startswith(("message_", "content_block_")) or род == "ping"):
        # Anthropic Messages API: message_start → content_block_start → content_block_delta … → message_delta → stop
        if род == "message_start":
            итог["usage"] = ((часть.get("message") or {}).get("usage")) or None
        elif род == "content_block_start":
            блок = часть.get("content_block") or {}
            if блок.get("type") in ("thinking", "redacted_thinking", "text", "tool_use"):
                итог["alive"] = True
                итог["text"] = блок.get("text") or "" if блок.get("type") == "text" else ""
                итог["reasoning"] = блок.get("thinking") or "" if блок.get("type") == "thinking" else ""
        elif род == "content_block_delta":
            дельта = часть.get("delta") or {}
            вид = дельта.get("type")
            if вид == "text_delta":
                итог["text"] = дельта.get("text") or ""
            elif вид == "thinking_delta":
                итог["reasoning"] = дельта.get("thinking") or ""
            итог["alive"] = вид in ("text_delta", "thinking_delta", "signature_delta", "input_json_delta")
        elif род == "message_delta":
            причина = (часть.get("delta") or {}).get("stop_reason")
            if причина:
                итог["finish"] = STOP_REASON_AS_OPENAI.get(причина, причина)
            итог["usage"] = часть.get("usage") or None
            итог["alive"] = итог["finish"] == "length" or bool((итог["usage"] or {}).get("output_tokens"))
        elif род == "message_stop":
            итог["end"] = True
        if итог["text"] or итог["reasoning"]:
            итог["alive"] = True
        return итог
    # OpenAI-совместимый поток (свой сервер, DeepSeek, вход Anthropic /v1/chat/completions) и OpenRouter.
    if часть.get("message") and not часть.get("choices"):
        дельта = часть.get("message") or {}     # родной поток Ollama
    else:
        выбор = (часть.get("choices") or [{}])[0] or {}
        дельта = выбор.get("delta") or {}
        итог["finish"] = выбор.get("finish_reason") or None
    итог["usage"] = часть.get("usage") or None
    for поле in STREAM_TEXT_FIELDS:
        if isinstance(дельта.get(поле), str):
            итог["text"] += дельта[поле]
    for поле in STREAM_REASONING_FIELDS:
        if isinstance(дельта.get(поле), str):
            итог["reasoning"] += дельта[поле]
    подробности = дельта.get("reasoning_details")
    if isinstance(подробности, list):
        # OpenRouter: рассуждение блоками; у Claude с display omitted — зашифрованное, без текста (reasoning: null)
        if not итог["reasoning"]:
            итог["reasoning"] = "".join(str(п.get("text") or п.get("summary") or "") for п in подробности
                                        if isinstance(п, dict))
        if подробности:
            итог["alive"] = True
    выход = (итог["usage"] or {}).get("completion_tokens") or (итог["usage"] or {}).get("output_tokens")
    if итог["text"] or итог["reasoning"] or итог["finish"] == "length" or выход:
        итог["alive"] = True
    return итог


# Потолок пробы у модели Claude (26.10.2026): рассуждение у Claude 5.x скрыто и тратит потолок, 64 токенов не хватает,
# чтобы после него пришёл хоть один знак ответа. Остановка по потолку и без того признак жизни — порог нужен, чтобы
# проба обычно доходила до текста. Цена порога — не больше 2048 токенов выхода (≈0,02 $ у Sonnet 5.5): поток
# закрывается на первом знаке.
PROBE_CLAUDE_MIN_TOKENS = 2048


def probe_max_tokens(route: "Route", model: str | None, settings: dict) -> int:
    """Потолок ответа пробы: из настроек, у модели Claude — не меньше `PROBE_CLAUDE_MIN_TOKENS`."""
    потолок = int(settings["max_tokens"])
    if route.kind in ("openai", "openrouter") and is_claude(model or route.model):
        потолок = max(потолок, PROBE_CLAUDE_MIN_TOKENS)
    return потолок


def probe(route: Route, *, chars: int = 0, system: str | None = None, user: str | None = None,
          model: str | None = None, api_key: str | None = None, extra: dict | None = None,
          settings: dict | None = None) -> dict:
    """Пробный запрос на одну точку. Возвращает замер: готова ли, причина, длина входа, время до первого признака
    жизни. Ответ целиком не ждём: первый признак — готова, поток закрываем. Ключ идёт только в заголовок; из причины
    его вычищает `scrub`."""
    s = settings or probe_settings()
    порог = float(s["first_sign_sec"])
    сообщения = probe_messages(chars, system, user)
    модель = model or route.model or os.environ.get("QWEN_MODEL", "")
    if route.kind == "ollama":
        body = {"model": модель, "messages": сообщения, "stream": True}
    else:
        # Claude (26.10.2026): потолок не меньше PROBE_CLAUDE_MIN_TOKENS — скрытое рассуждение тратит его первым
        body = {"model": модель, "messages": сообщения, "max_tokens": probe_max_tokens(route, модель, s),
                "stream": True}
    for ключ_поля, значение in (extra or {}).items():
        body.setdefault(ключ_поля, значение)
    if route.kind != "ollama":
        # Рассуждение у точки выключено — проба идёт тем же телом, что рабочий вызов (14.10.26). Поверх extra:
        # у openrouter продукт кладёт reasoning по своей модели, а настройка точки сильнее.
        apply_reasoning(body, route)
        # Claude (15.10.26): продукт кладёт в extra temperature — у Claude она даёт 400; здесь, после extra, — одним
        # местом для пробы обоих продуктов (`_проба_перед_сборкой` в Планёрке и в ERP идёт сюда через probe_role).
        apply_model_limits(body, route, модель)
    if route.kind == "ollama":
        body.setdefault("options", {}).setdefault("num_predict", int(s["max_tokens"]))
    итог = {"point": route.name, "model": модель, "kind": route.kind, "external": route.external,
            "chars_in": sum(len(m["content"]) for m in сообщения), "first_sign_sec": None, "seconds": 0.0,
            "ok": False, "reason": "", "first_sign_limit_sec": порог}
    ключ = route.api_key if api_key is None else api_key
    if route.kind == "ollama":
        адрес, тело_запроса, headers = route.endpoint, body, {"Content-Type": "application/json"}
    else:
        # тем же входом, что рабочий вызов: у точки Anthropic — родной Messages API с усилием (26.10.2026)
        адрес, тело_запроса, headers = wire_request(route, body, ключ)
    req = mark_request(urllib.request.Request(адрес, data=json.dumps(тело_запроса).encode("utf-8"), headers=headers,
                                              method="POST"), route)
    начало = time.monotonic()
    молчит = f"модель молчит дольше {порог:g} с — первый признак жизни не пришёл"

    def _готово(ok: bool, причина: str = "", дошёл: bool = False) -> dict:
        итог["seconds"] = round(time.monotonic() - начало, 2)
        if дошёл or ok:
            # Запрос дошёл до модели — поставщик берёт за весь вход пробы (это начало первого запроса сборки), хотя
            # поток закрыт на первом знаке и `usage` нет: сумма — оценкой по знакам (20.10.2026, заход 3 хаос-тестов)
            try:
                тариф, _ = tariff_for(route, модель)
                цена = llm_cost.стоимость_вызова({}, тариф, знаков_вход=итог["chars_in"],
                                                 знаков_выход=int(llm_cost.ЗНАКОВ_НА_ТОКЕН))
                if цена.get("cost_usd") is not None:
                    итог["cost_usd"], итог["cost_source"] = цена["cost_usd"], цена["cost_source"]
                    # пик по UTC момента пробы (заход 4, 20.10.2026): сверка баланса с журналом видит, где тариф двойной
                    if "peak" in цена:
                        итог["peak"] = цена["peak"]
            except Exception:  # noqa: BLE001 — подсчёт денег не роняет пробу
                pass
        if ok:
            итог["first_sign_sec"] = итог["seconds"]
            with _lock:
                _state.probe_ok[_probe_key(route, модель)] = time.time()
        итог["ok"], итог["reason"] = ok, scrub(причина, extra=(ключ,) if ключ else ())
        return итог

    try:
        resp = urllib.request.urlopen(req, timeout=порог)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = ""
        return _готово(False, _probe_http_reason(exc.code, scrub(detail, extra=(ключ,) if ключ else ())))
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
        причина = getattr(exc, "reason", exc)
        if isinstance(exc, TimeoutError) or isinstance(причина, TimeoutError) or "timed out" in str(exc).lower():
            return _готово(False, молчит)
        return _готово(False, f"нет связи с сервером модели: {type(exc).__name__}: {exc}")
    конец_ответа = False          # поставщик закрыл ответ сам: [DONE], message_stop, остановка, done у Ollama
    try:
        with resp:
            while True:
                прошло = time.monotonic() - начало
                if прошло > порог:
                    return _готово(False, молчит, дошёл=True)
                _read_timeout(resp, порог - прошло)
                try:
                    строка = resp.readline()
                except (TimeoutError, OSError, ValueError):
                    return _готово(False, молчит, дошёл=True)
                if not строка:
                    break
                текст = строка.decode("utf-8", errors="replace").strip()
                if текст.startswith("data:"):
                    текст = текст[5:].strip()
                if not текст or текст == "[DONE]":
                    if текст == "[DONE]":
                        конец_ответа = True
                        break
                    continue
                try:
                    часть = json.loads(текст)
                except ValueError:
                    continue                      # `event: …` Anthropic, `: OPENROUTER PROCESSING` и прочие служебные
                if not isinstance(часть, dict):
                    continue
                # Разбор — общий с чтением сборки (26.10.2026): OpenAI-совместимый, OpenRouter, Anthropic Messages API.
                кусок = stream_piece(часть)
                if кусок["error"]:
                    return _готово(False, f"поставщик прислал ошибку в потоке: {кусок['error'][:160]}", дошёл=True)
                if кусок["alive"]:
                    if time.monotonic() - начало > порог:
                        return _готово(False, молчит, дошёл=True)
                    # Каким признаком — в замер и журнал: видно, что модель думала скрыто, а не ответила текстом
                    итог["first_sign"] = ("текст ответа" if кусок["text"] else "текст рассуждения" if кусок["reasoning"]
                                          else "остановка по потолку, рассуждение скрыто" if кусок["finish"] == "length"
                                          else "блок рассуждения или расход выхода, рассуждение скрыто")
                    return _готово(True)          # первый признак жизни — готова; поток закрывает with
                if кусок["finish"] or кусок["end"]:
                    конец_ответа = True
                if route.kind == "ollama" and часть.get("done"):
                    конец_ответа = True
                    break
    except Exception as exc:  # noqa: BLE001 — обрыв посреди ответа: точка не готова, причина — человеку
        return _готово(False, f"ответ оборвался: {type(exc).__name__}: {exc}", дошёл=True)
    if not конец_ответа:
        # Ни остановки, ни [DONE], ни message_stop — поток оборвала сеть или прокси, а не модель (26.10.2026)
        return _готово(False, "поток оборвался до конца ответа (нет остановки и [DONE]) — связь или прокси точки",
                       дошёл=True)
    return _готово(False, "поток закончился без единого знака ответа или рассуждения", дошёл=True)


def probe_role(role: str, *, chars: int = 0, system: str | None = None, user: str | None = None,
               env: dict | None = None, prepare=None, journal=None,
               settings: dict | None = None) -> tuple[bool, list[dict]]:
    """Пробный запрос по цепочке роли: первая готовая точка — (True, замеры).

    `prepare(route, первая) -> (модель, ключ, доп. поля запроса)` — продукт сообщает то, что знает только он: модель
    по своим умолчаниям, ключ режима «из переменных», поля рассуждения и num_ctx — проба идёт тем же путём, что
    рабочий вызов. Точка, прошедшая пробу недавно, повторно не проверяется. Неготовая точка при нескольких в цепочке
    выводится на охлаждение тем же предохранителем, что отказ рабочего вызова, и проба идёт на следующую; одна
    точка в цепочке на охлаждение не ставится (прежнее правило). Ни одной готовой — (False, замеры)."""
    s = settings or probe_settings()
    routes = chain(role, env)
    замеры: list[dict] = []
    for i, route in enumerate(routes):
        try:
            модель, ключ, доп = prepare(route, i == 0) if prepare else (route.model, None, None)
        except Exception as exc:  # noqa: BLE001 — нет ключа, запрещённая модель: точка не готова, причина — человеку
            замер = {"point": route.name, "model": route.model or "", "kind": route.kind, "external": route.external,
                     "chars_in": 0, "first_sign_sec": None, "seconds": 0.0, "ok": False,
                     "reason": scrub(str(exc)), "role": role}
        else:
            if probe_fresh(route, модель or "", s):
                return True, замеры
            замер = probe(route, chars=chars, system=system, user=user, model=модель, api_key=ключ, extra=доп,
                          settings=s)
            замер["role"] = role
        if journal:
            try:
                journal(замер)
            except Exception:  # noqa: BLE001 — журнал не роняет пробу
                pass
        замеры.append(замер)
        if замер["ok"]:
            mark_up(route)
            return True, замеры
        if len(routes) > 1:
            mark_down(route, "пробный запрос: " + замер["reason"])
    return False, замеры


def probe_role_waiting(role: str, *, on_wait=None, sleep=None, clock=None, **kw) -> tuple[bool, list[dict], int, float]:
    """Пробный запрос с ожиданием (решение владельца 17.10.26, С5 сведения): точка не готова — повтор каждые
    `retry_sec` (5 мин), всего не дольше `wait_sec` (1 ч), потом (False, замеры последней попытки). Ожидание не снимает
    предохранители и охлаждение точек — повтор идёт тем же `probe_role`. `on_wait(попытка, замеры, осталось_сек,
    пауза_сек)` — продукту: признак жизни сторожу очереди и строка в сообщениях. Возвращает (готова, замеры,
    попыток, ждали_сек)."""
    s = kw.get("settings") or probe_settings()
    kw["settings"] = s
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    пауза = max(0.0, float(s.get("retry_sec") or 0))
    всего = max(0.0, float(s.get("wait_sec") or 0))
    начало = clock()
    попытка = 0
    while True:
        попытка += 1
        готова, замеры = probe_role(role, **kw)
        прошло = clock() - начало
        if готова or not пауза or прошло + пауза > всего:
            return готова, замеры, попытка, прошло
        if on_wait:
            on_wait(попытка, замеры, всего - прошло, пауза)
        sleep(пауза)


def _main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if "--path" in argv:
        i = argv.index("--path")
        _state.path = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    cmd = argv[0] if argv else "show"
    try:
        if cmd == "show":
            print(json.dumps(status(), ensure_ascii=False, indent=2))
        elif cmd == "use" and len(argv) == 3:
            print(json.dumps(use(argv[1], argv[2], by="командная строка"), ensure_ascii=False, indent=2))
        elif cmd == "check":
            for r in check_all():
                print(f"{'ок  ' if r['ok'] else 'НЕТ '} {r['name']:<20} {r['model'] or '(распознавание из переменных)'} — {r['detail']}")
        else:
            print(__doc__)
            return 2
    except RoutesError as exc:
        print(f"Ошибка маршрутов: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
