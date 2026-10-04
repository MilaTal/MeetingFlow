"""Срок только из слов встречи — для письма 01, п. 6 (pipeline.py:244-248 у MeetFlow).

Модель вернула due «31.12.2030», в тексте срока нет — в реестр ушло 31.12.2030. Правило: срок принимается,
только если его значимые слова (числа, день недели, «конца недели») прозвучали в цитате или в соседних
строках. Иначе срок пустой, в карточку — пометка «срок не прозвучал».

Встраивание: due = supported_due(draft.due_date, окно_цитаты) перед записью задачи.
"""

import re

STOP = {"до", "к", "ко", "срок", "в", "на", "не", "позднее", "позже", "г", "года"}


def _n(s: str) -> str:
    return (s or "").lower().replace("ё", "е")


def supported_due(due, window_text: str):
    if not isinstance(due, str) or not due.strip():
        return None
    said = _n(window_text)
    toks = [w for w in re.split(r"[\s./,\-|]+", _n(due)) if w and w not in STOP]
    if toks and all((w if w.isdigit() else w[:5]) in said for w in toks):
        return due.strip()
    return None


CASES = [
    ("31.12.2030", "Петрова, подготовьте регламент склада", None),
    ("до пятницы", "Петрова, подготовьте регламент до пятницы", "до пятницы"),
    ("10.10", "сдать до 10.10", "10.10"),
    ("к понедельнику", "к понедельнику обновлю график", "к понедельнику"),
    ("до конца недели", "закончить до конца месяца", None),
    ({"x": 1}, "что угодно", None),
]

if __name__ == "__main__":
    bad = [(d, w, e, supported_due(d, w)) for d, w, e in CASES if supported_due(d, w) != e]
    print("ок" if not bad else bad)
