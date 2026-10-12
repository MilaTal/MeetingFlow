"""Морфология для правила отрицаний и сверки сроков.

Перенесено из пакета 01 ветки meeting-registry (письмо 05, 03.10.26;
источник — их negation.py::_has_done_form и due_check.py), с правками MeetFlow.

1. has_done_form — признак свершившегося действия: прошедшее время
   совершенного вида или краткое причастие совершенного вида. Список слов
   выполнения пропускал «посчитали», «пересчитали», «оплачен» (письмо 01/15).
   Глаголы речи и начала («сказал», «пообещал», «начали») — не работа.
   Без pymorphy3 — None: правило остаётся на своём списке.
2. supported_due — срок принимается, только если его слова прозвучали в
   цитате или соседних строках: модель вписывала «31.12.2030», которого во
   встрече не было (письмо 01/6).
"""
from __future__ import annotations

import re

try:  # необязательная зависимость: без неё — мягкая деградация на список
    import pymorphy3
    _MORPH = pymorphy3.MorphAnalyzer()
except Exception:  # pragma: no cover
    _MORPH = None

SPEECH = {"сказать", "говорить", "спросить", "предложить", "обещать", "пообещать", "напомнить", "решить",
          "обсудить", "договориться", "уточнить", "ответить", "попросить", "поручить", "начать", "забыть",
          # снятие — не выполнение: «отменили» без этого читалось как «сделано» (найдено тестом
          # снятия по голосу при переносе, 03.10.26)
          "отменить", "снять", "отказаться", "вычеркнуть",
          # список ветки meeting-registry (письмо 12): отказ и прекращение — тоже не выполнение
          "отклонить", "аннулировать", "прекратить", "отозвать"}


def has_done_form(phrase: str) -> bool | None:
    """True — есть форма свершившегося действия; False — нет; None — морфологии нет."""
    if _MORPH is None:
        return None
    for w in re.findall(r"[а-яё]+", (phrase or "").lower()):
        for parse in _MORPH.parse(w.replace("ё", "е"))[:2]:
            tag = parse.tag
            if parse.normal_form in SPEECH:
                continue
            if ("VERB" in tag and "past" in tag and "perf" in tag) or ("PRTS" in tag and "perf" in tag):
                return True
    return False


def lemmas(text: str) -> set[str] | None:
    """Леммы значимых слов («закажите» → «заказать»); без pymorphy3 — None."""
    if _MORPH is None:
        return None
    from .text import STOP_WORDS, words
    return {_MORPH.parse(w)[0].normal_form.replace("ё", "е") for w in words(text) if w not in STOP_WORDS}


_TODAY = {"сегодня", "сегодняшнего", "конца", "дня", "вечера"}
_DUE_STOP = {"до", "к", "ко", "срок", "в", "на", "не", "позднее", "позже", "г", "года"}
_MONTHS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
_NUM_DATE = re.compile(r"^\s*(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?)\s*$")


def _numeric_date_said(due: str, said: str) -> tuple[int, int, int | None] | None:
    """D2 (прогон 09.10.26): модель вернула «2026-10-07», а прозвучало «до 7 октября». Дата цифрами принимается,
    если в окне цитаты прозвучали её число и месяц — словом («октября») или цифрами («07.10»)."""
    m = _NUM_DATE.match(due)
    if not m:
        return None
    day, month = (int(m.group(3)), int(m.group(2))) if m.group(1) else (int(m.group(4)), int(m.group(5)))
    year = int(m.group(1)) if m.group(1) else (int(m.group(6)) if m.group(6) else None)
    if year is not None and year < 100:
        year += 2000
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    toks = re.findall(r"[а-яa-z]+|\d+", said)
    day_said = any(t.isdigit() and int(t) == day for t in toks)
    stem = _MONTHS[month - 1]
    month_said = any(t.startswith(stem) and (stem != "ма" or t in ("мая", "май", "мае")) for t in toks)
    numeric = re.search(rf"\b0?{day}\.0?{month}\b", said) is not None
    if not ((day_said and month_said) or numeric):
        return None
    year_said = year is not None and str(year) in toks
    return day, month, (year if year_said else None)


def _word_date(due: str) -> tuple[int, int, int | None] | None:
    """«20 октября», «до 20 октября 2026» — число, месяц словом и, если есть, год (цикл 2 прогона 09.10.26, D6)."""
    toks = re.findall(r"[а-яa-z]+|\d+", due.lower().replace("ё", "е"))
    nums = [int(t) for t in toks if t.isdigit()]
    month = next((i + 1 for t in toks for i, st in enumerate(_MONTHS)
                  if t.startswith(st) and (st != "ма" or t in ("мая", "май", "мае"))), None)
    day = next((n for n in nums if 1 <= n <= 31), None)
    if not month or not day:
        return None
    year = next((n for n in nums if n >= 2000), None)
    return day, month, year


def _owner_format(day: int, month: int, year: int | None, meeting_date: str | None, fallback: str) -> str | None:
    """Формат владельца «день.месяц.год». Год, которого не было в речи, не берётся у модели (прогон 09.10.26:
    «2023-10-07» при планёрке 2026): ближайшая такая дата не раньше встречи; без даты встречи — как дала модель."""
    from datetime import date
    if year is None and meeting_date:
        try:
            md = date.fromisoformat(str(meeting_date)[:10])
            year = md.year if (month, day) >= (md.month, md.day) else md.year + 1
        except ValueError:
            year = None
    if year is None:
        return fallback
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


_DUE_NEG = re.compile(r"\bне\s+(?:к|ко|до|успе\w*|сможе\w*|получится|будет|раньше|позже|позднее)\b|\bвряд\s+ли\b")
_WEEK = ("понедельн", "вторн", "сред", "четверг", "пятниц", "суббот", "воскресен")


def due_negated(due: str, window_text: str) -> bool:
    """Правило отрицаний для срока (владелец 12.10.26): «к пятнице не успеем», «успеем до 5 октября?» срока не дают.
    Смотрятся предложения окна, где звучат слова этого срока: если каждое из них — вопрос или отрицание, срока нет."""
    low = (window_text or "").lower().replace("ё", "е")
    keys = [w for w in re.findall(r"[а-яa-z]+|\d+", due.lower().replace("ё", "е")) if w not in _DUE_STOP]
    keys = [w if w.isdigit() else w[:5] for w in keys]
    num = _NUM_DATE.match(due.strip())
    if num:                                   # срок цифрами: в речи — число и месяц словом или «дд.мм»
        day = int(num.group(3)) if num.group(1) else int(num.group(4))
        month = int(num.group(2)) if num.group(1) else int(num.group(5))
        keys = [str(day), _MONTHS[month - 1]]
    if not keys:
        return False
    sentences = re.findall(r"[^.!?\n]+[.!?]?", low)
    hit = [s for s in sentences if any((k in re.findall(r"[а-яa-z]+|\d+", s)) if k.isdigit() else k in s for k in keys)]
    return bool(hit) and all(s.strip().endswith("?") or _DUE_NEG.search(s) for s in hit)


def supported_due(due, window_text: str, meeting_date: str | None = None) -> str | None:
    """Срок из ответа модели — только если его значимые слова есть в окне цитаты и не под отрицанием или вопросом."""
    if not isinstance(due, str) or not due.strip():
        return None
    if due_negated(due, window_text):
        return None
    said = (window_text or "").lower().replace("ё", "е")
    num = _numeric_date_said(due, said)
    if num:
        day, month, year = num
        if year is None and meeting_date:
            from datetime import date
            try:
                md = date.fromisoformat(str(meeting_date)[:10])
                year = md.year if (month, day) >= (md.month, md.day) else md.year + 1
            except ValueError:
                year = None
        if year is None:
            return due.strip()
        try:
            from datetime import date
            d = date(year, month, day)            # формат владельца: день.месяц.год, год четырёхзначный
            return f"{d.day:02d}.{d.month:02d}.{d.year}"
        except ValueError:
            return None
    toks = [w for w in re.split(r"[\s./,\-|]+", due.lower().replace("ё", "е")) if w and w not in _DUE_STOP]
    if toks and set(toks) <= _TODAY and "сегодн" in said and meeting_date:
        # «сегодня» — настоящий срок, дата встречи (владелец 12.10.26); показ — «сегодня (дата)», см. dates.due_text
        from .dates import lenient_date
        md = lenient_date(str(meeting_date))
        return f"{md.day:02d}.{md.month:02d}.{md.year}" if md else due.strip()
    if toks and all((w if w.isdigit() else w[:5]) in said for w in toks):
        wd = _word_date(due)
        if wd:        # D6: прозвучавший срок словами — тоже в формате владельца
            return _owner_format(wd[0], wd[1], wd[2] if wd[2] and str(wd[2]) in said else None, meeting_date,
                                 due.strip())
        return due.strip()
    return None
