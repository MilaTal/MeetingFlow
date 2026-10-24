"""Формы системных пометок и хвостов секретаря — общий файл ERP и Планёрки `document_marks.md`.

Файл лежит рядом, копия байт в байт с ERP и Планёркой (стенд 13.10.26); правится там, сюда переносится целиком.
Своё у MeetFlow — формы шапки протокола до 15.10.26 (`MEETFLOW_MARKS`): их нет в общем файле, потому что у ERP и
Планёрки шапка другая. Правила владельца 13.10.26: документ чистый для читателя (находка стенда 30); хвост
секретаря в формулировке задачи вырезает код при любом заведении (находка стенда 31, Планёрка №219).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

FILE = Path(__file__).with_name("document_marks.md")
MARKS_SECTION = "### Формы пометок"
TAILS_SECTION = "### Хвосты секретаря в формулировке задачи"

# шапка протокола MeetFlow до 15.10.26 — старые протоколы в базах хранят её; выгрузка их чистит
MEETFLOW_MARKS = [
    r"^\s*\*?\s*Откуда:\s*собран",
    r"^\s*\*?\s*Обработано:",
    r"Стенд без модели",
    r"[Пп]рогон остановлен по пределу",
    r"^\s*Не собрано:",
    r"обращены к самой системе",
    r"сверку закрытий взяты",
]


def _section(name: str) -> list[str]:
    text = FILE.read_text(encoding="utf-8")
    body = text.split(name, 1)[1].split("\n### ", 1)[0]
    return re.findall(r"^- `([^`]+)`", body, re.MULTILINE)


@lru_cache(maxsize=1)
def marks() -> tuple[re.Pattern, ...]:
    return tuple(re.compile(f, re.IGNORECASE | re.MULTILINE) for f in _section(MARKS_SECTION) + MEETFLOW_MARKS)


@lru_cache(maxsize=1)
def tails() -> tuple[re.Pattern, ...]:
    return tuple(re.compile(f, re.IGNORECASE) for f in _section(TAILS_SECTION))


def strip_tails(description: str | None) -> tuple[str | None, list[str]]:
    """(формулировка без хвостов секретаря, вырезанное). Вырезанное — в журнал, без карточки; если формулировка
    стала бы пустой, остаётся как была (так же, как secretary_tails.py у ERP)."""
    if not description:
        return description, []
    text, cut = description, []
    for f in tails():
        cut += [m.group(0).strip(" ,;") for m in f.finditer(text)]
        text = f.sub("", text)
    if not cut:
        return description, []
    text = re.sub(r"[ \t]{2,}", " ", text).strip(" ,;\t")
    if not text:
        return description, []
    log.info("Из формулировки задачи вырезан хвост секретаря %s", cut)
    return text, cut
