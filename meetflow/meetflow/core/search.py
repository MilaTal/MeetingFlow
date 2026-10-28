"""Поиск по базе проекта — перенесён из Проекта ERP (search_service) и
Планёрки («Сводка по планёркам»).

Не смысловой RAG, а точные совпадения с источником — без пересказа моделью
(решение ERP 11.09: риск дофантазировать, проверки у поиска нет).
Взято из ERP как выверенное хаос-проверками:
- фильтр в Python: SQLite lower()/LIKE кириллицу не понимает;
- «ё» = «е»; даты «17.09.26», «17.09.2026», «2026-09-17» — одна дата,
  сравнение целиком; «31.02.26» — понятный отказ, а не поиск по «31»;
- «№5» — отказ с объяснением: номер свой в каждой таблице;
- служебные слова подсказок не ищутся; запрос из одних подсказок — «нужно
  уточнение», а не выдача всего подряд; одна буква — не запрос;
- выдача по релевантности, при равенстве — более поздняя встреча;
- внутренний номер задачи в сниппетах скрыт.
Исправлено относительно ERP (и согласовано с ответом ERP 03.10.26):
- слово совпадает с начала слова текста, хвост не длиннее трёх букв — и от
  самого слова, и от его основы (text.same_lexeme): «кот» не находится в
  «который», «согласовать» находит «согласовали», «Назаров» — «Назаровой»;
- поиск по сырой речи (расшифровки, записи, дословные цитаты единиц) —
  решение о доступе, а не о технике: ключ темы search.raw_speech, по
  умолчанию выключен, вопрос владельцу тематики выводит `meetflow todo`.
  В ERP владелец отклонил его 03.10.26: поиск открыт всем ролям, а
  сказанное доходит до людей через протокол.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .dates import lenient_date
from .text import same_lexeme, stem

RAW_SPEECH_KINDS = ("transcript", "recording")

SNIPPET = 120
STOP = {w.replace("ё", "е") for w in """было ли упомянуто протокол встречи от по встрече с и в на к о об за для задачи
поставленные ответственным ответственный фио этой задаче есть информация из у а но или не что это как при до без""".split()}
HINTS = ["задачи с ответственным (ФИО)", "в этой задаче есть о ...", "было ли упомянуто", "протокол встречи от",
         "информация о"]
_WORD = re.compile(r"[а-яёa-z0-9]+", re.I)
_FULL = re.compile(r"(?<![\d.])(?:(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})"
                   r"|(?P<dd>\d{1,2})[./](?P<dm>\d{1,2})[./](?P<dy>\d{4}|\d{2}))(?!\d|[./]\d)")
_PART = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?!\d|\.\d)")
_NUM = re.compile(r"^(?:задач\w*\s*)?(?:№|#)\s*(\d{1,9})$|^задач\w*\s+(\d{1,9})$")
_ID_CELL = re.compile(r"(?m)^(\s*\|\s*)№?\d+(\s*\|)")


def norm(t: str) -> str:
    return (t or "").lower().replace("ё", "е")


@dataclass
class Query:
    words: list[str] = field(default_factory=list)
    dates: list[tuple[int, int, int | None]] = field(default_factory=list)
    problem: str | None = None

    @property
    def has_substance(self) -> bool:
        return bool(self.words or self.dates)


def _mkdate(m: re.Match) -> date | None:
    try:
        if m.group("iy"):
            return date(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
        y = int(m.group("dy"))
        return date(y + 2000 if y < 100 else y, int(m.group("dm")), int(m.group("dd")))
    except ValueError:
        return None


def is_hint_only(q: str) -> bool:
    ws = [w.lower() for w in _WORD.findall(re.sub(r"\([^)]*\)|\.{2,}", " ", q or ""))]
    if not ws:
        return False
    for h in HINTS:
        hw = [w.lower() for w in _WORD.findall(re.sub(r"\([^)]*\)|\.{2,}", " ", h))]
        if ws == hw[:len(ws)]:
            return True
    return False


def parse(q: str) -> Query:
    s = norm((q or "").strip())
    if _NUM.match(s):
        return Query(problem="Номер задачи свой в каждой таблице, по порядку с 1 — по нему не найти. "
                             "Ищите по словам из задачи или по ответственному.")
    if is_hint_only(q):
        return Query(problem="Допишите, что искать: подсказка — только начало запроса.")
    dates, bad = [], []

    def full(m):
        d = _mkdate(m)
        (dates.append((d.day, d.month, d.year)) if d else bad.append(m.group(0)))
        return " "

    def part(m):
        dd, mm = int(m.group(1)), int(m.group(2))
        try:
            date(2024, mm, dd)          # високосный год: 29.02 допустим
            dates.append((dd, mm, None))
        except ValueError:
            bad.append(m.group(0))
        return " "
    rest = _PART.sub(part, _FULL.sub(full, s))
    ws = [w for w in _WORD.findall(rest) if w not in STOP and (len(w) > 1 or w.isdigit())]
    problem = f"Даты «{bad[0]}» не бывает — проверьте число и месяц." if bad and not dates else None
    if not ws and not dates and not problem:
        problem = "Запрос пустой: допишите слово, имя или дату."
    return Query(ws, dates, problem)


def _tokens(tn: str) -> list[str]:
    return _WORD.findall(tn)


def _word_hit(tokens: list[str], w: str) -> int:
    """0 — нет; 2 — слово целиком; 1 — то же слово в другой форме (с начала
    слова, хвост ≤ 3 букв). Числа — только целиком."""
    if w.isdigit():
        return 2 if w in tokens else 0
    if w in tokens:
        return 2
    # прежнее правило (same_word: хвост — только падежное окончание) теряло
    # глаголы: «согласовать» не находило «согласовали» — найдено тестом 03.10.26
    return 1 if any(same_lexeme(t, w) for t in tokens) else 0


def _dates_in(text: str) -> list[date]:
    return [d for m in _FULL.finditer(text or "") if (d := _mkdate(m))]


def _date_ok(d: date, q) -> bool:
    return d.day == q[0] and d.month == q[1] and (q[2] is None or d.year == q[2])


def score(text: str, meeting_date: str | None, q: Query) -> int | None:
    tn = norm(_ID_CELL.sub(lambda m: m.group(1) + m.group(2), text or ""))
    toks = _tokens(tn)
    hits = [_word_hit(toks, w) for w in q.words]
    if not all(hits):
        return None
    s = sum(100 if h == 2 else 50 for h in hits)
    if len(q.words) > 1 and " ".join(q.words) in " ".join(toks):
        s += 300
    if q.dates:
        md = lenient_date(meeting_date)
        if md and all(_date_ok(md, d) for d in q.dates):
            s += 1000
        elif all(any(_date_ok(x, d) for x in _dates_in(text)) for d in q.dates):
            s += 500
        else:
            return None
    return s


def snippet(text: str, q: Query) -> str:
    lines = []
    for ln in (text or "").splitlines():
        st = ln.strip()
        if re.match(r"^\|?[\s:|-]+\|?$", st) and "-" in st:
            continue
        if st.startswith("|") and st.endswith("|"):
            st = " — ".join(c.strip() for c in st.strip("|").split("|") if c.strip() and not re.fullmatch(r"№?\s?\d+", c.strip()))
        lines.append(re.sub(r"^#{1,4}\s*|\*", "", st))
    clean = "\n".join(lines)
    low = norm(clean)
    for w in q.words:
        m = re.search(rf"(?<![а-яеa-z0-9]){re.escape(stem(w) if not w.isdigit() else w)}", low)
        if m:
            a, b = max(0, m.start() - SNIPPET), min(len(clean), m.end() + SNIPPET)
            return ("…" if a else "") + clean[a:b].strip() + ("…" if b < len(clean) else "")
    return clean[:SNIPPET * 2].strip()


def search(store, project_id: int, query: str, limit: int = 50, raw_speech: bool = False) -> dict:
    q = parse(query)
    if q.problem or not q.has_substance:
        return {"problem": q.problem or "Нечего искать.", "results": []}
    res = []

    def add(kind, ref, mdate, text, s, title):
        res.append({"type": kind, "id": ref, "meeting_date": mdate, "title": title, "snippet": snippet(text, q),
                    "_s": s})
    from .tablica_zadach import без_снятых, задачи_для_скрытия
    _dropped, _alive = задачи_для_скрытия(store, project_id)        # проект с подпроектами (27.10.2026)

    def shown_md(md):
        return без_снятых(md, _dropped, _alive)
    for m in store.q("SELECT id, date, label, protocol_md FROM meetings WHERE deleted_at IS NULL AND project_id=? AND protocol_md IS NOT NULL",
                     (project_id,)):
        m = {**m, "protocol_md": shown_md(m["protocol_md"])}     # строки снятых задач не ищутся (26.10.2026)
        s = score(m["protocol_md"], m["date"], q)
        if s is not None:
            add("protocol", m["id"], m["date"], m["protocol_md"], s, "Протокол")
    for src in store.q("SELECT s.id, s.name, s.kind, s.text, s.meeting_id, m.date FROM sources s JOIN meetings m "
                       "ON m.id = s.meeting_id WHERE m.project_id=? AND s.removed_at IS NULL", (project_id,)):
        if not raw_speech and src["kind"] in RAW_SPEECH_KINDS:
            continue
        s = score(src["text"], src["date"], q)
        if s is not None:
            add("source", src["meeting_id"], src["date"], src["text"], s - 10, f"Источник: {src['name']}")
    # снятые задачи в поиске не показываются (решение владелицы 26.10.2026, как ERP)
    for t in store.q("SELECT t.*, m.date AS mdate FROM tasks t LEFT JOIN meetings m ON m.id = t.source_meeting_id "
                     "WHERE t.project_id=? AND t.status<>'dropped'", (project_id,)):
        best = None
        for text in (t["assignee"] or "", t["description"] or "", t["last_comment"] or ""):
            s = score(text, t["mdate"], q) if text else None
            best = s if s is not None and (best is None or s > best) else best
        if best is not None:
            st = {"active": "в работе", "done": "выполнено"}.get(t["status"], t["status"])
            add("task", t["id"], t["mdate"], f"{t['description']} — {t['assignee'] or 'не назначен'} — {st}",
                best + 20, "Задача")
    for u in store.q("SELECT u.*, m.date AS mdate FROM units u JOIN meetings m ON m.id = u.meeting_id "
                     "WHERE u.project_id=? AND u.status != 'removed'", (project_id,)):
        # формулировка единицы — пересказ, её видно в протоколе; дословная цитата — сырая речь
        s = score(f"{u['text']}\n{u['quote']}" if raw_speech else u["text"], u["mdate"], q)
        if s is not None:
            add("unit", u["meeting_id"], u["mdate"], u["text"], s, "Из записи встречи")
    res.sort(key=lambda r: (r["_s"], r["meeting_date"] or ""), reverse=True)
    for r in res:
        del r["_s"]
    return {"problem": None, "results": res[:limit], "total": len(res)}
