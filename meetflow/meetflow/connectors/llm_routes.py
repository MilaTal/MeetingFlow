"""Маршруты моделей — подключение моделей MeetFlow (решения владельца 09.10.26, 13.10.26, 15.10.26).

Модели не вшиты ни в код, ни в тему, ни в переменные окружения. У роли — генерация, проверка, досмотр, распознавание —
упорядоченная цепочка именованных точек в `data/models.json` (путь — MODEL_ROUTES_PATH). Первая доступная обслуживает
вызов; точка, которая не ответила, выводится на время охлаждения, и вызов уходит на следующую.

Модели по умолчанию нет (правило владельца 13.10.26 для ERP, Планёрки и MeetFlow; ответ владельца 15.10.26): роль без
точек — «не настроена», вызова нет, подстановки чужой роли нет. Заготовки подключений (DeepSeek, Claude по ключу,
OpenRouter, локальная qwen, Whisper) лежат в справочнике без адресов и ключей и в роль не попадают, пока
супер-администратор их не заполнит.

Общее с ERP и Планёркой — модули `shared/model_routes.py` и `shared/llm_cost.py`, копии байт в байт (правятся там и
переносятся целиком): проверка точки и её полей, разбор формы, ключ значением вне git (`model_keys.local.json`, наружу —
только «ключ задан · …XXXX»), рассуждение точки (auto/low/high/none), потолок ответа точки, поля, которых не принимает
модель (Claude — без temperature и top_p), внешняя точка — через системный прокси, вычистка ключа из ошибок, отказ
401/403 с ответом поставщика, пробный запрос, тарифы и предел расхода по поставщику. Своё у MeetFlow — чтение и запись
файла: общий модуль не принимает файл без роли генерации, а здесь это законное состояние «не настроена»; и роль
`guard` — досмотр реплик, обращённых к системе (необязательная).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .base import AnswerTruncated, ConnectorError, ConnectorUnavailable, LLMConnector
from .shared import llm_cost
from .shared import model_routes as mr
from ..core.types import LLMResult

KINDS = mr.KINDS
ASR_KINDS = mr.ASR_KINDS
ROLES = mr.ROLES + ("guard",)
ROLE_TITLES = {**mr.ROLE_TITLES, "guard": "Досмотр реплик к системе"}
KIND_FIELDS = mr.KIND_FIELDS
HISTORY_KEEP = mr.HISTORY_KEEP
SIDE_TO_ROLE = {"generator": "generate", "verifier": "verify"}
NOT_CONFIGURED = "не настроена"
CHARS_PER_TOKEN = 3

# Заготовки подключений (ответ владельца 15.10.26: «сразу перенести все настройки подключения моделей, какие уже есть
# в ERP и Планёрке, — заготовками без адресов и ключей»). Без адреса или модели — «не настроена», в роль не попадает.
PRESETS: dict[str, dict] = {
    "deepseek": {"kind": "openai", "url": "", "model": "deepseek-flash", "reasoning": "none", "max_tokens": 96000,
                 "key_source": "value",
                 "note": "внешний DeepSeek — адрес https://api.deepseek.com; тариф из справочника: 0,15 / 0,003 / 0,60 "
                         "за 1 млн (вход / из кэша / выход), часы пик ×2"},
    "claude": {"kind": "openai", "url": "", "model": "claude-sonnet-5-5", "max_tokens": 32000, "key_source": "value",
               "note": "Claude по ключу — адрес https://api.anthropic.com/v1; модель claude-sonnet-5-5, claude-opus-5-5 "
                       "или claude-haiku-5-5; рассуждение задаёт сама модель; temperature и top_p не передаются"},
    "openrouter": {"kind": "openrouter", "model": "", "key_source": "value",
                   "note": "через OpenRouter — любая модель каталога; рассуждение — своим форматом OpenRouter"},
    "qwen-local": {"kind": "ollama", "url": "", "model": "qwen3.8:latest", "max_tokens": 8000,
                   "note": "локальная qwen на сервере моделей; поля рассуждения у Ollama нет"},
    "whisper": {"kind": "faster-whisper", "model": "", "device": "auto",
                "note": "Whisper на этой машине: модель — имя (large-v3) или путь к папке; голос не покидает машину"},
    "asr-code": {"kind": "python", "callable": "", "note": "свой код распознавания на этой машине: модуль:функция"},
    "asr-service": {"kind": "asr-service", "url": "", "note": "сервис распознавания во внутренней сети: только внутренний адрес"},
}


def routes_path() -> Path:
    return Path(os.environ.get("MODEL_ROUTES_PATH", "").strip() or "data/models.json")


def _use(path: Path | None) -> Path:
    """Общий модуль узнаёт, где файл и хранилище ключей (`configure`), — до любого обращения к ключам."""
    path = Path(path or routes_path())
    mr.configure(path, "", asr_check=_asr_check)
    return path


def _asr_check(model: str):
    """Проверка модели Whisper для общего ping: та же, что у MeetFlow (модель на диске, движок установлен)."""
    from .asr_whisper import asr_ping
    return asr_ping({"kind": "faster-whisper", "model": model})


def _err(fn, *a, **kw):
    """Ошибка общего модуля — понятной ошибкой коннектора, а не трассировкой."""
    try:
        return fn(*a, **kw)
    except mr.RoutesError as e:
        raise ConnectorError(str(e)) from None


internal_url = mr._internal_url
missing = mr.missing
is_external = mr.is_external


def check_point(name: str, ep: dict) -> None:
    _err(mr._check_point, name, ep)


def validate(data: dict) -> dict:
    """Файл маршрутов MeetFlow. Пустая или отсутствующая роль — «не настроена», это не ошибка (13.10.26). Точки
    проверяет общий модуль; распознавание — только внутри контура, и при загрузке файла, и при любой записи."""
    eps, roles = data.get("endpoints"), data.get("roles", {})
    if not isinstance(eps, dict):
        raise ConnectorError("в models.json нет раздела endpoints")
    if not isinstance(roles, dict):
        raise ConnectorError("раздел roles — набор ролей с цепочками точек")
    for name, ep in eps.items():
        check_point(name, ep)
    if "probe" in data:
        _err(mr._probe_check, data["probe"])
    for role, chain in roles.items():
        if role not in ROLES:
            raise ConnectorError(f"неизвестная роль «{role}» — допустимы {', '.join(ROLES)}")
        if not isinstance(chain, list):
            raise ConnectorError(f"роль «{role}»: цепочка — список точек")
        unknown = [n for n in chain if n not in eps]
        if unknown:
            raise ConnectorError(f"роль «{role}»: неизвестные точки {', '.join(unknown)}")
        if role == "asr":
            outside = [n for n in chain if is_external(eps[n])]
            if outside:
                raise ConnectorError(f"распознавание — только внутри контура: точка «{outside[0]}» внешняя; голос не "
                                     "покидает периметр")
        wrong = [n for n in chain if (eps[n]["kind"] in ASR_KINDS) != (role == "asr")]
        if wrong:
            raise ConnectorError(f"роль «{role}»: точки {', '.join(wrong)} другого типа подключения — " + (
                "распознавание идёт только через faster-whisper, свой код или сервис внутренней сети"
                if role == "asr" else "точка распознавания не может писать текст"))
        for n in chain:
            gap = missing(eps[n])
            if gap:
                raise ConnectorError(f"роль «{role}»: точка «{n}» {NOT_CONFIGURED} — {gap}")
    return data


def presets_file() -> dict:
    return {"endpoints": {k: dict(v) for k, v in PRESETS.items()}, "roles": {}, "cooldown_sec": mr.DEFAULT_COOLDOWN_SEC}


def ensure_file(path: Path | None = None) -> Path:
    """Файла нет — кладётся справочник заготовок без ролей: ни одна роль не назначена, вызовов нет."""
    path = _use(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, presets_file(), {"action": "presets", "by": "система"}, backup=False)
    return path


def read(path: Path | None = None) -> dict | None:
    path = _use(path)
    if not path.exists():
        return None
    return validate(json.loads(path.read_text(encoding="utf-8")))


def _ordered(names: list[str]) -> list[str]:
    now = time.time()
    live = [n for n in names if mr._state.down_until.get(n, 0) <= now]
    return live + [n for n in names if n not in live]


VERIFY_BORROWS = "отдельная модель проверки не назначена"


def _names(roles: dict, role: str) -> list[str]:
    """Точки роли. Проверка без своих точек идёт на модель черновика, назначенную администратором (решения владельца
    09.10 и 13.10.26, ответ 15.10.26 — «как в ERP и Планёрке»), и это показывается явно. Остальные роли без точек —
    «не настроена», чужая роль не подставляется."""
    own = list(roles.get(role) or [])
    if not own and role == "verify":
        return list(roles.get("generate") or [])
    return own


def role_chain(role: str, path: Path | None = None) -> list[str]:
    """Цепочка роли по порядку, выведенные — в конце."""
    data = read(path)
    return _ordered(_names((data or {}).get("roles", {}), role))


def configured(role: str, path: Path | None = None) -> bool:
    try:
        return bool(role_chain(role, path))
    except ConnectorError:
        return False


def asr_chain(path: Path | None = None):
    """Цепочка распознавания: ([(имя, точка)], охлаждение) или None — роль не назначена («не настроена»)."""
    data = read(path)
    names = (data or {}).get("roles", {}).get("asr")
    if not names:
        return None
    return [(n, data["endpoints"][n]) for n in _ordered(names)], int(data.get("cooldown_sec", mr.DEFAULT_COOLDOWN_SEC))


def mark_down(name: str, cooldown: int, error: str = "") -> None:
    with mr._lock:
        mr._state.down_until[name] = time.time() + cooldown
        if error:
            mr._state.last_error[name] = mr.scrub(error)[:300]


def mark_up(name: str) -> None:
    with mr._lock:
        mr._state.down_until.pop(name, None)
        mr._state.last_error.pop(name, None)


def tariff_of(ep: dict, model: str | None = None) -> dict | None:
    try:
        return llm_cost.тариф_точки(ep, model or ep.get("model"), ep.get("url", ""))[0]
    except llm_cost.ТарифНеВерен:
        return None


def probe_settings(path: Path | None = None) -> dict:
    """Настройки пробы: умолчания и переменные общего модуля (порог первого признака не меньше 600 с, свежесть 10 мин),
    поверх — раздел "probe" файла MeetFlow (общий модуль его не читает: файл MeetFlow он не принимает целиком)."""
    s = mr.probe_settings()
    try:
        own = (read(path) or {}).get("probe") or {}
    except ConnectorError:
        own = {}
    for k, v in own.items():
        s[k] = bool(mr._как_да_нет(v)) if k == "enabled" else v
    return s


class PointLLM(LLMConnector):
    """Одна точка маршрута: OpenAI-совместимый сервер, OpenRouter или Ollama. Тело запроса — по правилам общего
    модуля, тем же путём, что у ERP (orchestrator_qwen): рассуждение точки, поля, которых модель не принимает,
    потолок ответа «точка, иначе тема», прокси для внешней точки, ключ — только в заголовок."""
    name = "point"

    def __init__(self, point: str, ep: dict, max_answer_tokens: int = 4096, journal_path: Path | None = None,
                 timeout: float = 900, attempts: int = 2):
        self.point, self.ep = point, dict(ep)
        self.route = mr._route(point, ep)
        self.model = ep.get("model") or ""
        self.profile = ep.get("profile", "generic")
        self.max_answer_tokens = mr.max_tokens_of(self.route) or max_answer_tokens
        self.context_chars = int(ep.get("context_chars") or 32_000)
        self.journal_path = journal_path
        self.timeout, self.attempts = timeout, attempts
        self.label = self.route.label

    @property
    def provider(self) -> str | None:
        return mr.provider_of(self.route)

    def probe(self, chars: int = 0, settings: dict | None = None) -> dict:
        """Пробный запрос общим модулем: начало запроса такого размера, ответ — до первого признака жизни."""
        return mr.probe(self.route, chars=chars, settings=settings)

    def probe_fresh(self, settings: dict) -> bool:
        return mr.probe_fresh(self.route, self.model, settings)

    def worst_call_usd(self, prompt_chars: int) -> float | None:
        t = tariff_of(self.ep)
        if not t:
            return 0.0 if not self.route.external else None
        mult = float((t.get("peak") or {}).get("multiplier") or 1)
        return (prompt_chars / CHARS_PER_TOKEN * t["input"] + self.max_answer_tokens * t["output"]) * mult / 1_000_000

    def health(self) -> dict:
        return {"name": self.point, "ok": None, "detail": "проверка по кнопке «Проверить связь»",
                "external": self.route.external}

    def body(self, system: str, user: str, json_mode: bool, temperature: float) -> dict:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.route.kind == "ollama":
            b = {"model": self.model, "messages": msgs, "stream": False,
                 "options": {"temperature": temperature, "num_predict": self.max_answer_tokens,
                             "num_ctx": int(self.ep.get("num_ctx") or 32768)}}
            if json_mode:
                b["format"] = "json"
            return b
        b = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": self.max_answer_tokens}
        if json_mode:
            b["response_format"] = {"type": "json_object"}
        if self.route.kind == "openrouter":
            # провайдеры, которые хранят или учат на присланном, — мимо (решение MeetFlow 03.10.26)
            b.update({"usage": {"include": True}, "provider": {"data_collection": "deny"}})
        mr.apply_reasoning(b, self.route)
        mr.apply_model_limits(b, self.route)
        return b

    def _limit_check(self) -> None:
        """Предел расхода поставщика в месяц (15.10.26): исчерпан — платные вызовы через него стоят, другие работают."""
        prov = self.provider
        if not prov or not self.journal_path:
            return
        st = llm_cost.состояние_предела(prov, llm_cost.расход_по_поставщикам(
            llm_cost.строки_журнала(self.journal_path), время_utc=False).get(prov, 0.0), provider_limit(prov))
        if st["state"] == "stop":
            raise ConnectorUnavailable(llm_cost.текст_остановки(st))

    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult:
        key = self.route.api_key
        if self.route.kind == "openrouter" and not key:
            raise ConnectorUnavailable(f"{self.label}: ключ не задан — задайте его в «Моделях»")
        if self.route.kind == "ollama" and self.route.external and not self.ep.get("allow_remote"):
            raise ConnectorError(f"{self.label}: Ollama — только в контуре; внешний адрес разрешается явно (allow_remote)")
        self._limit_check()
        body = self.body(system, user, json_mode, temperature)
        headers = {"Content-Type": "application/json", "X-Title": "MeetFlow"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        last, t0 = "", time.monotonic()
        for i in range(self.attempts):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise ConnectorError(f"Время прогона вышло до ответа модели ({last or 'запрос не отправлен'}).")
            req = mr.mark_request(urllib.request.Request(self.route.endpoint, data=json.dumps(body).encode("utf-8"),
                                                         headers=headers, method="POST"), self.route)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout if left is None else min(self.timeout, left)) as r:
                    data = json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = mr.scrub(e.read().decode("utf-8", "replace"), extra=(key,))
                if e.code == 429 or e.code >= 500:
                    last = f"HTTP {e.code}"
                    time.sleep(min(15 * (i + 1), max(0.0, (left or 30) - 1)) if i + 1 < self.attempts else 0)
                    continue
                if e.code == 401:
                    raise ConnectorUnavailable(f"{self.label}: {mr.key_rejected_reason(detail, extra=(key,))}") from None
                if e.code == 403:
                    raise ConnectorUnavailable(f"{self.label}: {mr.forbidden_reason(detail, extra=(key,))}") from None
                if e.code in (402, 404):           # денег нет, модели нет — недоступна ТОЧКА, на другой пройдёт
                    raise ConnectorUnavailable(f"{self.label} отказал: HTTP {e.code} — {detail[:300]}") from None
                raise ConnectorError(f"{self.label} отказал: HTTP {e.code} — {detail[:300]}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as e:
                last = mr.scrub(f"{type(e).__name__}: {e}", extra=(key,))[:200]
                continue
            if self.route.kind == "ollama":
                text = ((data.get("message") or {}).get("content") or "")
                finish = "length" if data.get("done_reason") == "length" else data.get("done_reason")
                usage = {"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count")}
            else:
                choice = (data.get("choices") or [{}])[0]
                text = (choice.get("message") or {}).get("content") or ""
                finish, usage = choice.get("finish_reason"), data.get("usage") or {}
            if finish == "length":
                raise AnswerTruncated(f"Ответ модели оборван потолком {self.max_answer_tokens} токенов — повтор дал бы "
                                      "тот же обрыв.")
            if not text.strip():
                last = "пустой ответ"
                continue
            cost = llm_cost.стоимость_вызова(usage, tariff_of(self.ep, data.get("model") or self.model),
                                             datetime.now(timezone.utc))
            return LLMResult(text, data.get("model") or self.model, int(usage.get("prompt_tokens") or 0),
                             int(usage.get("completion_tokens") or 0), float(cost.get("cost_usd") or 0.0),
                             time.monotonic() - t0,
                             {"usage": usage, "finish_reason": finish, "route": self.point, "provider": self.provider,
                              "cost_source": cost.get("cost_source"), "cached_tokens": cost.get("cached_tokens")})
        raise ConnectorUnavailable(f"{self.label} не ответил после {self.attempts} попыток ({last}).")


def provider_limit(provider: str | None, path: Path | None = None) -> float | None:
    """Предел поставщика в месяц — меньший из заданных у его точек (необязательный)."""
    if not provider:
        return None
    try:
        data = read(path) or {}
    except ConnectorError:
        return None
    limits = [ep["month_limit_usd"] for ep in (data.get("endpoints") or {}).values()
              if ep.get("month_limit_usd") and ep.get("kind") in KINDS and is_external(ep)
              and llm_cost.поставщик(ep.get("kind"), ep.get("url", "")) == provider]
    return float(min(limits)) if limits else None


class NotConfiguredLLM(LLMConnector):
    """Роль без модели (MEETFLOW_LLM=ollama/openrouter, а модель в теме не задана): ни одного вызова, понятный текст."""
    name = "not_configured"
    model = NOT_CONFIGURED
    configured = False

    def __init__(self, side: str):
        self.role = SIDE_TO_ROLE.get(side, side)
        self.not_configured_text = (f"Модель роли «{ROLE_TITLES.get(self.role, self.role)}» {NOT_CONFIGURED} — задайте её "
                                    "в «Моделях» (MEETFLOW_LLM=routes) или в теме.")

    def health(self) -> dict:
        return {"name": self.name, "ok": None, "detail": self.not_configured_text}

    def complete(self, system: str, user: str, **kw) -> LLMResult:
        raise ConnectorError(self.not_configured_text)


def provider_limits(journal_path, path: Path | None = None) -> list[dict]:
    """Строки мониторинга по поставщикам (стенд 46): внешние точки файла и все, у кого был расход в этом месяце —
    «потрачено за месяц X из Y (N %)», 90 % — предупреждение, 100 % — стоп этого поставщика. Общим llm_cost."""
    try:
        data = read(path) or {}
    except ConnectorError:
        data = {}
    spent = llm_cost.расход_по_поставщикам(llm_cost.строки_журнала(journal_path), время_utc=False) if journal_path else {}
    provs = {llm_cost.поставщик(ep.get("kind"), ep.get("url", "")) for ep in (data.get("endpoints") or {}).values()
             if ep.get("kind") in KINDS and is_external(ep) and (ep.get("url") or ep.get("kind") == "openrouter")}
    provs = {p for p in provs | set(spent) if p}
    return [llm_cost.состояние_предела(p, spent.get(p, 0.0), provider_limit(p, path))
            for p in sorted(provs, key=llm_cost.название_поставщика)]


class RoutedLLM(LLMConnector):
    """Цепочка точек одной роли. Атрибуты модели (model, profile, context_chars…) — у первой живой точки."""
    name = "routes"
    _lock = threading.RLock()

    def __init__(self, side: str, max_answer_tokens: int = 4096, path: Path | None = None, factory=None,
                 journal_path: Path | None = None):
        self.role = SIDE_TO_ROLE.get(side, side)
        self.max_answer_tokens = max_answer_tokens
        self.path = _use(path)
        self.journal_path = journal_path
        self._factory = factory or self._make
        self._raw: bytes | None = None
        self._data: dict = {}
        self._connectors: dict[str, LLMConnector] = {}
        self.last_route = ""
        if self.path.exists():
            self._load()                   # неверный файл объясняется сразу, при запуске, а не на первом вызове

    def _load(self) -> dict:
        _use(self.path)
        if not self.path.exists():
            return {"endpoints": {}, "roles": {}}
        raw = self.path.read_bytes()       # по содержимому: две записи в один тик времени не видны (15.10.26)
        with self._lock:
            if raw != self._raw:
                self._data = validate(json.loads(raw.decode("utf-8")))
                self._raw, self._connectors = raw, {}
        return self._data

    def _make(self, name: str, ep: dict) -> LLMConnector:
        return PointLLM(name, ep, self.max_answer_tokens, self.journal_path)

    def connector(self, name: str) -> LLMConnector:
        data = self._load()
        if name not in self._connectors:
            self._connectors[name] = self._factory(name, data["endpoints"][name])
        return self._connectors[name]

    def chain(self) -> list[str]:
        return _ordered(_names(self._load()["roles"], self.role))

    @property
    def borrowed(self) -> bool:
        """Проверка идёт на модель черновика: своей точки у роли нет (показывается явно)."""
        roles = self._load()["roles"]
        return self.role == "verify" and not roles.get("verify") and bool(roles.get("generate"))

    @property
    def display(self) -> str:
        """Для «Моделей», мониторинга и сведений о прогоне: какая точка работает; у проверки без своей — явно."""
        names = self.chain()
        if not names:
            return self.not_configured_text
        if self.borrowed:
            return f"модель черновика: {names[0]} · {VERIFY_BORROWS}"
        return names[0]

    @property
    def configured(self) -> bool:
        try:
            return bool(self.chain())
        except ConnectorError:
            return False

    @property
    def not_configured_text(self) -> str:
        return f"Модель роли «{ROLE_TITLES.get(self.role, self.role)}» {NOT_CONFIGURED} — назначьте её в «Моделях»."

    @property
    def _primary(self) -> LLMConnector | None:
        names = self.chain()
        return self.connector(names[0]) if names else None

    @property
    def model(self) -> str:
        return getattr(self._primary, "model", "") if self.configured else NOT_CONFIGURED

    @property
    def profile(self) -> str:
        return getattr(self._primary, "profile", "generic") if self.configured else "generic"

    @property
    def context_chars(self) -> int:
        names = self.chain()
        return min(int(getattr(self.connector(n), "context_chars", 0) or 10**9) for n in names) if names else 32_000

    def worst_call_usd(self, prompt_chars: int) -> float | None:
        """Худший случай — по самой дорогой точке цепочки: при переходе вызов может уйти на неё."""
        costs = [self.connector(n).worst_call_usd(prompt_chars) for n in self.chain()]
        known = [c for c in costs if c is not None]
        return max(known) if known else None

    def health(self) -> dict:
        names = self.chain()
        now = time.time()
        return {"name": self.name, "ok": bool(names) or None, "role": self.role, "chain": names,
                "detail": "" if names else self.not_configured_text,
                "down": {n: int(t - now) for n, t in mr._state.down_until.items() if t > now}}

    def probe(self, chars: int = 0) -> tuple[bool, list[dict]]:
        """Пробный запрос перед сборкой по цепочке роли (стенд 39): точка, прошедшая пробу в пределах свежести, не
        проверяется; не готова — выводится и проба идёт на следующую. (готова ли роль, замеры попыток)."""
        settings = probe_settings(self.path)
        if not settings["enabled"]:
            return True, []
        tries = []
        cooldown = int(self._load().get("cooldown_sec", mr.DEFAULT_COOLDOWN_SEC))
        for name in self.chain():
            point = self.connector(name)
            if not hasattr(point, "probe"):
                return True, tries              # подключение без пробы (подменное, заглушка) — считается готовым
            if point.probe_fresh(settings):
                return True, tries
            r = point.probe(chars=chars, settings=settings)
            tries.append(r)
            if r.get("ok"):
                return True, tries
            mark_down(name, cooldown, r.get("reason", ""))
        return False, tries

    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult:
        # Цепочка перечитывается перед КАЖДОЙ попыткой (локальная машина 12.10.26): переключение в «Моделях»
        # подхватывается без перезапуска; провалившиеся в этом вызове точки не повторяются.
        if not self.chain():
            raise ConnectorError(self.not_configured_text)        # ни одного вызова, ни одной подстановки
        errors, tried = [], set()
        while True:
            names = [n for n in self.chain() if n not in tried]
            if not names:
                break
            name = names[0]
            tried.add(name)
            cooldown = int(self._load().get("cooldown_sec", mr.DEFAULT_COOLDOWN_SEC))
            try:
                res = self.connector(name).complete(system, user, json_mode=json_mode, temperature=temperature,
                                                    purpose=purpose, deadline=deadline)
            except ConnectorUnavailable as e:
                mark_down(name, cooldown, str(e))
                errors.append(f"{name}: {e}")
                continue
            mark_up(name)
            self.last_route = name
            if isinstance(res.raw, dict):
                res.raw.setdefault("route", name)
            return res
        raise ConnectorUnavailable("Ни одна точка роли «%s» не ответила — %s" % (self.role, "; ".join(errors)))


# --- пульт «Модели» ------------------------------------------------------------------------------------------------

def panel(path: Path | None = None, full_keys: bool = True) -> dict:
    """Для «Моделей» супер-администратора: роли, точки по порядку и состояние, справочник подключений с ключом только
    в виде «ключ задан · …XXXX», тариф и откуда цифры, роды подключений с полями формы. Роль без точек — «не настроена»."""
    path = ensure_file(path)
    data = read(path)
    now = time.time()
    roles = {}
    for role in ROLES:
        rows = []
        for i, n in enumerate(data["roles"].get(role) or []):
            ep = data["endpoints"][n]
            rest = int(mr._state.down_until.get(n, 0) - now)
            rows.append({"name": n, "kind": ep["kind"], "model": ep.get("model") or ep.get("callable") or ep.get("url"),
                         "url": ep.get("url", "") or (f"device: {ep.get('device', 'auto')}" if ep["kind"] == "faster-whisper" else ""),
                         "state": f"выведена ещё {rest} с" if rest > 0 else ("основная" if i == 0 else "запасная"),
                         "last_error": mr._state.last_error.get(n, ""), "external": is_external(ep),
                         "reasoning": ep.get("reasoning", "auto")})
        roles[role] = rows
    options = {role: [{"name": n, "model": ep.get("model") or ep.get("callable") or ep.get("url"), "kind": ep["kind"],
                       "external": is_external(ep)}
                      for n, ep in data["endpoints"].items()
                      if (ep["kind"] in ASR_KINDS) == (role == "asr") and not missing(ep)
                      and not (role == "asr" and is_external(ep))]
               for role in ROLES}
    endpoints = [{"name": n, "kind": ep["kind"], "kind_title": KIND_FIELDS[ep["kind"]]["title"],
                  "fields": {k: v for k, v in ep.items() if k != "kind"},
                  "roles": [r for r in ROLES if n in (data["roles"].get(r) or [])],
                  "missing": missing(ep), "last_error": mr._state.last_error.get(n, ""), "external": is_external(ep),
                  "key": mr.key_masked(n, full_keys) if ep.get("key_source") == "value" else "",
                  **({"tariff": mr._tariff_panel(ep)} if ep["kind"] in KINDS else {})}
                 for n, ep in data["endpoints"].items()]
    hist = path.with_name("models.history")
    return {"switchable": True, "asr_switchable": True, "path": str(path), "cooldown_sec": int(data.get("cooldown_sec", mr.DEFAULT_COOLDOWN_SEC)),
            "roles": roles, "options": options, "endpoints": endpoints, "kinds": KIND_FIELDS, "role_titles": ROLE_TITLES,
            "not_configured": [r for r in ("generate", "verify", "asr") if not _names(data["roles"], r)],
            # проверка без своих точек — на модели черновика: показать явно, а не пусто (15.10.26)
            "verify_fallback": (data["roles"].get("generate") or [""])[0] if not data["roles"].get("verify") else "",
            "history": history(path), "tariff_book": llm_cost.справочник_для_формы(),
            "versions": len(list(hist.glob("models-*.json"))) if hist.exists() else 0, "editable": True, "note": ""}


def check_all(path: Path | None = None) -> list[dict]:
    """Короткий запрос на каждую точку ролей тем же телом, что рабочий вызов (общий `ping`); у распознавания —
    проверка без записи. Роль без точек — строкой «не настроена»."""
    path = _use(path)
    data = read(path) or {"endpoints": {}, "roles": {}}
    out, todo, seen = [], [], set()
    for role in ROLES:
        names = data["roles"].get(role) or []
        if not names and role == "verify" and data["roles"].get("generate"):
            out.append({"name": ROLE_TITLES[role], "model": "", "ok": True,
                        "detail": f"модель черновика: {data['roles']['generate'][0]} · {VERIFY_BORROWS}"})
        elif not names and role != "guard":
            out.append({"name": ROLE_TITLES[role], "model": "", "ok": False, "detail": NOT_CONFIGURED})
        for n in names:
            if n not in seen:
                seen.add(n)
                todo.append(n)

    def one(n: str) -> dict:
        try:
            ok, detail = mr.ping(mr._route(n, data["endpoints"][n]))
        except Exception as e:  # noqa: BLE001 — одна точка не роняет опрос остальных
            ok, detail = False, f"{type(e).__name__}: {e}"
        return {"name": n, "model": data["endpoints"][n].get("model") or "", "ok": ok, "detail": mr.scrub(detail)}
    # все точки разом, а не по очереди (стенд 12): молчащий сервер не держит опрос остальных
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(todo)))) as pool:
        out += list(pool.map(one, todo))
    return out


def _editable(path: Path | None) -> tuple[Path, dict]:
    path = ensure_file(path)
    return path, read(path)


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
    mr._log(path, record)
    return data


def _role_and_point(data: dict, role: str, name: str) -> None:
    if role not in ROLES:
        raise ConnectorError(f"нет роли «{role}»")
    if name not in data["endpoints"]:
        raise ConnectorError(f"нет точки «{name}»")


def use(role: str, name: str, path: Path | None = None, by: str = "") -> dict:
    """Поставить точку первой в роли — работающие подключения подхватят файл без перезапуска."""
    path, data = _editable(path)
    _role_and_point(data, role, name)
    data["roles"][role] = [name] + [n for n in data["roles"].get(role) or [] if n != name]
    _write(path, data, {"action": "use", "role": role, "point": name, "by": by})
    mark_up(name)
    return data["roles"]


def add_to_role(role: str, name: str, path: Path | None = None, by: str = "") -> dict:
    path, data = _editable(path)
    _role_and_point(data, role, name)
    chain = data["roles"].get(role) or []
    if name in chain:
        raise ConnectorError(f"точка «{name}» уже в роли «{ROLE_TITLES.get(role, role)}»")
    data["roles"][role] = chain + [name]
    _write(path, data, {"action": "add", "role": role, "point": name, "by": by})
    return data["roles"]


def remove_from_role(role: str, name: str, path: Path | None = None, by: str = "") -> dict:
    """Убрать точку из роли. Последняя точка уходит тоже — роль становится «не настроена» (вызовов нет)."""
    path, data = _editable(path)
    _role_and_point(data, role, name)
    chain = data["roles"].get(role) or []
    if name not in chain:
        raise ConnectorError(f"точки «{name}» нет в роли «{ROLE_TITLES.get(role, role)}»")
    data["roles"][role] = [n for n in chain if n != name]
    _write(path, data, {"action": "remove", "role": role, "point": name, "by": by})
    return data["roles"]


def clean_point(fields: dict) -> dict:
    return _err(mr.clean_point, fields)


def save_point(name: str, fields: dict, path: Path | None = None, by: str = "", old_name: str = "",
               key_value: str | None = None) -> dict:
    """Завести или изменить подключение. Без адреса или модели — заготовка «не настроена». `key_value` — ключ
    значением из формы: пишется в model_keys.local.json рядом с файлом (вне git), в models.json его нет."""
    name = (name or "").strip()
    if not name or len(name) > 60 or "|" in name:
        raise ConnectorError("имя подключения — до 60 знаков, без «|»")
    path, data = _editable(path)
    ep = clean_point(fields)
    check_point(name, ep)
    if key_value:
        if ep.get("key_source") != "value":
            raise ConnectorError("ключ значением передан, а у подключения выбрано «имя переменной окружения»")
        key_value = _err(mr._key_check, key_value)
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
    if old_name and old_name != name:
        mr.key_rename(old_name, name)
    if ep.get("key_source") == "value":
        if key_value:
            _err(mr.key_set, name, key_value, by)
    elif mr.key_has(name):
        mr.key_delete(name, by=by)
    mark_up(name)
    return ep


def set_point_key(name: str, value: str, path: Path | None = None, by: str = "") -> str:
    """«Заменить ключ» у точки с ключом значением. Наружу — только «задан / заменён»."""
    _, data = _editable(path)
    ep = data["endpoints"].get(name)
    if ep is None:
        raise ConnectorError(f"нет точки «{name}»")
    if ep.get("key_source") != "value":
        raise ConnectorError(f"у подключения «{name}» ключ берётся из переменной окружения — выберите «значение» в форме")
    result = _err(mr.key_set, name, value, by)
    mark_up(name)
    return result


def delete_point_key(name: str, path: Path | None = None, by: str = "") -> bool:
    _, data = _editable(path)
    if name not in data["endpoints"]:
        raise ConnectorError(f"нет точки «{name}»")
    return mr.key_delete(name, by=by)


def delete_point(name: str, path: Path | None = None, by: str = "") -> None:
    """Удалить подключение; из ролей оно уходит само (роль может остаться «не настроена»)."""
    path, data = _editable(path)
    if name not in data["endpoints"]:
        raise ConnectorError(f"нет точки «{name}»")
    data["roles"] = {r: [n for n in ch if n != name] for r, ch in data["roles"].items()}
    del data["endpoints"][name]
    _write(path, data, {"action": "delete", "point": name, "by": by})
    mr.key_delete(name, by=by)


def test_point(fields: dict, key_value: str = "", name: str = "", path: Path | None = None) -> tuple[bool, str]:
    """«Проверить связь» по полям формы до сохранения — тем же телом, что рабочий вызов (общий модуль)."""
    _use(path)
    return _err(mr.test_point, fields, key_value, name)


def history(path: Path | None = None, limit: int = 8) -> list[dict]:
    log = _use(path).with_name("models.log.jsonl")
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
