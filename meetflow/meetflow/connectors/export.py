"""Выгрузка документов: markdown и Word.

Протокол хранится как markdown (источник истины), .docx — производное.
Уроки md_to_docx: не оставлять `**` и обратные кавычки (≈60 файлов были
испорчены), markdown-таблицы — настоящие таблицы Word, заголовки — стилями.
Шрифт документа берётся из темы (design.document_font), по умолчанию
Times New Roman 12 pt — корпоративный стиль владельца.
"""
from __future__ import annotations

import io
import re

from .base import OutputConnector

_INLINE = re.compile(r"(\*\*|__|`)")


class MarkdownOutput(OutputConnector):
    name = "md"
    extension = ".md"

    def render(self, markdown: str, title: str) -> bytes:
        return markdown.encode("utf-8")


class DocxOutput(OutputConnector):
    name = "docx"
    extension = ".docx"

    def __init__(self, font: str = "Times New Roman", size_pt: int = 12):
        self.font, self.size = font, size_pt

    def render(self, markdown: str, title: str) -> bytes:
        """Оформление — как у Планёрки (решение владелицы 22.11.2026, п. 2): Calibri 11, настоящие заголовки Word,
        поля по ГОСТ, таблицы с повторяющейся шапкой и своим размером колонок. Структура берётся из markdown, который
        готовит тот же показ, что и онлайн-монитор; конвертер общий с Планёркой."""
        import tempfile
        from pathlib import Path

        from . import md_to_docx

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "protocol.md"
            src.write_text(markdown, encoding="utf-8")
            готовый = md_to_docx.convert(src)
            return Path(готовый).read_bytes()
