"""Название встречи для показа (слово владелицы 08.11.2026).

«из папки-приёмника:» убрать полностью; технические знаки имени файла в название не переносить — остаётся тема.
Чистится только название, которое записал сам приём (с этой пометкой): расширение, даты и время, rec/zoom/«копия»,
номера «(1)», подчёркивания и скобки. Ручное название не трогается. Та же логика — `cleanLabel` во фронте (app.js).
В базе название не меняется: хранение и приём — отдельной запиской машине (51bde83).
"""
from __future__ import annotations

import re

МЕТКА_ПРИЁМНИКА = re.compile(r"^\s*(?:создана\s+)?из\s+папки[-\s]?приёмника\s*:?\s*", re.IGNORECASE)
_Н, _К = r"(?<![^\W_])(?<!\d)", r"(?![^\W_])"
_РАСШИРЕНИЕ = re.compile(r"\.(?:m4a|mp3|wav|mp4|ogg|oga|webm|flac|aac|txt|docx?|pdf|vtt|srt)$", re.IGNORECASE)
_ЧИСТКА = [
    re.compile(_Н + r"\d{4}[-_.]?\d{2}[-_.]?\d{2}" + _К),          # 2026-11-05, 20261105
    re.compile(_Н + r"\d{1,2}[._-]\d{1,2}[._-]\d{2,4}" + _К),        # 05.11.2026
    re.compile(_Н + r"\d{1,2}[-_.:]\d{2}(?:[-_.:]\d{2})?" + _К),     # 10-30, 10_30_15
    re.compile(r"GMT\s*[+-]?\s*\d*", re.IGNORECASE),
    re.compile(_Н + r"\d{4,}" + _К),                                 # длинные номера
    re.compile(r"\(\d+\)"),
    re.compile(_Н + r"(?:rec|record|recording|audio|video|zoom|meeting|meet|telemost|запись|копия|copy|final)" + _К,
               re.IGNORECASE),
    re.compile(r"[_#@=+~^;{}\[\]()]"),
]


def тема_из_приёмника(текст: str | None) -> str:
    s = _РАСШИРЕНИЕ.sub("", str(текст or ""))
    for rx in _ЧИСТКА:
        s = rx.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s.,:;\-–—]+|[\s.,:;\-–—]+$", "", s)
    if not re.search(r"[^\W\d_]{3}", s):
        return ""
    return s[:1].upper() + s[1:]


def для_показа(label: str | None) -> str | None:
    """Название встречи на экран и в ответы API. Пустое — None (экран покажет «Встреча дд.мм.гггг»)."""
    if not label:
        return None
    if МЕТКА_ПРИЁМНИКА.match(label):
        return тема_из_приёмника(МЕТКА_ПРИЁМНИКА.sub("", label)) or None
    return label
