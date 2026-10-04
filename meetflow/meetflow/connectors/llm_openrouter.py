"""Модель через OpenRouter — второй инструмент подключения (решение владельца
03.10.26: «пока запускаем через OpenRouter; два инструмента — роутер и
локальный; при развёртывании — выбор»). Локальный — llm_ollama.

Взято из Планёрки (services/llm_client.py) как проверенное:
- ключ только из переменной OPENROUTER_API_KEY, в сообщения и журнал не
  попадает;
- `usage: {include: true}` — стоимость вызова приходит в ответе;
- рассуждение выключается, иначе оно съедает потолок ответа; у моделей с
  обязательным рассуждением (Muse отвечает 400 без него) — включено с
  `exclude`;
- модели «contributor» (обучаются на присланном) — отказ до сети;
- 429 и 5xx повторяются с паузой, 4xx — нет.
Отличия MeetFlow:
- потолок ответа 4096 токенов (решение владельца 03.10.26) вместо 32000;
  обрыв по потолку (`finish_reason: length`) не повторяется — повтор даст
  тот же обрыв, сообщение называет потолок;
- `provider.data_collection: deny` — провайдеры, которые хранят или учат на
  запросах, не выбираются;
- худший случай вызова по ценам модели из открытого каталога OpenRouter:
  потолок прогона не пускает вызов, который в остаток не помещается
  (письмо meeting-registry 01/9).
"""
from __future__ import annotations

import os
import time

import httpx

from .base import AnswerTruncated, ConnectorError, LLMConnector
from ..core.types import LLMResult

API = "https://openrouter.ai/api/v1"
REASONING_REQUIRED = ("muse",)
CHARS_PER_TOKEN = 3            # кириллица — около 3 знаков на токен, оценка сверху по числу токенов


class OpenRouterLLM(LLMConnector):
    name = "openrouter"

    def __init__(self, model: str = "", profile: str = "generic", max_answer_tokens: int = 4096,
                 timeout: float = 900.0, attempts: int = 3, backoff: float = 15.0,
                 transport: httpx.BaseTransport | None = None, reasoning_effort: str = "low"):
        name = (model or "").strip().lower()
        if "-contributor" in name or ":contributor" in name:
            raise ConnectorError(f"Модель «{model}» обучается на присланных данных (вариант «contributor»): "
                                 "в запросах — встречи с именами людей, такие модели запрещены.")
        self.model, self.profile = model, profile
        self.max_answer_tokens = max_answer_tokens
        self.context_chars = 128_000 * CHARS_PER_TOKEN
        self.timeout, self.attempts, self.backoff = timeout, attempts, backoff
        self.reasoning_effort = reasoning_effort
        self._transport = transport
        self._prices: tuple[float, float] | None = None

    @staticmethod
    def _key() -> str:
        return os.environ.get("OPENROUTER_API_KEY", "").strip()

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=self._transport)

    def _reasoning(self) -> dict:
        if any(m in self.model.lower() for m in REASONING_REQUIRED):
            return {"effort": self.reasoning_effort, "exclude": True}
        return {"enabled": False}

    def health(self) -> dict:
        if not self._key():
            return {"name": self.name, "ok": False, "detail": "не задан OPENROUTER_API_KEY"}
        try:
            with self._client() as c:
                r = c.get(f"{API}/key", headers={"Authorization": f"Bearer {self._key()}"})
            return {"name": self.name, "ok": r.status_code == 200, "model": self.model,
                    "detail": "" if r.status_code == 200 else f"ключ не принят: HTTP {r.status_code}"}
        except httpx.HTTPError as e:
            return {"name": self.name, "ok": False, "detail": f"OpenRouter недоступен: {type(e).__name__}"}

    def prices(self) -> tuple[float, float] | None:
        """(цена токена запроса, цена токена ответа) из открытого каталога; None — неизвестно."""
        if self._prices is None:
            try:
                with self._client() as c:
                    data = c.get(f"{API}/models").json().get("data", [])
                for m in data:
                    if m.get("id") == self.model:
                        p = m.get("pricing") or {}
                        self._prices = (float(p.get("prompt") or 0), float(p.get("completion") or 0))
                        break
            except (httpx.HTTPError, ValueError):
                return None
        return self._prices

    def worst_call_usd(self, prompt_chars: int) -> float | None:
        """Худший случай вызова: запрос по своему размеру плюс полный потолок ответа."""
        pr = self.prices()
        if pr is None:
            return None
        return prompt_chars / CHARS_PER_TOKEN * pr[0] + self.max_answer_tokens * pr[1]

    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult:
        key = self._key()
        if not key:
            raise ConnectorError("Подключение OpenRouter выбрано, но переменная OPENROUTER_API_KEY не задана.")
        body = {"model": self.model, "temperature": temperature, "max_tokens": self.max_answer_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "usage": {"include": True}, "provider": {"data_collection": "deny"},
                "reasoning": self._reasoning()}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        last, t0 = None, time.monotonic()
        for i in range(self.attempts):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise ConnectorError(f"Время прогона вышло до ответа модели ({last or 'запрос не отправлен'}).")
            try:
                with self._client() as c:
                    r = c.post(f"{API}/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {key}", "X-Title": "MeetFlow"},
                               timeout=self.timeout if left is None else min(self.timeout, left))
            except httpx.HTTPError as e:
                last = type(e).__name__
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                pause = self.backoff * (i + 1)
                if deadline is not None and time.monotonic() + pause >= deadline:
                    break
                time.sleep(pause)
                continue
            if r.status_code >= 400:          # ошибка запроса: повтор даст то же; ключ в текст не попадает
                raise ConnectorError(f"OpenRouter отказал: HTTP {r.status_code} — {r.text[:300].replace(key, '***')}")
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            if choice.get("finish_reason") == "length":
                raise AnswerTruncated(f"Ответ модели оборван потолком {self.max_answer_tokens} токенов "
                                     f"(решение владельца 03.10.26) — повтор дал бы тот же обрыв.")
            if not text.strip():
                last = "пустой ответ"
                continue
            u = data.get("usage") or {}
            return LLMResult(text, data.get("model") or self.model, int(u.get("prompt_tokens") or 0),
                             int(u.get("completion_tokens") or 0), float(u.get("cost") or 0.0),
                             time.monotonic() - t0, {"usage": u, "finish_reason": choice.get("finish_reason")})
        raise ConnectorError(f"OpenRouter не ответил после {self.attempts} попыток ({last}).")
