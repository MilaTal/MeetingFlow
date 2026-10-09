"""LLM через Ollama — целевой локальный контур (GLM / DeepSeek / Qwen).

Framework к Ollama в разработке не подключается (манифест): коннектор
спроектирован и проверен на заглушке HTTP. Профили моделей — в prompts.py.
Перенесённые уроки транспорта:
- num_ctx задаётся явно: по умолчанию Ollama даёт 8192, а системный промпт
  из двух SKILL.md занимал ~45-55 тыс. токенов (ERP 11.09) — ответа не было.
- format=json для JSON-режима; один повтор с напоминанием, если не JSON.
- Таймаут на попытку, ограниченное число попыток, 429/5xx — пауза.
- Только локальный адрес: удалённый OLLAMA_URL требует allow_remote=True,
  иначе конфиденциальные данные могли бы уйти за периметр.
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx

from ..core.types import LLMResult
from .base import AnswerTruncated, ConnectorError, ConnectorUnavailable, LLMConnector

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OllamaLLM(LLMConnector):
    name = "ollama"

    def __init__(self, model: str = "PLACEHOLDER: glm-4.7-flash", profile: str = "glm",
                 url: str | None = None, num_ctx: int = 32768, timeout: float = 900.0,
                 attempts: int = 3, allow_remote: bool = False, transport: httpx.BaseTransport | None = None,
                 backoff: float = 15.0, max_answer_tokens: int = 4096):
        self.backoff = backoff
        self.max_answer_tokens = max_answer_tokens
        self.model = model
        self.profile = profile
        self.url = (url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.num_ctx = num_ctx
        self.context_chars = num_ctx * 3  # ~3 знака кириллицы на токен — консервативно
        self.timeout = timeout
        self.attempts = attempts
        self._transport = transport
        host = urlparse(self.url).hostname or ""
        if host not in LOCAL_HOSTS and not allow_remote:
            raise ConnectorError(f"OLLAMA_URL {self.url} вне локального контура; нужен allow_remote=True")

    def _client(self) -> httpx.Client:
        # trust_env=False: системный HTTP_PROXY не должен получить текст встречи,
        # даже когда адрес прошёл проверку «локальный» (письмо meeting-registry 01/1)
        return httpx.Client(timeout=self.timeout, transport=self._transport, trust_env=False)

    def health(self) -> dict:
        try:
            with self._client() as c:
                r = c.get(f"{self.url}/api/tags")
                models = [m.get("name") for m in r.json().get("models", [])]
            return {"name": self.name, "ok": self.model in models, "models": models,
                    "detail": "" if self.model in models else f"модель {self.model} не загружена в Ollama"}
        except Exception as e:  # соединение — честный признак, а не флаг
            return {"name": self.name, "ok": False, "detail": f"Ollama недоступна: {type(e).__name__}"}

    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult:
        """deadline — момент (time.monotonic) конца прогона: таймаут попытки и
        паузы между повторами не выходят за остаток (письмо 01/17). 4xx, кроме
        429, не повторяется, текст ответа уходит в сообщение (01/21)."""
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": temperature, "num_ctx": self.num_ctx,
                            "num_predict": self.max_answer_tokens}}
        if json_mode:
            body["format"] = "json"
        last = None
        t0 = time.monotonic()
        for i in range(self.attempts):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise ConnectorError(f"Время прогона вышло до ответа модели ({last or 'запрос не отправлен'}).")
            try:
                with self._client() as c:
                    timeout = self.timeout if left is None else min(self.timeout, left)
                    r = c.post(f"{self.url}/api/chat", json=body, timeout=timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                    pause = self.backoff * (i + 1)
                    if deadline is not None and time.monotonic() + pause >= deadline:
                        break                     # пауза съела бы остаток прогона — не ждём
                    time.sleep(pause)
                    continue
                if r.status_code == 404:          # модели нет на сервере — недоступна точка, а не запрос
                    raise ConnectorUnavailable(f"Модель {self.model} не найдена на {self.url}: HTTP 404")
                if 400 <= r.status_code < 500:    # ошибка запроса: повтор даст то же самое
                    raise ConnectorError(f"Модель отказала: HTTP {r.status_code} — {r.text[:300]}")
                r.raise_for_status()
                data = r.json()
                text = (data.get("message") or {}).get("content") or ""
                if data.get("done_reason") == "length":
                    raise AnswerTruncated(f"Ответ модели оборван потолком {self.max_answer_tokens} токенов "
                                         f"(решение владельца 03.10.26) — повтор дал бы тот же обрыв.")
                if not text.strip():
                    last = "пустой ответ"
                    continue
                return LLMResult(text, self.model, int(data.get("prompt_eval_count") or 0),
                                 int(data.get("eval_count") or 0), 0.0, time.monotonic() - t0, data)
            except httpx.HTTPError as e:
                last = type(e).__name__
        raise ConnectorUnavailable(f"Модель не ответила после {self.attempts} попыток ({last}).")
