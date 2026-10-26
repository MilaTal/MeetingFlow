"""Абстрактные интерфейсы коннекторов. Ядро знает только эти классы.

Пять типов:
  SourceConnector  — файл/байты -> SourceDoc (txt, md, docx, ...)
  ASRConnector     — аудио/видео -> SourceDoc(transcript), только локально
  VisionConnector  — изображение -> SourceDoc(other), описание для модели
  LLMConnector     — сообщения -> LLMResult (Ollama, свой OpenAI-совместимый сервер, OpenRouter; маршруты — llm_routes)
  OutputConnector  — markdown -> файл (docx, md)

Новый коннектор = подкласс + регистрация в PluginRegistry; ядро не меняется.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.types import LLMResult, SourceDoc


class ConnectorError(RuntimeError):
    """Понятная человеку ошибка коннектора (без трассировки на экране)."""


class ConnectorUnavailable(ConnectorError):
    """Точка модели недоступна (нет связи, 5xx/429 после повторов, нет ключа или денег, модели нет на сервере).
    В отличие от ошибки запроса, на другой точке цепочки маршрутов вызов может пройти (llm_routes, 09.10.26)."""


class AnswerTruncated(ConnectorError):
    """Ответ модели оборван потолком длины ответа: повтор того же запроса даст тот же обрыв —
    конвейер делит кусок или сохраняет без этой части (прогон ERP 03.10.26, встреча 08.09)."""


class BadAnswer(ConnectorError):
    """Негодный ответ модели — пустой или зациклившийся — после `model_routes.BAD_ANSWERS_PER_CALL` обращений на вызов,
    либо пустой ответ при остановке по потолку (рассуждение заняло весь потолок). Повтор тем же запросом платит снова и
    даёт то же; на запасную точку такой ответ не уходит (как ERP и Планёрка, 26.10.2026). Причина — в тексте."""


class Connector(ABC):
    name: str = "base"
    kind: str = "base"

    def health(self) -> dict[str, Any]:
        """Проверка соединением, а не флагом (панель «Мониторинг»)."""
        return {"name": self.name, "ok": True}


class SourceConnector(Connector):
    kind = "source"
    extensions: tuple[str, ...] = ()
    max_bytes: int = 20 * 1024 * 1024

    def accepts(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in self.extensions

    @abstractmethod
    def read(self, data: bytes, filename: str) -> SourceDoc: ...


class ASRConnector(Connector):
    kind = "asr"
    extensions: tuple[str, ...] = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".ogg", ".flac")

    def accepts(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in self.extensions

    @abstractmethod
    def transcribe(self, path: Path) -> SourceDoc: ...


class VisionConnector(Connector):
    kind = "vision"
    extensions: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")

    def accepts(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in self.extensions

    @abstractmethod
    def describe(self, data: bytes, filename: str) -> SourceDoc: ...


class LLMConnector(Connector):
    kind = "llm"
    model: str = ""
    profile: str = "generic"
    context_chars: int = 32_000
    max_answer_tokens: int = 4096      # потолок ответа на вызов — решение владельца 03.10.26

    def worst_call_usd(self, prompt_chars: int) -> float | None:
        """Худший случай цены вызова (запрос + полный потолок ответа); None — цена неизвестна."""
        return None

    @abstractmethod
    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult: ...


class OutputConnector(Connector):
    kind = "output"
    extension: str = ".md"

    @abstractmethod
    def render(self, markdown: str, title: str) -> bytes: ...
