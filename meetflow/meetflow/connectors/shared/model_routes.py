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
окружения с ключом. Файла нет — маршруты собираются из прежних переменных (LLM_PROVIDER, QWEN_MODEL,
QWEN_VERIFY_MODEL, LLM_BASE_URL, LLM_VERIFY_BASE_URL…), то есть поведение без файла прежнее.

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

Пробный запрос перед сборкой (решение владельца 14.10.26): перед сборкой Протокола и Плана первой доступной точке
роли уходит настоящее начало первого запроса сборки — о неготовой модели известно сразу, а не после 25–36 минут
повторов; готова — по первому признаку жизни. Настройки — раздел "probe" в файле (рядом с cooldown_sec) или
переменные MODEL_PROBE*; first_sign_sec не задан — берётся порог молчания сборки:
    "probe": {"enabled": true, "first_sign_sec": 600, "fresh_sec": 600, "max_tokens": 64}
Подробно — у `probe_settings` и `probe_role` ниже.

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
ROLES = ("generate", "verify", "asr")
ROLE_TITLES = {"asr": "Распознавание речи", "generate": "Генерация черновика", "verify": "Проверка черновика"}
_BASE_KEYS = ("kind", "model", "url", "key_env")
DEFAULT_COOLDOWN_SEC = 300
HISTORY_KEEP = 30
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEYS_FILE = "model_keys.local.json"        # ключи значением — рядом с models.json, в git и выгрузки не идут
KEY_SOURCES = ("env", "value")              # имя переменной окружения или само значение (14.10.26)
PROXY_MODES = ("system", "none")            # внешняя точка: через системный прокси (по умолчанию) или напрямую
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
    {"key": "proxy", "label": "Прокси — для внешней точки", "choices": list(PROXY_MODES),
     "choice_titles": {"system": "системный", "none": "без прокси"}},
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
                                "hint": "raw — wav телом, параметры в строке (прежний протокол); multipart — поля формы и file (audioCintezPro /transcribe)"}]},
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
        """Внешняя точка ходит через прокси (системный или адресом точки); локальная — мимо прокси."""
        return self.external and self.opt("proxy", "system") != "none"

    @property
    def proxy_address(self) -> str:
        """Адрес прокси точки, если в «Моделях» выбран вариант «адрес» (как в Планёрке, 16.10.26)."""
        value = str(self.opt("proxy", "") or "")
        return value if value.startswith(("http://", "https://")) else ""

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
    def proxy_open(self, req, proxy, type):  # noqa: A002 — подпись urllib
        if getattr(req, "_model_routes_direct", False):
            return None                       # мимо прокси: следующий обработчик откроет соединение напрямую
        return super().proxy_open(req, proxy, type)


def _install_opener() -> None:
    if getattr(urllib.request, "_model_routes_opener", False):
        return
    urllib.request.install_opener(urllib.request.build_opener(_ProxyByRoute()))
    urllib.request._model_routes_opener = True


_install_opener()


def mark_request(req: urllib.request.Request, route: "Route") -> urllib.request.Request:
    """Пометить запрос к точке: локальная или внешняя без прокси — напрямую, внешняя — через системный прокси или
    адрес прокси точки (как в Планёрке, 16.10.26)."""
    addr = route.proxy_address
    if addr:
        from urllib.parse import urlsplit
        u = urlsplit(addr)
        req.set_proxy(u.netloc, u.scheme)      # https-точка — туннелем CONNECT через этот прокси
        req._model_routes_direct = False
        req._model_routes_proxy = addr
        return req
    req._model_routes_direct = not route.uses_proxy
    return req


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
    if proxy not in PROXY_MODES and not (isinstance(proxy, str) and proxy.startswith(("http://", "https://"))):
        raise RoutesError(f"точка «{name}»: proxy — system (системный прокси), none (без прокси) или адрес "
                          f"http://… / https://…")
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


def _validate(data: dict) -> dict:
    eps = data.get("endpoints")
    roles = data.get("roles")
    if not isinstance(eps, dict) or not eps:
        raise RoutesError("в models.json нет раздела endpoints или он пуст")
    if not isinstance(roles, dict) or "generate" not in roles:
        raise RoutesError("в models.json нет раздела roles с ролью generate")
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


def _from_env(role: str, env: dict | None = None) -> list[Route]:
    """Прежнее поведение без файла: один маршрут на роль, собранный из настроек продукта.

    `env` — текущие значения из модуля продукта (LLM_PROVIDER, OLLAMA_URL, LLM_BASE_URL, LLM_VERIFY_BASE_URL):
    продукт читает их при импорте, а тесты подменяют их в модуле, поэтому брать надо оттуда, а не из os.environ."""
    env = env or {}
    if role == "asr":
        return [Route("env-asr", "faster-whisper", None, from_env=True)]
    get = lambda k, d: (env.get(k) if env.get(k) is not None else os.environ.get(k, d))  # noqa: E731
    provider = (get("LLM_PROVIDER", _state.default_provider) or _state.default_provider).strip()
    base = (get("LLM_BASE_URL", "http://localhost:1234") or "").rstrip("/")
    if provider == "ollama":
        route = Route("env", "ollama", None, get("OLLAMA_URL", "http://localhost:11434"), from_env=True)
    elif provider == "openrouter":
        route = Route("env", "openrouter", None, key_env="OPENROUTER_API_KEY", from_env=True)
    else:
        route = Route("env", "openai", None, base, key_env="LLM_API_KEY", from_env=True)
    verify_url = (get("LLM_VERIFY_BASE_URL", "") or "").rstrip("/")
    if role == "verify" and verify_url and provider != "ollama":
        route = Route("env-verify", "openai", None, verify_url, key_env="LLM_VERIFY_API_KEY", from_env=True)
    return [route]


def chain(role: str, env: dict | None = None) -> list[Route]:
    """Цепочка точек роли по порядку; выведенные предохранителем — в конце (если живых нет, пробуем и их)."""
    data = _load()
    if data is None:
        return _from_env(role, env)
    if role == "asr" and "asr" not in data["roles"]:
        return _from_env(role, env)          # распознавание в файл не вынесено — как раньше, по переменным
    names = data["roles"].get(role) or data["roles"]["generate"]
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
        return {"source": "переменные окружения", "path": str(_current_path() or ""),
                "roles": {r: [x.name for x in _from_env(r)] for r in ROLES}, "down": {}}
    return {"source": "файл", "path": str(_current_path()), "roles": data["roles"],
            "endpoints": {n: {k: v for k, v in ep.items() if k != "key"} for n, ep in data["endpoints"].items()},
            "down": {n: int(t - now) for n, t in _state.down_until.items() if t > now},
            "last_error": dict(_state.last_error)}


def _editable() -> tuple[Path, dict]:
    path = _current_path()
    data = _load()
    if data is None or path is None:
        raise RoutesError("файла маршрутов нет — править нечего; создайте models.json (образец — models.example.json)")
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
        (hist / f"models-{stamp}.json").write_bytes(path.read_bytes())
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
    if len(chain_) == 1:
        raise RoutesError(f"«{name}» — единственная точка роли «{ROLE_TITLES.get(role, role)}»: сначала добавьте другую")
    data["roles"][role] = [n for n in chain_ if n != name]
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
        if chain_ == [name]:
            raise RoutesError(f"«{name}» — единственная точка роли «{ROLE_TITLES.get(role, role)}»: сначала добавьте "
                              f"в роль другую")
    data["roles"] = {r: [n for n in ch if n != name] for r, ch in data["roles"].items()}
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
    data = _load()
    now = time.time()
    if data is None:
        return {"source": "env", "path": str(_current_path() or ""), "switchable": False,
                "note": "Файла маршрутов нет — модели заданы переменными окружения, переключать с панели нечего. "
                        "Чтобы включить переключение, положите models.json (образец — models.example.json).",
                "roles": {r: [{"name": x.name, "kind": x.kind, "model": None, "url": x.url, "state": "основная"}
                              for x in _from_env(r)] for r in ROLES}}
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
    return {"source": "file", "path": str(_current_path()), "switchable": True,
            "cooldown_sec": int(data.get("cooldown_sec", DEFAULT_COOLDOWN_SEC)), "roles": roles, "options": options,
            "endpoints": endpoints, "kinds": KIND_FIELDS, "role_titles": ROLE_TITLES, "history": history(),
            "tariff_book": llm_cost.справочник_для_формы(),
            "versions": len(list(hist.glob("models-*.json"))) if hist.exists() else 0}


def check_all() -> list[dict]:
    """Короткий запрос на каждую точку обеих ролей (стоит долей цента на облачных точках)."""
    out, seen = [], set()
    for role in ROLES:
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

    Разбор по голосам и разметку слов по умолчанию НЕ просим (`diarization=false`,
    `identify_speakers=false`, `word_timestamps=false`): их делает наш разбор, а лишняя работа на сервисе
    только удлиняет распознавание."""
    if not _internal_url(route.url):
        raise RoutesError("сервис распознавания — только во внутренней сети")
    форма = str(route.opt("form") or "").strip().lower()

    def run(wav_path, **params):
        данные = Path(wav_path).read_bytes()
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
            for сегмент in сегменты:
                if not isinstance(сегмент, dict):
                    continue
                реплика = str(сегмент.get("text") or "").strip()
                if not реплика:
                    continue
                секунды = int(float(сегмент.get("start") or 0))
                строки.append(f"{секунды // 3600:02d}:{секунды % 3600 // 60:02d}:{секунды % 60:02d}\t{реплика}")
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
            })
            return текст, {k: v for k, v in мета.items() if v not in (None, [], "")}

        if форма != "multipart":
            query = {k: v for k, v in params.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != ""}
            url = route.url + (("&" if "?" in route.url else "?") + urllib.parse.urlencode(query) if query else "")
            req = urllib.request.Request(url, data=данные, headers={"Content-Type": "audio/wav"}, method="POST")
            with urllib.request.urlopen(req, timeout=float(route.opt("timeout_sec", 4 * 3600))) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            return собрать(raw)

        # multipart/form-data собираем руками: своя библиотека тут не нужна, а зависимостей не добавляем.
        граница = "----webapp-asr-" + uuid.uuid4().hex
        поле_файла = str(route.opt("file_field") or "file")
        поля = [("language", язык), ("prompt", подсказка), ("wait", "true"),
                ("diarization", "false"), ("identify_speakers", "false"), ("word_timestamps", "false")]
        поля += [(str(k), str(v)) for k, v in (route.opt("extra_fields") or {}).items()]
        части: list[bytes] = []
        for имя, значение in поля:
            if значение == "":
                continue
            части.append(f"--{граница}\r\nContent-Disposition: form-data; name=\"{имя}\"\r\n\r\n{значение}\r\n"
                         .encode("utf-8"))
        имя_файла = Path(wav_path).name or "audio.wav"
        части.append(f"--{граница}\r\nContent-Disposition: form-data; name=\"{поле_файла}\"; "
                     f"filename=\"{имя_файла}\"\r\nContent-Type: audio/wav\r\n\r\n".encode("utf-8"))
        части.append(данные + b"\r\n")
        части.append(f"--{граница}--\r\n".encode("utf-8"))
        тело = b"".join(части)
        req = urllib.request.Request(route.url, data=тело, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={граница}",
                                              "Content-Length": str(len(тело))})
        with urllib.request.urlopen(req, timeout=float(route.opt("timeout_sec", 4 * 3600))) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return собрать(raw)

    return run


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
    headers = {"Content-Type": "application/json"}
    key = route.api_key if api_key is None else api_key
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = mark_request(urllib.request.Request(route.endpoint, data=json.dumps(body).encode("utf-8"), headers=headers,
                                              method="POST"), route)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = (raw.get("message") or {}).get("content") if route.kind == "ollama" else \
            ((raw.get("choices") or [{}])[0].get("message") or {}).get("content")
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
# (content, reasoning_content, reasoning или thinking — как в чтении потока рабочих вызовов) — точка готова, поток
# закрывается. Не готова — нет связи, 401 (ключ не принят), 403 (доступ запрещён), 400 и прочие отказы сервера, молчание дольше порога
# или поток, закончившийся без единого знака. Порог первого признака по умолчанию — порог молчания самой сборки
# (его передаёт продукт), чтобы проба не браковала модель, которую сборка дождалась бы. Предел ответа маленький
# (64 токена): ответ всё равно обрывается на первом признаке.
#
# Настройки — в одном месте: умолчания ниже, переменные окружения MODEL_PROBE* и раздел "probe" в models.json
# (рядом с cooldown_sec, перечитывается без перезапуска). Файл сильнее переменных, переменные сильнее умолчаний.
PROBE_DEFAULTS = {
    "enabled": True,          # пробный запрос перед сборкой включён
    "first_sign_sec": None,   # первый признак жизни — не дольше; None — порог молчания сборки (передаёт продукт)
    "fresh_sec": 600,         # точка, прошедшая пробу недавно, повторно не проверяется
    "max_tokens": 64,         # предел ответа пробы: ответ обрывается на первом признаке жизни
}
PROBE_FIRST_SIGN_FALLBACK = 600    # если продукт порог молчания не передал
PROBE_ENV = {"enabled": "MODEL_PROBE", "first_sign_sec": "MODEL_PROBE_FIRST_SIGN_SEC",
             "fresh_sec": "MODEL_PROBE_FRESH_SEC", "max_tokens": "MODEL_PROBE_MAX_TOKENS"}
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
        if число > 0:
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
        body = {"model": модель, "messages": сообщения, "max_tokens": int(s["max_tokens"]), "stream": True}
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
    headers = {"Content-Type": "application/json"}
    ключ = route.api_key if api_key is None else api_key
    if ключ:
        headers["Authorization"] = f"Bearer {ключ}"
    req = mark_request(urllib.request.Request(route.endpoint, data=json.dumps(body).encode("utf-8"), headers=headers,
                                              method="POST"), route)
    начало = time.monotonic()
    молчит = f"модель молчит дольше {порог:g} с — первый признак жизни не пришёл"

    def _готово(ok: bool, причина: str = "") -> dict:
        итог["seconds"] = round(time.monotonic() - начало, 2)
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
    try:
        with resp:
            while True:
                прошло = time.monotonic() - начало
                if прошло > порог:
                    return _готово(False, молчит)
                _read_timeout(resp, порог - прошло)
                try:
                    строка = resp.readline()
                except (TimeoutError, OSError, ValueError):
                    return _готово(False, молчит)
                if not строка:
                    break
                текст = строка.decode("utf-8", errors="replace").strip()
                if текст.startswith("data:"):
                    текст = текст[5:].strip()
                if not текст or текст == "[DONE]":
                    if текст == "[DONE]":
                        break
                    continue
                try:
                    часть = json.loads(текст)
                except ValueError:
                    continue
                if not isinstance(часть, dict):
                    continue
                if route.kind == "ollama":
                    дельта = часть.get("message") or {}
                else:
                    дельта = ((часть.get("choices") or [{}])[0] or {}).get("delta") or {}
                if any(isinstance(дельта.get(поле), str) and дельта.get(поле)
                       for поле in ("content", "reasoning_content", "reasoning", "thinking")):
                    if time.monotonic() - начало > порог:
                        return _готово(False, молчит)
                    return _готово(True)          # первый признак жизни — готова; поток закрывает with
                if route.kind == "ollama" and часть.get("done"):
                    break
    except Exception as exc:  # noqa: BLE001 — обрыв посреди ответа: точка не готова, причина — человеку
        return _готово(False, f"ответ оборвался: {type(exc).__name__}: {exc}")
    return _готово(False, "поток закончился без единого знака ответа или рассуждения")


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
                print(f"{'ок  ' if r['ok'] else 'НЕТ '} {r['name']:<20} {r['model'] or '(из переменных)'} — {r['detail']}")
        else:
            print(__doc__)
            return 2
    except RoutesError as exc:
        print(f"Ошибка маршрутов: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
