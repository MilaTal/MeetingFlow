"""Текстовые примитивы: нормализация, смысловые основы, нумерация строк, покрытие.

Модель отвечает НОМЕРОМ строки, а цитату достаёт код — так цитата не может быть выдумана
(приём Планёрки closing_check 21.09.26: верные закрытия 3 из 3 против 1 из 3 у пересказа).
"""

import re
import unicodedata
from functools import lru_cache

try:  # морфология офлайн; без неё — грубая основа по первым буквам (мягкая деградация)
    import pymorphy3

    _MORPH = pymorphy3.MorphAnalyzer()
except Exception:  # pragma: no cover - зависит от окружения
    _MORPH = None

STOPWORDS = {
    "и", "в", "во", "на", "по", "с", "со", "к", "ко", "о", "об", "от", "до", "за", "из", "у", "же",
    "а", "но", "что", "это", "как", "так", "то", "там", "тут", "вот", "ну", "да", "нет", "не", "ни",
    "мы", "вы", "он", "она", "они", "оно", "я", "ты", "его", "ее", "их", "нам", "вам", "мне", "тебе",
    "уже", "еще", "бы", "ли", "для", "при", "под", "над", "все", "всё", "этот", "эта", "эти", "тот",
    "который", "которая", "которые", "будет", "есть", "был", "была", "было", "были", "чтобы", "если",
    "или", "тоже", "также", "только", "очень", "можно", "надо", "нужно", "давайте", "пожалуйста",
}

# Невидимые и управляющие символы, которыми прячут текст (U+202E разворачивает строку на экране)
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿\x00-\x08\x0b\x0c\x0e-\x1f]")
_WORD = re.compile(r"[a-zа-я0-9]+", re.IGNORECASE)


def clean(text: str) -> str:
    """Убирает невидимые символы и приводит переводы строк к одному виду."""
    text = unicodedata.normalize("NFC", text or "")
    text = _INVISIBLE.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def norm(text: str) -> str:
    return clean(text).lower().replace("ё", "е")


def words(text: str) -> list:
    return _WORD.findall(norm(text))


@lru_cache(maxsize=50000)
def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if _MORPH is not None and re.fullmatch(r"[а-я]+", w):
        return _MORPH.parse(w)[0].normal_form.replace("ё", "е")
    return w[:6]


def content_stems(text: str) -> set:
    """Смысловые основы: без служебных слов и без чисел (даты «с 07.09» и «с 29.09» не должны совпадать)."""
    out = set()
    for w in words(text):
        if w in STOPWORDS or w.isdigit() or len(w) < 3:
            continue
        out.add(stem(w))
    return out


_DATE_LIKE = re.compile(r"\b\d{1,2}[./:]\d{1,2}(?:[./:]\d{2,4})?\b")


def numbers(text: str) -> set:
    """Номера вне дат и времени: «объект 3», «склад №5». Разные номера — разные задачи, даже при равных основах.

    Числа исключены из основ ради дат («с 07.09» и «с 29.09» не должны совпадать), и это молча склеивало
    «отчёт по объекту 0» с «отчёт по объекту 1» (нагрузочный тест 03.10.26: из 300 задач заведено 3).
    """
    return set(re.findall(r"\d+", _DATE_LIKE.sub(" ", clean(text))))


def same_subject(a: str, b: str, threshold: float) -> bool:
    """Повтор задачи: основы совпадают не меньше порога И номера вне дат одинаковы."""
    return coverage(a, b) >= threshold and numbers(a) == numbers(b)


def coverage(needle: str, haystack: str) -> float:
    """Доля смысловых основ needle, найденных в haystack. Пустое needle — 0, а не 1 (прибор не должен хвалить пустоту)."""
    a = content_stems(needle)
    if not a:
        return 0.0
    return len(a & content_stems(haystack)) / len(a)


NOT_SPEAKERS = {"Итого", "Итог", "Срок", "Задача", "Решение", "Решили", "Вопрос", "Ответ", "Повестка", "Тема",
                "Важно", "Примечание", "Протокол", "Участники", "Дата", "Пункт", "Внимание"}

_SENT_SPLIT =re.compile(r"(?<=[.!?])\s+(?=[А-ЯA-Z])")
_SPEAKER = re.compile(r"^\s*(?:\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*)?([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?|Говорящий\s*\d+|Спикер\s*\d+)\s*:\s*(.*)$")


def numbered_lines(text: str, max_len: int = 400) -> list:
    """Строки источника с номерами от 1. Длинные строки режутся по предложениям, чтобы номер указывал точно.

    Возвращает список словарей {n, speaker, text}. Говорящий берётся из префикса «Имя:» или «Говорящий 3:».
    """
    out = []
    for raw in clean(text).split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        speaker = None
        m = _SPEAKER.match(raw)
        body = raw
        if m and m.group(1) not in NOT_SPEAKERS:
            speaker, body = m.group(1), m.group(2)
        # реплика режется на предложения всегда: «Хорошо. Назаров, подготовьте…» — два разных высказывания,
        # и номер должен указывать на поручение, а не на всю реплику
        pieces = _SENT_SPLIT.split(body)
        for p in pieces:
            p = p.strip()
            if p:
                out.append({"n": len(out) + 1, "speaker": speaker, "text": p})
    return out


def render_lines(lines: list) -> str:
    return "\n".join(f"[{l['n']}] " + (f"{l['speaker']}: " if l["speaker"] else "") + l["text"] for l in lines)


def chunk_lines(lines: list, max_chars: int, overlap: int = 3) -> list:
    """Куски по max_chars с перекрытием в несколько строк: поручение на стыке не теряется."""
    chunks, cur, size = [], [], 0
    for l in lines:
        ln = len(l["text"]) + 12
        if cur and size + ln > max_chars:
            chunks.append(cur)
            cur = cur[-overlap:] if overlap else []
            size = sum(len(x["text"]) + 12 for x in cur)
        cur.append(l)
        size += ln
    if cur:
        chunks.append(cur)
    return chunks
