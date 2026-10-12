"""Копия `deadline.py` Проекта ERP и Планёрки (12.10.26); отличие одно — разбор на слова вместо импорта
модуля отрицаний. Срок задачи из фразы совещания (правило владельца 12.10.2026, письмо ветки copilot «12.10 01-05»).

Правило: срок пишется всегда, когда он прозвучал; не прозвучал — пусто. «Сегодня» и срок, равный дате совещания, — настоящий
срок, показывается «сегодня (дд.мм.гггг)», голой датой — никогда: её путают с датой постановки. Относительный срок
(«завтра», «к пятнице», «через две недели») переводится в дату от даты совещания, исходная фраза хранится рядом.
«К следующему совещанию» — дата совещания + 7 дней с пометкой «оценка» (решение владельца 13.10.2026: у встреч ERP дата
следующей заранее неизвестна). Спорное — два срока в одной фразе, срок раньше совещания, фраза без распознанного срока —
не решается молча, а уходит оператору карточкой.

Отрицание и вопрос срока не дают («не к пятнице», «к пятнице успеете?») — по правилу отрицаний. Поручение и будущее время
сроку не мешают: «сделайте к следующему совещанию» и есть срок, поэтому общий признак «сомнительно» модуля negation здесь
не годится — берётся только отрицание перед словом срока и вопрос.

Почему поле было пустым у всех 151 задачи (разбор 13.10.2026): функция срока брала только дату ПОЗЖЕ встречи («дата самой
встречи — постановка»), относительные сроки не переводила, промпт не объяснял поле срока."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta



class negation:  # noqa: N801 — в ERP и Планёрке это модуль правила отрицаний; здесь нужен только его разбор на слова
    _TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")

TODAY, ESTIMATE, BEFORE_MEETING = "сегодня", "оценка", "раньше встречи"
ISSUE_TWO, ISSUE_BEFORE, ISSUE_UNREAD = "два срока", "срок раньше даты совещания", "срок не распознан"
ISSUE_NOT_IN_RECORD = "срок не найден в записи рядом с поручением"
NEXT_MEETING_DAYS = 7

_WEEKDAYS = (("понедельник", 0), ("вторник", 1), ("сред", 2), ("четверг", 3), ("пятниц", 4), ("суббот", 5), ("воскресен", 6))
_NUM_WORDS = {"один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
              "семь": 7, "десять": 10}

_EXPLICIT = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?![\d])")
_DAY_OF_MONTH = re.compile(r"\b(?:до|к|ко)\s+(\d{1,2})\s*-?\s*(?:го|му|е|числа)\b")
_IN = re.compile(r"\bчерез\s+(\d+|один|одну|одна|два|две|три|четыре|пять|шесть|семь|десять)?\s*"
                 r"(день|дня|дней|неделю|недели|недель|месяц|месяца|месяцев)\b")
_WEEKDAY = re.compile(r"\b(?:до|к|ко|в|во|на)\s+(?:следующ\w+\s+|этот\s+|эту\s+|эти\s+)?"
                      r"(понедельник\w*|вторник\w*|сред[ауы]\w*|четверг\w*|пятниц\w*|суббот\w*|воскресен\w*)")
_NEXT_MEETING = re.compile(r"\b(?:к|до|на)\s+следующ\w+\s+(?:совещани\w*|встреч\w*|планерк\w*|планёрк\w*|созвон\w*|заседани\w*)")
_SIMPLE = (
    (re.compile(r"\bпослезавтра\b"), 2),
    (re.compile(r"\bзавтра\b"), 1),
    (re.compile(r"\bсегодня\b"), 0),
)
_END_WEEK = re.compile(r"\b(?:до|к)\s+конц\w*\s+(?:этой\s+)?недел\w*|\bна\s+этой\s+неделе\b")
_NEXT_WEEK = re.compile(r"\bна\s+следующей\s+неделе\b|\b(?:до|к)\s+конц\w*\s+следующей\s+недел\w*")
_END_MONTH = re.compile(r"\b(?:до|к)\s+конц\w*\s+(?:этого\s+)?месяц\w*")


@dataclass
class Deadline:
    due: date | None = None
    kind: str | None = None          # None — обычная дата; «сегодня»; «оценка»; «раньше встречи»
    phrase: str = ""
    issue: str | None = None         # спорное — карточкой оператору


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


# «не позднее 15.10», «не позже пятницы» — это срок, а не отказ от него; «не забудьте к пятнице» — тоже
_NOT_A_NEGATION = ("позднее", "позже", "забуд")
_CLAUSE_END = re.compile(r"[,.;:!?\n]|\s(?:но|а|однако)\s")


def _negating(tokens: list[str]) -> bool:
    for k, tok in enumerate(tokens):
        if tok in ("не", "нет") and not (k + 1 < len(tokens) and tokens[k + 1].startswith(_NOT_A_NEGATION)):
            return True
    return False


def _negated_or_question(text: str, start: int) -> bool:
    """Срок отменён: фраза — вопрос («к пятнице успеете?») или в той же части фразы есть отрицание — перед словом срока
    («не к пятнице», «не завтра») или после него («к пятнице не успеем», «завтра не сделаем»). Находка ветки «Мониторинг»
    12.10.26 для MeetFlow и Планёрки, проверено у нас 13.10: отрицание после слова срока давало срок. Берётся из правила
    отрицаний только это — не будущее время и не поручение: «сделайте к пятнице» — срок."""
    sentence_end = re.search(r"[.!?]", text[start:])
    if sentence_end and text[start + sentence_end.start()] == "?":
        return True
    before = negation._TOKEN_RE.findall(_norm(text[:start]))[-2:]
    end = _CLAUSE_END.search(text, start + 1)
    after = negation._TOKEN_RE.findall(_norm(text[start:end.start() if end else len(text)]))
    return _negating(before) or _negating(after)


def _next_weekday(base: date, weekday: int) -> date:
    days = (weekday - base.weekday()) % 7
    return base + timedelta(days=days or 7)


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _friday_of_week(d: date) -> date:
    friday = d + timedelta(days=4 - d.weekday())
    return friday if friday >= d else friday + timedelta(days=7)


def _candidates(text: str, meeting: date) -> list[tuple[date, str | None, int]]:
    """Все сроки фразы: (дата, вид, позиция). Отрицания и вопросы отброшены."""
    t = _norm(text)
    out: list[tuple[date, str | None, int]] = []

    def add(d: date | None, kind: str | None, pos: int) -> None:
        if d is not None and not _negated_or_question(t, pos):
            out.append((d, kind, pos))

    for m in _EXPLICIT.finditer(t):
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            if year:
                y = int(year) + (2000 if len(year) == 2 else 0)
                add(date(y, month, day), None, m.start())
            else:
                d = date(meeting.year, month, day)
                add(d if d >= meeting else date(meeting.year + 1, month, day), None, m.start())
        except ValueError:
            pass
    for m in _DAY_OF_MONTH.finditer(t):
        day = int(m.group(1))
        try:
            d = date(meeting.year, meeting.month, day)
            add(d if d >= meeting else _add_months(d, 1), None, m.start())
        except ValueError:
            pass
    for rx, days in _SIMPLE:
        for m in rx.finditer(t):
            if days == 1 and t[max(0, m.start() - 5):m.start()] == "после":
                continue
            add(meeting + timedelta(days=days), None, m.start())
    for m in _IN.finditer(t):
        n = m.group(1)
        n = int(n) if n and n.isdigit() else _NUM_WORDS.get(n or "", 1)
        unit = m.group(2)
        if unit.startswith("д"):
            add(meeting + timedelta(days=n), None, m.start())
        elif unit.startswith("нед"):
            add(meeting + timedelta(days=7 * n), None, m.start())
        else:
            add(_add_months(meeting, n), None, m.start())
    for m in _WEEKDAY.finditer(t):
        word = m.group(1)
        wd = next(i for stem, i in _WEEKDAYS if word.startswith(stem[:4]))
        add(_next_weekday(meeting, wd), None, m.start())
    for m in _NEXT_MEETING.finditer(t):
        add(meeting + timedelta(days=NEXT_MEETING_DAYS), ESTIMATE, m.start())
    for m in _NEXT_WEEK.finditer(t):
        add(_friday_of_week(meeting) + timedelta(days=7), ESTIMATE, m.start())
    for m in _END_WEEK.finditer(t):
        add(_friday_of_week(meeting), None, m.start())
    for m in _END_MONTH.finditer(t):
        add(date(meeting.year, meeting.month, calendar.monthrange(meeting.year, meeting.month)[1]), None, m.start())
    return out


def resolve(phrase: str | None, meeting: date, model_date: date | None = None) -> Deadline:
    """Срок из фразы совещания. Фраза важнее даты модели: код считает от даты встречи сам и не верит пересказу. Нет фразы —
    берётся дата модели (её тоже проверяют на «раньше встречи»)."""
    phrase = (phrase or "").strip()
    found = _candidates(phrase, meeting) if phrase else []
    if not found and model_date is None:
        if phrase and not _negated_any(phrase):
            return Deadline(phrase=phrase, issue=ISSUE_UNREAD)
        return Deadline(phrase=phrase)
    if found:
        dates = {d for d, _k, _p in found}
        due, kind, _pos = sorted(found, key=lambda x: x[2])[0]
        issue = ISSUE_TWO if len(dates) > 1 else None
    else:
        due, kind, issue = model_date, None, None
    if due == meeting:
        kind = TODAY
    elif due < meeting:
        kind, issue = BEFORE_MEETING, issue or ISSUE_BEFORE
    return Deadline(due=due, kind=kind, phrase=phrase, issue=issue)


def _negated_any(phrase: str) -> bool:
    """Фраза сама по себе — отрицание или вопрос («к пятнице не успеем», «срок?»): это не «нераспознанный срок»."""
    t = _norm(phrase)
    return t.rstrip().endswith("?") or bool(re.search(r"\bне\b|\bнет\b", t))


def label(due: date | None, date_set: date | None = None, kind: str | None = None) -> str:
    """Как срок показывается человеку: «сегодня (дд.мм.гггг)», «дд.мм.гггг (оценка)» или просто дата. Голой датой срок,
    равный дате постановки, не показывается никогда."""
    if due is None:
        return ""
    if kind == TODAY or (date_set is not None and due == date_set):
        return f"сегодня ({due:%d.%m.%Y})"
    if kind == ESTIMATE:
        return f"{due:%d.%m.%Y} (оценка)"
    return f"{due:%d.%m.%Y}"
