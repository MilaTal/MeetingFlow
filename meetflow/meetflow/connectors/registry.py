"""Реестр плагинов: коннекторы регистрируются по типу и имени.

Масштабируемость без изменения ядра: сторонний модуль вызывает
registry.register(MyConnector()) или указывает "module:Class" в теме
(connectors.extra) — ядро находит его через resolve_source / get.
"""
from __future__ import annotations

import importlib
from typing import Iterable

from .base import ASRConnector, Connector, ConnectorError, LLMConnector, OutputConnector, SourceConnector, VisionConnector


class PluginRegistry:
    def __init__(self) -> None:
        self._by_kind: dict[str, dict[str, Connector]] = {}

    def register(self, c: Connector, replace: bool = False) -> Connector:
        bucket = self._by_kind.setdefault(c.kind, {})
        if c.name in bucket and not replace:
            raise ConnectorError(f"коннектор {c.kind}/{c.name} уже зарегистрирован")
        bucket[c.name] = c
        return c

    def get(self, kind: str, name: str) -> Connector:
        try:
            return self._by_kind[kind][name]
        except KeyError:
            raise ConnectorError(f"нет коннектора {kind}/{name}") from None

    def all(self, kind: str) -> list[Connector]:
        return list(self._by_kind.get(kind, {}).values())

    def names(self, kind: str) -> list[str]:
        return sorted(self._by_kind.get(kind, {}))

    def resolve_source(self, filename: str) -> Connector | None:
        """Кто примет файл: текстовый источник, ASR или Vision."""
        for kind in ("source", "asr", "vision"):
            for c in self._by_kind.get(kind, {}).values():
                if isinstance(c, (SourceConnector, ASRConnector, VisionConnector)) and c.accepts(filename):
                    return c
        return None

    def load_extra(self, specs: Iterable[str]) -> list[Connector]:
        """specs: ["package.module:ClassName", ...] из темы."""
        out = []
        for spec in specs:
            mod_name, _, cls_name = spec.partition(":")
            cls = getattr(importlib.import_module(mod_name), cls_name)
            out.append(self.register(cls(), replace=True))
        return out

    def llm(self, name: str) -> LLMConnector:
        c = self.get("llm", name)
        assert isinstance(c, LLMConnector)
        return c

    def output(self, name: str) -> OutputConnector:
        c = self.get("output", name)
        assert isinstance(c, OutputConnector)
        return c


def default_registry() -> PluginRegistry:
    """Базовый набор: текст, docx, Whisper (локально), Vision (Ollama),
    LLM (Ollama, OpenRouter, mock), выгрузка md/docx."""
    from .asr_whisper import WhisperLocalASR
    from .export import DocxOutput, MarkdownOutput
    from .files_docx import DocxSource
    from .files_text import TextSource
    from .llm_mock import MockLLM
    from .llm_ollama import OllamaLLM
    from .llm_openrouter import OpenRouterLLM
    from .vision_ollama import OllamaVision

    r = PluginRegistry()
    for c in (TextSource(), DocxSource(), WhisperLocalASR(), OllamaVision(), MockLLM(), OllamaLLM(), OpenRouterLLM(),
              MarkdownOutput(), DocxOutput()):
        r.register(c)
    return r
