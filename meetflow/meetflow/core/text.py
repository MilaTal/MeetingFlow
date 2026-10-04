"""Текстовые утилиты ядра: чистка входа, основы слов, сходство.

Уроки, зашитые сюда:
- SQLite lower()/LIKE не понимают кириллицу — сравниваем в Python (ERP 12.09).
- Основы по «первым 5 буквам» ловили «Алексей»~«Алексейко» и «Отдел…»~любой
  отдел — здесь сравниваем целые основы, а хвост ограничен 2 буквами.
- Невидимые и управляющие символы вырезаются до любых проверок.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# zero-width, bidi-override, BOM — частый носитель скрытых инструкций
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")

# Русские окончания для облегчённого стемминга без внешних зависимостей.
# инфинитив и повелительное наклонение сводятся к одной основе:
# «подготовить» / «подготовьте» -> «подготов» (иначе цитата поручения
# не находилась по формулировке задачи — найдено итерацией 4)
_ENDINGS = sorted(
    """ьте йте ите ить ать ять еть ыть уть
    ами ями ого его ому ему ыми ими ой ей ий ый ая яя ое ее ые ие ом ем ах ях
    ов ев ам ям ую юю ть ся сь ет ут ют ит ат ят ешь ишь ем им ла ло ли ал ил
    а я о е ы и у ю ь""".split(),
    key=len, reverse=True,
)

STOP_WORDS = frozenset(
    """и в во не на с со к ко по о об от до за из у же ли бы что как это то
    так а но или да нет мы вы он она они оно я ты его её их там тут вот
    все всё уже ещё еще для при над под про через быть был была были""".split()
)


def sanitize(text: str) -> str:
    """Чистка недоверенного текста: NFC, без управляющих и невидимых символов."""
    text = unicodedata.normalize("NFC", text or "")
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub("", text)
    return text


def significant_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", sanitize(text)))


def words(text: str) -> list[str]:
    return [w.lower().replace("ё", "е") for w in _WORD.findall(text or "")]


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if len(w) <= 4:
        return w
    for end in _ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[: -len(end)]
    return w


def stems(text: str, drop_stop: bool = True) -> list[str]:
    return [stem(w) for w in words(text) if not (drop_stop and w in STOP_WORDS)]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def coverage(part: set[str], whole: set[str]) -> float:
    """Доля основ part, найденных в whole (асимметрично)."""
    if not part:
        return 0.0
    return len(part & whole) / len(part)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


# Падежные окончания имён и фамилий: хвост должен быть одним из них.
# Правило Планёрки 02.10 «хвост ≤ 2 букв» пропускало «Мария»~«Марина» и
# «Алексей»~«Алексейко» (известный предел) — проверка окончания закрывает оба.
_NAME_TAILS = frozenset("""
 а я ы и е у ю ь й о ой ей ою ею ом ем ым им ах ях ам ям ами ями ов ев
 ого его ому ему ая яя ую юю ий ый ие ые их ых
""".split()) | {""}


def same_word(a: str, b: str, max_tail: int = 3) -> bool:
    """Одно слово в разных падежах: общая основа ≥ 4 букв, а хвосты с обеих
    сторон — падежные окончания (≤ max_tail букв). Аддитивное ограничение:
    может только убирать совпадения."""
    a, b = a.lower().replace("ё", "е"), b.lower().replace("ё", "е")
    if a == b:
        return True
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    if n < 4:
        return False
    ta, tb = a[n:], b[n:]
    if len(ta) > max_tail or len(tb) > max_tail:
        return False
    if ta in _NAME_TAILS and tb in _NAME_TAILS:
        return True
    # основа могла «съесть» гласную окончания: Анастаси|я ~ Анастаси|и
    return n > 4 and (a[n - 1] + ta) in _NAME_TAILS and (b[n - 1] + tb) in _NAME_TAILS


def same_lexeme(a: str, b: str) -> bool:
    """Одно слово в другой форме — для поиска и склейки, не для имён людей.

    Правило из ответа Проекта ERP 03.10.26: совпадение с начала слова и хвост
    не длиннее трёх букв с обеих сторон («согласовать» ~ «согласовали»,
    «поставки» ~ «поставок», «Назаров» ~ «Назаровой»). Короткое слово (3
    буквы) — только с падежным окончанием: «кот» ~ «кота», но не «который»,
    «том» не находит «томат». Числа — только целиком. Для имён остаётся
    same_word: «Алексей» ~ «Алексейко» здесь совпадает, там — нет."""
    a, b = a.lower().replace("ё", "е"), b.lower().replace("ё", "е")
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    ta, tb = a[n:], b[n:]
    if n >= 4:
        return len(ta) <= 3 and len(tb) <= 3
    return n == 3 and ta in _NAME_TAILS and tb in _NAME_TAILS


def content_words(text: str) -> list[str]:
    """Слова, по которым различаются пункты: без служебных, от трёх букв, и числа."""
    return [w for w in words(text) if w not in STOP_WORDS and (len(w) >= 3 or w.isdigit())]


def word_triples(text: str) -> set[tuple[str, str, str]]:
    ws = words(text)
    return {tuple(ws[i:i + 3]) for i in range(len(ws) - 2)}  # type: ignore[misc]
