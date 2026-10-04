"""Вид источника — по содержанию, а не по расширению.

Урок Планёрки 28.09: .docx бывает расшифровкой, заметками или «прочим»;
форма по умолчанию «протокол секретаря» отказывала настоящей расшифровке.
Пороги из Планёрки: расшифровка — доля строк-реплик ≥ 0.4 и ≥ 3 таймкодов;
заметки — ≥ 2 признаков методички (theme.notes_markers) и реплик < 0.2.
Спорный случай не решается молча — возвращается ambiguous=True (карточка).
Защита от «своего вывода как эталона»: текст, похожий на выгрузку самого
framework (theme.own_output_markers), помечается own_output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .types import SourceKind

_TIMECODE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_REPLY = re.compile(r"^\s*(?:\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*)?[A-ZА-ЯЁ][\wА-Яа-яЁё .\-]{1,40}\s*[:\t]\s*\S")
MEDIA_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".ogg", ".flac"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class Classification:
    kind: SourceKind
    reply_share: float
    timecodes: int
    notes_markers: int
    ambiguous: bool = False
    own_output: bool = False


def classify_text(text: str, notes_markers: list[str] | None = None,
                  own_output_markers: list[str] | None = None) -> Classification:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    n = max(len(lines), 1)
    replies = sum(1 for ln in lines if _REPLY.match(ln))
    share = replies / n
    # «Повестка: склад» в заметках похожа на реплику — для заметок считаем
    # только реплики с таймкодом
    share_tc = sum(1 for ln in lines if _REPLY.match(ln) and _TIMECODE.search(ln[:12])) / n
    tcs = len(_TIMECODE.findall(text))
    low = text.lower()
    markers = sum(1 for m in (notes_markers or []) if m.lower() in low)
    own = sum(1 for m in (own_output_markers or []) if m.lower() in low) >= 2

    if share >= 0.4 and tcs >= 3:
        return Classification(SourceKind.TRANSCRIPT, share, tcs, markers, own_output=own)
    if markers >= 2 and share_tc < 0.2:
        return Classification(SourceKind.NOTES, share, tcs, markers, own_output=own)
    ambiguous = (0.2 <= share_tc < 0.4) or (markers >= 2 and share_tc >= 0.2)
    return Classification(SourceKind.OTHER, share, tcs, markers, ambiguous=ambiguous, own_output=own)


def kind_by_extension(name: str) -> SourceKind | None:
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in MEDIA_EXT:
        return SourceKind.RECORDING
    if ext in IMAGE_EXT:
        return SourceKind.IMAGE
    return None
