"""Клиенты модели. Боевой — локальная Ollama (GLM / DeepSeek / Qwen) внутри периметра.

Правила, вшитые в код, а не в инструкцию:
- периметр: адрес модели только локальный или из явного белого списка MR_ALLOWED_HOSTS
  (правило владельца 24.09.26 «голос не покидает периметр», конфиденциальные данные — только локально);
- запрет моделей, обучающихся на присланных данных (маркер contributor, правило 30.09.26);
- повтор только на сетевых отказах (до 3 попыток с растущей паузой); плохой JSON — один повтор
  с напоминанием о формате; потолок прогона — ни одного повтора.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .errors import BadModelAnswer, ProviderUnavailable, SetupError

JSON_REMINDER = "\n\nОтветь ТОЛЬКО одним JSON-объектом, без пояснений и без разметки."


def estimate_tokens(text: str) -> int:
    """Оценка для эвристического клиента и для потолка до вызова: ~3 знака кириллицы на токен."""
    return max(1, len(text) // 3)


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    # strict=False: модель копирует в цитату строку записи с сырой табуляцией («00:00:00<TAB>Имя»), строгий разбор
    # на ней падает (полный прогон ERP, 03.10.26 — две встречи из двадцати).
    try:
        obj = json.loads(text, strict=False)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise BadModelAnswer("в ответе модели нет JSON-объекта")
        try:
            obj = json.loads(m.group(0), strict=False)
        except json.JSONDecodeError as e:
            raise BadModelAnswer(f"ответ модели не разбирается как JSON: {e}")
    if not isinstance(obj, dict):
        raise BadModelAnswer("ответ модели — не объект")
    return obj


def assert_local(base_url: str):
    host = (urlparse(base_url).hostname or "").lower()
    allowed = {"localhost", "127.0.0.1", "::1"} | {
        h.strip().lower() for h in os.environ.get("MR_ALLOWED_HOSTS", "").split(",") if h.strip()
    }
    if host not in allowed:
        raise SetupError(
            f"Адрес модели {host} вне периметра. Разрешены только локальные адреса и MR_ALLOWED_HOSTS — "
            "данные совещания не уходят наружу."
        )


def assert_no_training_model(model: str):
    if re.search(r"[-:]contributor\b", model or "", re.IGNORECASE):
        raise SetupError(f"Модель {model} обучается на присланных данных — такие модели запрещены.")


class LLMClient:
    name = "abstract"

    def complete_json(self, system: str, user: str, purpose: str) -> tuple:
        """Возвращает (dict, usage{tokens_in, tokens_out, cost_usd, seconds})."""
        raise NotImplementedError


class OllamaClient(LLMClient):
    def __init__(self, base_url=None, model=None, timeout=None, attempts=3, num_ctx=None,
                 price_in_per_m=None, price_out_per_m=None):
        self.base_url = (base_url or os.environ.get("MR_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("MR_MODEL", "")
        if not self.model:
            raise SetupError("Не задана модель: переменная MR_MODEL (например glm-4.7-flash).")
        assert_local(self.base_url)
        assert_no_training_model(self.model)
        self.timeout = float(timeout or os.environ.get("MR_TIMEOUT", 300))
        self.attempts = attempts
        self.num_ctx = int(num_ctx or os.environ.get("MR_NUM_CTX", 32768))
        # локальная модель денег за вызов не стоит; цены можно задать, чтобы считать «как если бы через API»
        self.price_in = float(price_in_per_m if price_in_per_m is not None else os.environ.get("MR_PRICE_IN", 0))
        self.price_out = float(price_out_per_m if price_out_per_m is not None else os.environ.get("MR_PRICE_OUT", 0))
        self.name = f"ollama:{self.model}"
        self.base_timeout = self.timeout
        # без системного прокси: иначе запрос к 127.0.0.1 уходит на прокси и текст встречи покидает периметр (ревью 03.10.26)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _post(self, payload: dict) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last = None
        for attempt in range(1, self.attempts + 1):
            req = urllib.request.Request(self.base_url + "/api/chat", data=data, headers={"Content-Type": "application/json"})
            try:
                with self._opener.open(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:300]
                if e.code == 404 and "not found" in body:
                    raise SetupError(f"Модель {self.model} не загружена в Ollama: ollama pull {self.model}")
                if e.code < 500 and e.code != 429:
                    # 4xx — ошибка запроса или настройки (контекст, формат), повтор и переход на правила её не лечат
                    raise SetupError(f"Ollama отклонила запрос: HTTP {e.code} {body}")
                last = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = str(e)
            if attempt < self.attempts:
                time.sleep(min(2 ** attempt, 10))
        raise ProviderUnavailable(f"Ollama недоступна после {self.attempts} попыток: {last}")

    def complete_json(self, system: str, user: str, purpose: str) -> tuple:
        t0 = time.monotonic()
        tin = tout = 0
        for retry in range(2):  # плохой JSON — один повтор, не четыре
            payload = {
                "model": self.model, "stream": False, "format": "json",
                "options": {"temperature": 0, "num_ctx": self.num_ctx},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user + (JSON_REMINDER if retry else "")}],
            }
            resp = self._post(payload)
            tin += int(resp.get("prompt_eval_count") or estimate_tokens(system + user))
            tout += int(resp.get("eval_count") or 0)
            if resp.get("done_reason") == "length":
                raise BadModelAnswer("ответ модели обрезан по длине (num_ctx мал для этого входа)")
            try:
                obj = parse_json(resp.get("message", {}).get("content", ""))
                break
            except BadModelAnswer:
                if retry:
                    raise
        cost = tin / 1e6 * self.price_in + tout / 1e6 * self.price_out
        return obj, {"tokens_in": tin, "tokens_out": tout, "cost_usd": cost, "seconds": time.monotonic() - t0}


class ScriptedClient(LLMClient):
    """Клиент для тестов: ответы по назначению вызова. Ответ — dict, строка (сырой текст) или исключение."""

    def __init__(self, script: dict, price_per_call=0.0):
        self.script = {k: list(v) if isinstance(v, list) else [v] for k, v in script.items()}
        self.calls = []
        self.price = price_per_call
        self.name = "scripted"

    def complete_json(self, system, user, purpose):
        self.calls.append((purpose, user))
        queue = self.script.get(purpose) or [{}]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(item):
            item = item(user)
        if isinstance(item, Exception):
            raise item
        obj = parse_json(item) if isinstance(item, str) else item
        return obj, {"tokens_in": estimate_tokens(system + user), "tokens_out": 50, "cost_usd": self.price, "seconds": 0.0}
