"""Vision: снимок доски / скан -> текстовое описание (DeepSeek Vision в Ollama).

В исходных проектах картинки не читались вовсе (в План шло «приложен файл:
имя»), владелец конвертировал их в текст вручную. Коннектор закрывает этот
пробел в целевом локальном контуре. Описание картинки — материал (OTHER),
а не источник фактов: задачи из него не заводятся без цитаты в источнике.
"""
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import httpx

from ..core.types import SourceDoc, SourceKind
from .base import ConnectorError, VisionConnector
from .llm_ollama import LOCAL_HOSTS

PROMPT = ("Опиши, что написано и нарисовано на изображении, дословно перепиши текст. "
          "Не делай выводов о задачах и статусах. Ответ — обычный текст.")


class OllamaVision(VisionConnector):
    name = "ollama_vision"

    def __init__(self, model: str = "", url: str | None = None,
                 timeout: float = 300.0, transport: httpx.BaseTransport | None = None, max_bytes: int = 15 * 2 ** 20):
        self.model = model
        self.url = (url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        if (urlparse(self.url).hostname or "") not in LOCAL_HOSTS:
            raise ConnectorError("Vision только в локальном контуре")
        self.timeout = timeout
        self._transport = transport
        self.max_bytes = max_bytes

    def _client(self) -> httpx.Client:
        # без системного прокси: снимок доски не уходит за периметр (письмо 01/1)
        return httpx.Client(timeout=self.timeout, transport=self._transport, trust_env=False)

    def describe(self, data: bytes, filename: str) -> SourceDoc:
        if not data:
            raise ConnectorError(f"Изображение «{filename}» пустое.")
        if len(data) > self.max_bytes:
            raise ConnectorError(f"Изображение «{filename}» слишком большое.")
        body = {"model": self.model, "stream": False, "messages": [
            {"role": "user", "content": PROMPT, "images": [base64.b64encode(data).decode()]}]}
        try:
            with self._client() as c:
                r = c.post(f"{self.url}/api/chat", json=body)
                r.raise_for_status()
                text = (r.json().get("message") or {}).get("content", "")
        except httpx.HTTPError as e:
            raise ConnectorError(f"Vision недоступен: {type(e).__name__}") from None
        return SourceDoc(f"{filename} (описание изображения)", SourceKind.OTHER, text,
                         {"connector": self.name, "from_image": True})
