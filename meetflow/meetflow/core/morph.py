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


_DUE_STOP = {"до", "к", "ко", "срок", "в", "на", "не", "позднее", "позже", "г", "года"}


def supported_due(due, window_text: str) -> str | None:
    """Срок из ответа модели — только если его значимые слова есть в окне цитаты."""
    if not isinstance(due, str) or not due.strip():
        return None
    said = (window_text or "").lower().replace("ё", "е")
    toks = [w for w in re.split(r"[\s./,\-|]+", due.lower().replace("ё", "е")) if w and w not in _DUE_STOP]
    if toks and all((w if w.isdigit() else w[:5]) in said for w in toks):
        return due.strip()
    return None
