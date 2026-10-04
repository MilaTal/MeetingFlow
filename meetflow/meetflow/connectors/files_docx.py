"""Источник .docx.

Уроки ридеров ERP и Планёрки (02.10): абзацы в ячейке склеивались
(«освещениюДата:»), терялись w:br и w:tab, вложенные таблицы читались
трижды. Здесь обход идёт по XML тела документа в порядке следования:
абзац -> строка, ячейки таблицы -> «a | b | c», переносы и табы сохраняются,
вложенная таблица читается один раз внутри своей ячейки.
"""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from ..core.classify import classify_text
from ..core.text import sanitize, significant_chars
from ..core.types import SourceDoc
from .base import ConnectorError, SourceConnector

MAX_XML_BYTES = 50 * 2 ** 20
MAX_RATIO = 100
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _para_text(p: ET.Element) -> str:
    out: list[str] = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            out.append(el.text)
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out)


def _cell_text(tc: ET.Element) -> str:
    parts: list[str] = []
    for child in tc:
        if child.tag == W + "p":
            parts.append(_para_text(child))
        elif child.tag == W + "tbl":
            parts.append(_table_text(child))
    return " / ".join(x.strip() for x in parts if x.strip())


def _table_text(tbl: ET.Element) -> str:
    rows = []
    for tr in tbl.findall(W + "tr"):
        cells = [_cell_text(tc) for tc in tr.findall(W + "tc")]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def docx_to_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            # защита от zip-бомбы: 306 КБ разворачивались в 1,1 ГБ памяти (ревью)
            if info.file_size > MAX_XML_BYTES or info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise ConnectorError("Файл .docx подозрителен: слишком большой объём после распаковки.")
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise ConnectorError("Файл .docx повреждён или это не .docx.") from None
    root = ET.fromstring(xml)
    body = root.find(W + "body")
    if body is None:
        return ""
    blocks = []
    for child in body:
        if child.tag == W + "p":
            blocks.append(_para_text(child))
        elif child.tag == W + "tbl":
            blocks.append(_table_text(child))
    return "\n".join(blocks)


class DocxSource(SourceConnector):
    name = "docx"
    extensions = (".docx",)

    def __init__(self, notes_markers: list[str] | None = None, own_output_markers: list[str] | None = None):
        self.notes_markers = notes_markers or []
        self.own_output_markers = own_output_markers or []

    def read(self, data: bytes, filename: str) -> SourceDoc:
        if not data:
            raise ConnectorError(f"Файл «{filename}» пустой.")
        if len(data) > self.max_bytes:
            raise ConnectorError(f"Файл «{filename}» больше {self.max_bytes // 1024 // 1024} МБ.")
        text = sanitize(docx_to_text(data))
        if significant_chars(text) < 20:
            raise ConnectorError(f"В файле «{filename}» почти нет текста.")
        cl = classify_text(text, self.notes_markers, self.own_output_markers)
        return SourceDoc(filename, cl.kind, text, {"reply_share": round(cl.reply_share, 3),
                                                    "ambiguous": cl.ambiguous, "own_output": cl.own_output,
                                                    "connector": self.name})
