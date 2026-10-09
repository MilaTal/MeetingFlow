"""Маршруты моделей — третий инструмент подключения, MEETFLOW_LLM=routes (решение владельца 09.10.26).

Модели не вшиты в переменные окружения: у роли (генерация, проверка) — упорядоченная цепочка именованных точек
в файле `models.json`. Первая доступная обслуживает вызов. Точка, которая не ответила (`ConnectorUnavailable`:
нет связи, 5xx/429 после повторов, нет ключа или денег, модели нет на сервере), выводится на время охлаждения
(предохранитель), и вызов уходит на следующую. Ошибка самого запроса и оборванный ответ на другую точку не
переносятся: они повторились бы и там.

Формат файла тот же, что у Планёрки и ERP (`model_routes.py`), чтобы один файл описывал серверы компании:

    {"endpoints": {"or-qwen":  {"kind": "openrouter", "model": "qwen/qwen-plus"},
                   "lmstudio": {"kind": "openai", "url": "http://192.168.100.59:1234", "model": "qwen3.8-27b"},
                   "ollama":   {"kind": "ollama", "url": "http://localhost:11434", "model": "glm-4.7-flash"}},
     "roles": {"generate": ["or-qwen", "lmstudio"], "verify": ["ollama", "or-qwen"]},
     "cooldown_sec": 300}

`kind`: openrouter — облако, ключ OPENROUTER_API_KEY; openai — свой OpenAI-совместимый сервер (url без /v1,
ключ — необязательная переменная из `key_env`); ollama — родной протокол Ollama. Удалённый адрес Ollama нужно
разрешить явно: `"allow_remote": true`. Роль `asr` — распознавание речи (09.10.26): только локальные движки —
`faster-whisper` (model — имя или путь к папке модели, device — auto, cuda или cpu) или `python` (callable —
ссылка на свой код «модуль:функция», path — папка с кодом) или `asr-service` (сервис распознавания во внутренней
сети, адрес только внутренний); облачных точек у этой роли нет.

Справочник и работа оператора (09.10.26, по образцу шлюзов моделей — LiteLLM, Portkey, Kong/Envoy AI Gateway):
подключение заводится заранее, даже без адреса — заготовка «не настроена» в роль не попадает; «Проверить связь»
до сохранения; ключ — только имя переменной окружения; каждое изменение кладёт прежнюю версию в `models.history/`,
«Откатить» возвращает её; в `models.log.jsonl` — когда, что и кто. Формат и роды те же, что у Планёрки и ERP.
Путь к файлу — MODEL_ROUTES_PATH, иначе `data/models.json`. Файл
перечитывается при изменении: переключение — поменять порядок в `roles` или `python -m meetflow routes use
generate lmstudio`, без перезапуска.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path

from .base import ConnectorError, ConnectorUnavailable, LLMConnector
from .llm_ollama import OllamaLLM
from .llm_openrouter import OpenRouterLLM
from ..core.types import LLMResult

KINDS = ("openrouter", "openai", "ollama")
ASR_KINDS = ("faster-whisper", "python", "asr-service")
ROLES = ("generate", "verify", "asr")
ROLE_TITLES = {"asr": "Распознавание речи", "generate": "Генерация черновика", "verify": "Проверка черновика"}
HISTORY_KEEP = 30
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Что оператор заполняет у точки каждого рода — по этому описанию вкладка «Модели» строит форму подключения.
KIND_FIELDS = {
    "openai": {"title": "Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1)", "for": "text",
               "fields": [{"key": "url", "label": "Адрес сервера, без /v1", "hint": "http://192.168.100.59:1234", "required": True},
                          {"key": "model", "label": "Модель на сервере", "hint": "deepseek-flash", "required": True},
                          {"key": "key_env", "label": "Переменная окружения с ключом, если сервер его просит", "hint": "LLM_API_KEY"}]},
    "ollama": {"title": "Ollama, родной протокол", "for": "text",
               "fields": [{"key": "url", "label": "Адрес сервера", "hint": "http://localhost:11434", "required": True},
                          {"key": "model", "label": "Модель", "hint": "qwen3:8b", "required": True}]},
    "openrouter": {"title": "OpenRouter — облако, только для текста", "for": "text",
                   "fields": [{"key": "model", "label": "Модель OpenRouter", "hint": "qwen/qwen-plus", "required": True},
                              {"key": "key_env", "label": "Переменная окружения с ключом", "hint": "OPENROUTER_API_KEY", "default": "OPENROUTER_API_KEY"}]},
    "faster-whisper": {"title": "Whisper на этой машине (faster-whisper)", "for": "asr",
                       "fields": [{"key": "model", "label": "Модель: имя или путь к папке", "hint": "large-v3 или D:/models/whisper-large-v3", "required": True},
                                  {"key": "device", "label": "Устройство", "choices": ["auto", "cuda", "cpu"], "default": "auto"}]},
    "python": {"title": "Свой код распознавания на этой машине", "for": "asr",
               "fields": [{"key": "callable", "label": "Функция: модуль:функция", "hint": "asr_engine:transcribe", "required": True},
                          {"key": "path", "label": "Папка с кодом, если код не установлен пакетом", "hint": "D:/asr/engine"}]},
    "asr-service": {"title": "Сервис распознавания во внутренней сети", "for": "asr",
                    "fields": [{"key": "url", "label": "Адрес сервиса (только внутренняя сеть)", "hint": "http://192.168.100.60:9000/transcribe", "required": True}]},
}
SIDE_TO_ROLE = {"generator": "generate", "verifier": "verify"}


def routes_path() -> Path:
    return Path(os.environ.get("MODEL_ROUTES_PATH", "").strip() or "data/models.json")


def internal_url(url: str) -> bool:
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


def missing(ep: dict) -> str:
    """Чего не хватает точке, чтобы работать; пусто — готова. Заготовка допустима в справочнике, но не в роли."""
    need = [f["key"] for f in KIND_FIELDS.get(ep.get("kind"), {}).get("fields", []) if f.get("required")]
    names = {"url": "не задан адрес (url)", "model": "не задана модель (model)", "callable": "не задана функция (callable)"}
    return "; ".join(names.get(k, f"не задано поле {k}") for k in need if not str(ep.get(k) or "").strip())


def check_point(name: str, ep: dict) -> None:
    """Неверно заполненное поле — ошибка сразу; пустое обязательное — заготовка (см. missing)."""
    kind = ep.get("kind")
    if kind not in KINDS + ASR_KINDS:
        raise ConnectorError(f"точка «{name}»: kind должен быть одним из {', '.join(KINDS + ASR_KINDS)}")
    for bad in ("key", "api_key", "token", "password"):
        if ep.get(bad):
            raise ConnectorError(f"точка «{name}»: ключи в файле не хранятся — укажите имя переменной окружения в key_env")
    key_env = str(ep.get("key_env") or "")
    if key_env and (not _ENV_NAME.match(key_env) or len(key_env) > 60):
        raise ConnectorError(f"точка «{name}»: key_env — имя переменной окружения (например OPENROUTER_API_KEY), а не сам ключ")
    if kind == "python" and ep.get("callable") and ":" not in str(ep["callable"]):
        raise ConnectorError(f"точка «{name}»: callable — ссылка на код «модуль:функция»")
    url = str(ep.get("url") or "")
    if url and not url.startswith(("http://", "https://")):
        raise ConnectorError(f"точка «{name}»: адрес начинается с http:// или https://")
    if kind == "asr-service" and url and not internal_url(url):
        raise ConnectorError(f"точка «{name}»: сервис распознавания — только во внутренней сети, голос не покидает периметр")
    if kind == "faster-whisper" and ep.get("device", "auto") not in ("auto", "cuda", "cpu"):
        raise ConnectorError(f"точка «{name}»: device — auto, cuda или cpu")


def validate(data: dict) -> dict:
    eps, roles = data.get("endpoints"), data.get("roles")
    if not isinstance(eps, dict) or not eps:
        raise ConnectorError("в models.json нет раздела endpoints или он пуст")
    if not isinstance(roles, dict) or "generate" not in roles:
        raise ConnectorError("в models.json нет раздела roles с ролью generate")
    for name, ep in eps.items():
        check_point(name, ep)
    for role, chain in roles.items():
        unknown = [n for n in chain or [] if n not in eps]
        if not chain or unknown:
            raise ConnectorError(f"роль «{role}»: пустая цепочка или неизвестные точки {', '.join(unknown)}")
        for n in chain:
            if (eps[n]["kind"] in ASR_KINDS) != (role == "asr"):
                raise ConnectorError(
                    f"роль «{role}», точка «{n}»: распознавание идёт только локальными движками (faster-whisper или "
                    f"свой код), а языковой модели нужна точка openrouter, openai или ollama" if role == "asr" else
                    f"роль «{role}», точка «{n}»: движок распознавания не годится для языковой модели")
            gap = missing(eps[n])
            if gap:
                raise ConnectorError(f"роль «{role}»: точка «{n}» не настроена — {gap}")
    return data


def _ordered(names: list[str]) -> list[str]:
    now = time.time()
    live = [n for n in names if RoutedLLM._down_until.get(n, 0) <= now]
    return live + [n for n in names if n not in live]


def asr_chain(path: Path | None = None):
    """Цепочка распознавания из файла: [(имя, точка)], охлаждение — или None, если файла или роли asr нет
    (тогда WhisperLocalASR работает как раньше, на модели темы)."""
    path = path or routes_path()
    if not path.exists():
        return None
    data = validate(json.loads(path.read_text(encoding="utf-8")))
    names = data["roles"].get("asr")
    if not names:
        return None
    return [(n, data["endpoints"][n]) for n in _ordered(names)], int(data.get("cooldown_sec", 300))


def mark_down(name: str, cooldown: int) -> None:
    with RoutedLLM._lock:
        RoutedLLM._down_until[name] = time.time() + cooldown


def mark_up(name: str) -> None:
    with RoutedLLM._lock:
        RoutedLLM._down_until.pop(name, None)


class RoutedLLM(LLMConnector):
    """Цепочка точек одной роли. Атрибуты модели (model, profile, context_chars…) — у первой живой точки."""
    name = "routes"

    _down_until: dict[str, float] = {}       # общий для генерации и проверки: сервер лёг для обеих ролей
    _lock = threading.RLock()

    def __init__(self, side: str, max_answer_tokens: int = 4096, path: Path | None = None,
                 factory=None):
        self.role = SIDE_TO_ROLE.get(side, side)
        self.max_answer_tokens = max_answer_tokens
        self.path = path or routes_path()
        self._factory = factory or self._make
        self._mtime: float | None = None
        self._data: dict = {}
        self._connectors: dict[str, LLMConnector] = {}
        self.last_route = ""
        self._load()

    # --- файл и точки -------------------------------------------------------------------------------------
    def _load(self) -> dict:
        if not self.path.exists():
            raise ConnectorError(f"MEETFLOW_LLM=routes, но файла маршрутов нет: {self.path}")
        mtime = self.path.stat().st_mtime
        with self._lock:
            if mtime != self._mtime:
                self._data = validate(json.loads(self.path.read_text(encoding="utf-8")))
                self._mtime, self._connectors = mtime, {}
        return self._data

    def _make(self, name: str, ep: dict) -> LLMConnector:
        kind, model, profile = ep["kind"], ep["model"], ep.get("profile", "generic")
        if kind == "openrouter":
            return OpenRouterLLM(model=model, profile=profile, max_answer_tokens=self.max_answer_tokens)
        if kind == "openai":
            return OpenRouterLLM(model=model, profile=profile, max_answer_tokens=self.max_answer_tokens,
                                 api_base=ep["url"].rstrip("/") + "/v1", key_env=ep.get("key_env", ""),
                                 label=f"{ep['url']} ({name})")
        return OllamaLLM(model=model, profile=profile, url=ep["url"], num_ctx=int(ep.get("num_ctx", 32768)),
                         allow_remote=bool(ep.get("allow_remote")), max_answer_tokens=self.max_answer_tokens)

    def connector(self, name: str) -> LLMConnector:
        data = self._load()
        if name not in self._connectors:
            self._connectors[name] = self._factory(name, data["endpoints"][name])
        return self._connectors[name]

    def chain(self) -> list[str]:
        data = self._load()
        return _ordered(data["roles"].get(self.role) or data["roles"]["generate"])

    @property
    def _primary(self) -> LLMConnector:
        return self.connector(self.chain()[0])

    # --- то, что конвейер читает у подключения -------------------------------------------------------------
    @property
    def model(self) -> str:
        return getattr(self._primary, "model", "")

    @property
    def profile(self) -> str:
        return getattr(self._primary, "profile", "generic")

    @property
    def context_chars(self) -> int:
        return min(int(getattr(self.connector(n), "context_chars", 0) or 10**9) for n in self.chain())

    def worst_call_usd(self, prompt_chars: int) -> float | None:
        """Худший случай — по самой дорогой точке цепочки: при переходе вызов может уйти на неё."""
        costs = [self.connector(n).worst_call_usd(prompt_chars) for n in self.chain()]
        known = [c for c in costs if c is not None]
        return max(known) if known else None

    def health(self) -> dict:
        names = self.chain()
        now = time.time()
        return {"name": self.name, "ok": True, "role": self.role, "chain": names,
                "down": {n: int(t - now) for n, t in self._down_until.items() if t > now},
                "primary": self.connector(names[0]).health()}

    # --- вызов --------------------------------------------------------------------------------------------
    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult:
        names = self.chain()
        cooldown = int(self._load().get("cooldown_sec", 300))
        errors = []
        for name in names:
            try:
                res = self.connector(name).complete(system, user, json_mode=json_mode, temperature=temperature,
                                                    purpose=purpose, deadline=deadline)
            except ConnectorUnavailable as e:
                with self._lock:
                    self._down_until[name] = time.time() + cooldown
                errors.append(f"{name}: {e}")
                continue
            with self._lock:
                self._down_until.pop(name, None)
            self.last_route = name
            if isinstance(res.raw, dict):
                res.raw.setdefault("route", name)
            return res
        raise ConnectorUnavailable("Ни одна точка роли «%s» не ответила — %s" % (self.role, "; ".join(errors)))


def panel(path: Path | None = None) -> dict:
    """Для вкладки «Модели» мониторинга супер-администратора: роли, точки по порядку, состояние каждой, и для
    ручного выбора — все точки, подходящие роли (options). Распознавание переключается при любом инструменте
    модели (asr_switchable), генерация и проверка — только при MEETFLOW_LLM=routes."""
    path = path or routes_path()
    active = os.environ.get("MEETFLOW_LLM", "mock").strip().lower() == "routes"
    if not path.exists():
        return {"switchable": False, "path": str(path), "roles": {},
                "note": "Файла маршрутов нет — модель задана инструментом MEETFLOW_LLM. Чтобы переключать модели "
                        "с панели, положите models.json (образец — docs/models.example.json) и запустите с MEETFLOW_LLM=routes."}
    data = validate(json.loads(path.read_text(encoding="utf-8")))
    now = time.time()
    roles = {}
    for role, names in data["roles"].items():
        rows = []
        for i, n in enumerate(names):
            ep = data["endpoints"][n]
            rest = int(RoutedLLM._down_until.get(n, 0) - now)
            rows.append({"name": n, "kind": ep["kind"], "model": ep.get("model") or ep.get("callable") or ep.get("url"),
                         "url": ep.get("url", "") or ep.get("device", ""),
                         "state": f"выведена ещё {rest} с" if rest > 0 else ("основная" if i == 0 else "запасная")})
        roles[role] = rows
    options = {role: [{"name": n, "model": ep.get("model") or ep.get("callable") or ep.get("url"), "kind": ep["kind"]}
                      for n, ep in data["endpoints"].items()
                      if (ep["kind"] in ASR_KINDS) == (role == "asr") and not missing(ep)]
               for role in ROLES}
    endpoints = [{"name": n, "kind": ep["kind"], "kind_title": KIND_FIELDS[ep["kind"]]["title"],
                  "fields": {k: v for k, v in ep.items() if k != "kind"},
                  "roles": [r for r in ROLES if n in data["roles"].get(r, [])], "missing": missing(ep)}
                 for n, ep in data["endpoints"].items()]
    hist = path.with_name("models.history")
    return {"switchable": active, "asr_switchable": True, "path": str(path),
            "cooldown_sec": int(data.get("cooldown_sec", 300)), "roles": roles, "options": options,
            "endpoints": endpoints, "kinds": KIND_FIELDS, "role_titles": ROLE_TITLES, "history": history(path),
            "versions": len(list(hist.glob("models-*.json"))) if hist.exists() else 0, "editable": True,
            "note": "" if active else "Файл есть, но сервер запущен не с MEETFLOW_LLM=routes — выбор генерации и "
                                      "проверки не действует; распознавание переключается."}


def check_all(path: Path | None = None) -> list[dict]:
    """Короткий запрос на каждую точку обеих ролей (на облачных точках — доли цента); у распознавания — проверка
    без записи: движок установлен, модель на диске, код находится."""
    out, seen = [], set()
    routes = asr_chain(path)
    if routes:
        from .asr_whisper import asr_ping
        for name, ep in routes[0]:
            seen.add(name)
            ok, detail = asr_ping(ep)
            out.append({"name": name, "model": ep.get("model") or ep.get("callable"), "ok": ok, "detail": detail})
    for side in ("generator", "verifier"):
        llm = RoutedLLM(side, path=path)
        for name in llm.chain():
            if name in seen:
                continue
            seen.add(name)
            try:
                res = llm.connector(name).complete("Отвечай одним словом.", "Ответь: да", json_mode=False)
                out.append({"name": name, "model": res.model, "ok": True,
                            "detail": f"ответ за {res.seconds:.1f} с: {res.text.strip()[:30]!r}"})
            except Exception as e:  # noqa: BLE001 — для проверки достаточно текста ошибки
                out.append({"name": name, "model": "", "ok": False, "detail": str(e)[:200]})
    return out


def _editable(path: Path | None) -> tuple[Path, dict]:
    path = path or routes_path()
    if not path.exists():
        raise ConnectorError(f"файла маршрутов нет: {path} — образец docs/models.example.json")
    return path, validate(json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, data: dict, record: dict, backup: bool = True) -> dict:
    """Проверить, сохранить прежнюю версию в models.history/, записать атомарно, отметить в журнале."""
    validate(data)
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
    try:
        with open(path.with_name("models.log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict({"at": time.strftime("%Y-%m-%d %H:%M:%S")}, **record), ensure_ascii=False) + "\n")
    except OSError:
        pass   # журнал — справка; его сбой не отменяет изменение
    return data


def _role_and_point(data: dict, role: str, name: str) -> None:
    if role not in ROLES:
        raise ConnectorError(f"нет роли «{role}»")
    if name not in data["endpoints"]:
        raise ConnectorError(f"нет точки «{name}»")


def use(role: str, name: str, path: Path | None = None, by: str = "") -> dict:
    """Поставить точку первой в роли и записать файл: работающие подключения подхватят его без перезапуска.
    Переключение пишется строкой в `models.log.jsonl` рядом с файлом: когда, роль, точка, кто."""
    path, data = _editable(path)
    _role_and_point(data, role, name)
    data["roles"][role] = [name] + [n for n in data["roles"].get(role, []) if n != name]
    _write(path, data, {"action": "use", "role": role, "point": name, "by": by})
    RoutedLLM._down_until.pop(name, None)
    return data["roles"]


def add_to_role(role: str, name: str, path: Path | None = None, by: str = "") -> dict:
    """Добавить точку в конец цепочки роли — запасной."""
    path, data = _editable(path)
    _role_and_point(data, role, name)
    chain = data["roles"].get(role, [])
    if name in chain:
        raise ConnectorError(f"точка «{name}» уже в роли «{ROLE_TITLES.get(role, role)}»")
    data["roles"][role] = chain + [name]
    _write(path, data, {"action": "add", "role": role, "point": name, "by": by})
    return data["roles"]


def remove_from_role(role: str, name: str, path: Path | None = None, by: str = "") -> dict:
    """Убрать точку из цепочки роли; последняя точка роли остаётся."""
    path, data = _editable(path)
    _role_and_point(data, role, name)
    chain = data["roles"].get(role, [])
    if name not in chain:
        raise ConnectorError(f"точки «{name}» нет в роли «{ROLE_TITLES.get(role, role)}»")
    if len(chain) == 1:
        raise ConnectorError(f"«{name}» — единственная точка роли «{ROLE_TITLES.get(role, role)}»: сначала добавьте другую")
    data["roles"][role] = [n for n in chain if n != name]
    _write(path, data, {"action": "remove", "role": role, "point": name, "by": by})
    return data["roles"]


def clean_point(fields: dict) -> dict:
    """Поля формы → точка: только поля её рода и пояснение, пустые необязательные отброшены."""
    kind = str(fields.get("kind") or "").strip()
    if kind not in KIND_FIELDS:
        raise ConnectorError(f"род подключения — один из: {', '.join(KIND_FIELDS)}")
    ep = {"kind": kind}
    for f in KIND_FIELDS[kind]["fields"]:
        value = str(fields.get(f["key"]) or "").strip() or f.get("default", "")
        if value or f.get("required"):
            ep[f["key"]] = value
    note = str(fields.get("note") or "").strip()
    if note:
        ep["note"] = note[:300]
    return ep


def save_point(name: str, fields: dict, path: Path | None = None, by: str = "", old_name: str = "") -> dict:
    """Завести или изменить подключение. Без адреса или модели — заготовка «не настроена». Переименование правит
    и цепочки ролей."""
    name = (name or "").strip()
    if not name or len(name) > 60 or "|" in name:
        raise ConnectorError("имя подключения — до 60 знаков, без «|»")
    path, data = _editable(path)
    ep = clean_point(fields)
    check_point(name, ep)
    old_name = (old_name or "").strip()
    if old_name and old_name not in data["endpoints"]:
        raise ConnectorError(f"нет точки «{old_name}»")
    if name in data["endpoints"] and name != old_name:
        raise ConnectorError(f"подключение «{name}» уже есть — выберите другое имя или измените его")
    if old_name and old_name != name:
        data["endpoints"] = {(name if k == old_name else k): v for k, v in data["endpoints"].items()}
        data["roles"] = {r: [name if n == old_name else n for n in ch] for r, ch in data["roles"].items()}
    data["endpoints"][name] = ep
    _write(path, data, {"action": "edit" if old_name else "new", "point": name,
                        **({"was": old_name} if old_name and old_name != name else {}), "by": by})
    RoutedLLM._down_until.pop(name, None)
    return ep


def delete_point(name: str, path: Path | None = None, by: str = "") -> None:
    """Удалить подключение; из ролей оно уходит само, но единственную точку роли удалить нельзя."""
    path, data = _editable(path)
    if name not in data["endpoints"]:
        raise ConnectorError(f"нет точки «{name}»")
    for role, chain in data["roles"].items():
        if chain == [name]:
            raise ConnectorError(f"«{name}» — единственная точка роли «{ROLE_TITLES.get(role, role)}»: сначала добавьте другую")
    data["roles"] = {r: [n for n in ch if n != name] for r, ch in data["roles"].items()}
    del data["endpoints"][name]
    _write(path, data, {"action": "delete", "point": name, "by": by})


def test_point(fields: dict) -> tuple[bool, str]:
    """«Проверить связь» по полям формы — до сохранения."""
    ep = clean_point(fields)
    check_point("проверка", ep)
    gap = missing(ep)
    if gap:
        return False, f"не настроена — {gap}"
    if ep["kind"] in ASR_KINDS:
        from .asr_whisper import asr_ping
        return asr_ping(ep)
    llm = RoutedLLM.__new__(RoutedLLM)
    llm.max_answer_tokens = 64
    try:
        res = RoutedLLM._make(llm, "проверка", ep).complete("Отвечай одним словом.", "Ответь: да", json_mode=False)
        return True, f"ответ за {res.seconds:.1f} с: {res.text.strip()[:30]!r}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def history(path: Path | None = None, limit: int = 8) -> list[dict]:
    """Последние изменения файла маршрутов из журнала, новые сверху."""
    log = (path or routes_path()).with_name("models.log.jsonl")
    if not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[::-1]


def rollback(path: Path | None = None, by: str = "") -> dict:
    """Вернуть файл к версии до последнего изменения. Повторный откат идёт ещё на шаг назад."""
    path, _ = _editable(path)
    hist = path.with_name("models.history")
    versions = sorted(hist.glob("models-*.json")) if hist.exists() else []
    if not versions:
        raise ConnectorError("прежних версий нет — откатывать нечего")
    last = versions[-1]
    data = validate(json.loads(last.read_text(encoding="utf-8")))
    _write(path, data, {"action": "rollback", "point": last.name, "by": by}, backup=False)
    last.unlink()
    return data["roles"]
