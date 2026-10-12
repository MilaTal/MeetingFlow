"""Дата встречи из имени файла.

Один алгоритм для всех коннекторов (в ERP были парсеры на Python и JS, их
сверяли parity-тестом). Уроки:
- «2026_09_05» читалось как 9 мая — сначала однозначные формы (год первым,
  4-значный год), найденное вымарывается, потом неоднозначные.
- «10.09.2026 11.05» читалось как 5 ноября — время не принимаем за дату.
- Голые 6 цифр не разбираются, год только текущий ±1, будущее отбрасывается.
- Нужна ровно одна дата; ноль или несколько — файл ждёт человека.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "сент": 9, "окт": 10, "ноя": 11, "дек": 12,
}

_PATTERNS = [
    # год первым: 2026-09-30, 2026_09_30, 2026.09.30
    (re.compile(r"(?<!\d)(20\d\d)[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"), "ymd"),
    # 20260930 — 8 цифр, год первым
    (re.compile(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)"), "ymd"),
    # 30.09.2026, 30_09_2026, 30 09 2026
    (re.compile(r"(?<!\d)(\d{1,2})[-_. ](\d{1,2})[-_. ](20\d\d)(?!\d)"), "dmy"),
    # 30 сент 2026 / 30 сентября
    (re.compile(r"(?<!\d)(\d{1,2})\s*(январ[ья]|янв|феврал[ья]|фев|марта?|мар|апрел[ья]|апр|ма[яй]|июн[ья]|июн|"
                r"июл[ья]|июл|августа?|авг|сентябр[ья]|сент|сен|октябр[ья]|окт|ноябр[ья]|ноя|декабр[ья]|дек)"
                r"(?![а-яё])\.?(?:\s*(20\d\d))?", re.I), "dMy"),
    # 30.09.26 — двузначный год последним; не часть версии «v1.2.26» и не
    # кусок большего числа, но точка перед расширением файла допустима
    (re.compile(r"(?<![\w.])(\d{1,2})[-_.](\d{1,2})[-_.](\d\d)(?!\w|\.\d)"), "dmy2"),
]
_TIME = re.compile(r"(?<![\d.:_-])([01]?\d|2[0-3])[.:]([0-5]\d)(?![.:_-]?\d)")


def _valid(y: int, m: int, d: int, today: date) -> date | None:
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    if abs(dt.year - today.year) > 1 or dt > today:
        return None
    return dt


def dates_in_name(name: str, today: date | None = None) -> list[date]:
    today = today or date.today()
    s = name
    found: list[date] = []
    for rx, kind in _PATTERNS:
        if kind == "dmy2":
            # время «11.05» рядом с датой — не дата; убираем до двузначных форм
            s = _TIME.sub(lambda mm: "#" * len(mm.group(0)), s)
        for m in list(rx.finditer(s)):
            g = m.groups()
            dt = None
            if kind == "ymd":
                dt = _valid(int(g[0]), int(g[1]), int(g[2]), today)
            elif kind == "dmy":
                dt = _valid(int(g[2]), int(g[1]), int(g[0]), today)
            elif kind == "dMy":
                month = _MONTHS.get(g[1].lower()[:4]) or _MONTHS.get(g[1].lower()[:3])
                if month and g[2]:
                    dt = _valid(int(g[2]), month, int(g[0]), today)
                elif month:
                    # без года: эта дата в текущем году, а если она в будущем —
                    # значит прошлый год («30 дек» в январе)
                    dt = _valid(today.year, month, int(g[0]), today) or _valid(today.year - 1, month, int(g[0]), today)
            elif kind == "dmy2":
                dt = _valid(2000 + int(g[2]), int(g[1]), int(g[0]), today)
            if dt and dt not in found:
                found.append(dt)
            # вымарываем найденное, чтобы не разобрать повторно иначе
            s = s[: m.start()] + "#" * (m.end() - m.start()) + s[m.end():]
    return found


def single_date(name: str, today: date | None = None) -> date | None:
    """Ровно одна однозначная дата — иначе None (решает человек)."""
    found = dates_in_name(name, today)
    return found[0] if len(found) == 1 else None


def lenient_date(value: str | None) -> date | None:
    """Дата встречи из базы: ISO или ДД.ММ.ГГГГ; непонятная — None, а не сбой
    прогона (письмо meeting-registry 01/24: «02.10.2026» ронял прогон с единицами)."""
    s = (value or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def due_text(due: str | None, date_set: str | None, kind: str | None = None) -> str:
    """Срок для человека (владелец 12.10.26): срок, равный дате встречи, — «сегодня (дд.мм.гггг)», иначе голая дата
    читается как дата постановки. Просрочка по нему настоящая. Срок раньше даты постановки сохраняется как есть и
    помечается — решение по нему за владельцем. Непонятный срок («к следующей встрече») — как записан."""
    due = (due or "").strip()
    d, s = lenient_date(due), lenient_date(date_set)
    if not d or not s:
        return due
    shown = f"{d.day:02d}.{d.month:02d}.{d.year}"
    if d == s:
        return f"сегодня ({shown})"
    if kind == "оценка":       # «к следующему совещанию» = дата встречи + 7 дней (владелец 12.10.26)
        return f"{shown} (оценка)"
    return f"{shown} (раньше даты постановки — как в источнике)" if d < s else shown
