"""Текстовые источники: .txt / .md / вставка.

Кодировки: utf-8 (с BOM и без), utf-16 только с BOM, cp1251 — запасной путь
(у ERP и Планёрки встречались все три). Бинарный мусор и пустой файл
отклоняются сразу понятной ошибкой, а не падают дальше по конвейеру.
"""
from __future__ import annotations

from ..core.classify import classify_text
from ..core.text import sanitize, significant_chars
from ..core.types import SourceDoc
from .base import ConnectorError, SourceConnector

MIN_SIGNIFICANT = 20


def decode_bytes(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    text = data.decode("cp1251", errors="strict")
    return text


def looks_binary(data: bytes) -> bool:
    head = data[:4096]
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    return False


class TextSource(SourceConnector):
    name = "text"
    extensions = (".txt", ".md", ".text")

    def __init__(self, notes_markers: list[str] | None = None, own_output_markers: list[str] | None = None):
        self.notes_markers = notes_markers or []
        self.own_output_markers = own_output_markers or []

    def read(self, data: bytes, filename: str) -> SourceDoc:
        if not data:
            raise ConnectorError(f"Файл «{filename}» пустой.")
        if len(data) > self.max_bytes:
            raise ConnectorError(f"Файл «{filename}» больше {self.max_bytes // 1024 // 1024} МБ.")
        if looks_binary(data):
            raise ConnectorError(f"Файл «{filename}» не похож на текст — не читается.")
        try:
            text = sanitize(decode_bytes(data))
        except UnicodeDecodeError:
            raise ConnectorError(f"Файл «{filename}»: кодировка не распознана.") from None
        if significant_chars(text) < MIN_SIGNIFICANT:
            raise ConnectorError(f"В файле «{filename}» меньше {MIN_SIGNIFICANT} значащих знаков.")
        cl = classify_text(text, self.notes_markers, self.own_output_markers)
        return SourceDoc(filename, cl.kind, text, {"reply_share": round(cl.reply_share, 3),
                                                    "timecodes": cl.timecodes, "ambiguous": cl.ambiguous,
                                                    "own_output": cl.own_output, "connector": self.name})
