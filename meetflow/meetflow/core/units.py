"""Единицы встречи: решения, договорённости, уточнения, открытые вопросы,
вехи и пропущенные задачи — с цитатой, местом в записи, ролями людей,
открытием и закрытием. Перенесено из Проекта ERP (units_extract, 02.10.26).

Взято из ERP как доказавшее себя:
- строки нумеруются, модель отвечает номерами, цитату берёт код;
- куски по времени (~6 мин с перекрытием 1 мин), без таймкодов — по 60
  строк; длинная строка режется по предложениям (одна строка в 76 тыс.
  знаков давала 0 единиц);
- фраза короче 4 слов не единица («Получилось.» не называет предмет);
- роль человека — только с опорой в тексте рядом с цитатой (из 92 ролей
  опору имели 19: модель вписывала участниками всех присутствующих);
- закрытие по голосу сразу, «Вернуть» — после; уточнение и вопрос к задаче
  закрываются вместе с задачей; разовое решение с прошедшей датой — закрыто.
  Последние два — вычисляются при чтении, база при показе не меняется.

Исправлено относительно ERP (см. «Рекомендации для Проекта ERP» и ответ
ERP 03.10.26 «решения по рекомендациям»):
1. Задача из единицы проходит общий TaskGate (Команда, цитата, вопрос,
   отрицание, дубль), а не заводится в реестр напрямую; не прошедшая —
   карточка. Проверки стоят на любом пути заведения задачи.
2. Одна и та же мысль склеивается уже при извлечении (same_point: одна
   формулировка покрывает другую с точностью до формы слова), а не по порогу
   Жаккара — порог склеивал «отчёт 1» и «отчёт 2», замер в тестах.
3. Сбой одного куска не стирает прежние единицы этого куска.
4. Одна фраза закрывает не больше одной единицы.
5. Решение и договорённость закрываются только заменой или отменой:
   «подтвердили» — не закрытие (замер ERP: 8 из 10 ложных закрытий).
6. Закрытие внутри своей встречи — только если тема включила
   units.close_same_meeting (по умолчанию нет, до замера).
7. Проверка «не итог» — вопрос, условие, намерение и только будущее время
   («обсудим», «посмотрим»); «обсудили и решили» — итог.
8. Тематика (раньше «проект внедрения 1С:ERP» в промпте) — из темы; данные
   встречи огорожены метками (security.fence).
9. Дата события раньше встречи или дальше года — сбрасывается.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .dates import lenient_date
from ..connectors.base import AnswerTruncated
from .negation import NegationRule
from .people import Team
from .security import DATA_NOT_INSTRUCTIONS, fence
from .text import content_words, same_lexeme, same_word, words
from .types import TaskDraft

KIND_RU = {"decision": "Решение", "agreement": "Договорённость", "clarification": "Уточнение",
           "open_question": "Открытый вопрос", "milestone": "Веха", "task": "Задача"}
RU_KIND = {v.lower(): k for k, v in KIND_RU.items()}
OPEN = ("open", "active")
DATED = ("decision", "agreement")
CLOSABLE = ("open_question", "decision", "agreement")
BY_TASK = ("clarification", "open_question")
CHUNK_SECONDS, OVERLAP_SECONDS = 360, 60
CHUNK_LINES, OVERLAP_LINES = 60, 10
LONG_LINE, PIECE = 600, 300
MIN_QUOTE_WORDS = 4
_TS = re.compile(r"^\s*\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?")
_TS_STRIP = re.compile(r"^\s*\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*")
_SPEAKER = re.compile(r"^\s*(говорящий|спикер|speaker|участник)\s*\d*\s*$", re.I)
_PRONOUNS = {"вы", "мы", "все", "они", "он", "она", "я", "ты", "команда", "коллеги"}
_NUM_PREFIX = re.compile(r"^(?:задач[аи]\s*)?(?:№|T)\s*\d+\s*(?:\(([^)]*)\))?\s*[—–:-]?\s*", re.I)
# Только будущее и неопределённость: «обсудили / посмотрели» — это итог, «обсудим / посмотрим» — нет.
# В ERP «обсуд\w*» ловил и прошедшее время, и «Обсудили и решили: …» не закрывало вопрос (найдено тестом).
_NOT_RESOLVED = re.compile(r"\b(подумаем|подумать|обсудим|обсудить|обсуждаем|посмотрим|посмотреть|не знаю|не реш\w*|"
                           r"пока не|позже|потом реш\w*|надо бы|не определ\w*|не понятно|непонятно)\b", re.I)

KINDS_TEXT = """Виды единиц:
- Решение — принятое решение («решили», «делаем так»);
- Договорённость — правило работы, о котором условились;
- Уточнение — уточнение к уже поставленной задаче: сроки, состав, кто именно;
- Открытый вопрос — вопрос подняли и не решили;
- Веха — факт достижения этапа или плановая дата этапа;
- Задача — поручение конкретного действия."""

ANSWER_TEXT = """Для каждой единицы верни:
- "kind" — вид из списка (по-русски);
- "statement" — одной фразой своими словами, без номера задачи;
- "lines" — номера строк L, где это прозвучало (1–3 номера, только из куска);
- "responsible", "participants", "influencers" — имена, ПРОЗВУЧАВШИЕ в тексте. «Говорящий N» — не имя;
- "task" — ссылка T… из списка открытых задач, если единица к ней относится, иначе "";
- "date" — ДД.ММ.ГГГГ только для разового решения или договорённости с датой, иначе "".
Бери только то, что прозвучало. Ничего значимого — пустой список. Ответ — JSON: {"items": [...]}."""


@dataclass
class Line:
    n: int          # сквозной номер для модели
    src: int        # номер строки в источнике (0-based)
    secs: int | None
    text: str

    @property
    def ts(self) -> str | None:
        return None if self.secs is None else f"{self.secs // 3600:02d}:{self.secs % 3600 // 60:02d}:{self.secs % 60:02d}"


def _pieces(line: str) -> list[str]:
    if len(line) <= LONG_LINE:
        return [line]
    sents: list[str] = []
    for s in re.split(r"(?<=[.!?…])\s+", line):
        while len(s) > PIECE * 2:
            cut = s.rfind(" ", 0, PIECE)
            cut = cut if cut > 0 else PIECE
            sents.append(s[:cut])
            s = s[cut:].strip()
        if s:
            sents.append(s)
    out, cur = [], ""
    for s in sents:
        if cur and len(cur) + 1 + len(s) > PIECE:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    return out + ([cur] if cur else [])


def numbered(text: str) -> list[Line]:
    out: list[Line] = []
    for i, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        m = _TS.match(raw)
        secs = None
        if m:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m.group(3) \
                else int(m.group(1)) * 60 + int(m.group(2))
        for piece in _pieces(raw.strip()):
            out.append(Line(len(out) + 1, i, secs, piece))
    return out


def chunk(lines: list[Line]) -> list[list[Line]]:
    timed = [ln for ln in lines if ln.secs is not None]
    if len(timed) >= max(10, len(lines) // 2):
        end, start, out = max(ln.secs for ln in timed), 0, []
        while start <= end:
            part = [ln for ln in timed if start - OVERLAP_SECONDS <= ln.secs < start + CHUNK_SECONDS]
            if part:
                out.append(part)
            start += CHUNK_SECONDS
        return out
    out = []
    for i in range(0, len(lines), CHUNK_LINES - OVERLAP_LINES):
        out.append(lines[i:i + CHUNK_LINES])
        if i + CHUNK_LINES >= len(lines):
            break
    return [p for p in out if p]


def _render(part: list[Line]) -> str:
    return "\n".join(f"L{ln.n}: {ln.text}" for ln in part)


def _quote(rows: list[Line]) -> str:
    return " ".join(_TS_STRIP.sub("", r.text) for r in rows)


def named_in(text: str, person: str) -> bool:
    """Назван ли человек в тексте: любое слово имени — тем же словом в
    другом падеже (core.text.same_word), а не по первым 5 буквам."""
    tw = words(text)
    for pw in words(person):
        if len(pw) < 3:
            continue
        if any(w == pw or same_word(w, pw) for w in tw):
            return True
    return False


# Решение и договорённость закрываются только заменой или отменой. Замер ERP
# 03.10.26 (53 единицы, слепая разметка): 8 из 10 закрытий по голосу были
# «подтвердили» вместо «закрыли» — подтверждение решение не закрывает.
_CHANGE = re.compile(r"\b(отмен\w*|замен\w*|вместо|передума\w*|теперь|перенес\w*|перенос\w*|больше не|не будем|"
                     r"изменил\w*|изменен\w*|изменён\w*|по-другому|иначе)\b", re.I)


def changes_decision(phrase: str) -> bool:
    return bool(_CHANGE.search(phrase))


def not_resolved(phrase: str, neg: NegationRule) -> bool:
    v = neg.check(phrase)
    return bool({"question", "condition", "intent"} & set(v.blockers)) or bool(_NOT_RESOLVED.search(phrase))


def _event_date(value: Any, kind: str, meeting_date: date | None) -> str | None:
    """Дата разового события — только у решения и договорённости; код
    проверяет правдоподобие: не раньше встречи и не дальше года."""
    if kind not in DATED:
        return None
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", str(value or ""))
    if not m:
        return None
    try:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    if meeting_date and not (meeting_date <= d <= date(meeting_date.year + 1, meeting_date.month, 28)):
        return None
    return d.isoformat()


@dataclass
class Extracted:
    kind: str
    text: str
    nums: list[int]
    quote: str
    line_from: int
    line_to: int
    ts: str | None
    task_id: int | None
    date: str | None
    roles: list[dict] = field(default_factory=list)
    how: str = "куски"


def parse_items(items: Any, by_n: dict[int, Line], team: Team, open_tasks: dict[int, str],
                meeting_date: date | None, how: str) -> list[Extracted]:
    out: list[Extracted] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        kind = RU_KIND.get(str(it.get("kind") or "").strip().lower())
        if not kind:
            continue
        nums = sorted({int(m.group()) for x in (it.get("lines") or [])
                       for m in [re.search(r"\d+", str(x))] if m and int(m.group()) in by_n})[:3]
        if not nums:
            continue                       # без строки источника единицы нет
        rows = [by_n[n] for n in nums]
        quote = _quote(rows)
        if len(words(quote)) < MIN_QUOTE_WORDS:
            continue
        m = re.search(r"\d+", str(it.get("task") or ""))
        task_id = int(m.group()) if m and int(m.group()) in open_tasks else None
        text = _NUM_PREFIX.sub(lambda mm: (mm.group(1) + ": ") if mm.group(1) else "", str(it.get("statement") or "").strip())
        text = re.sub(r"\s*(№|T)\s*\d+", "", text).strip(" —-:")[:1000] or quote[:300]
        near = " ".join(by_n[k].text for k in range(nums[0] - 3, nums[-1] + 4) if k in by_n)
        roles = []
        for role, key in (("ответственный", "responsible"), ("участник", "participants"), ("влияющий", "influencers")):
            vals = it.get(key) or []
            for v in vals if isinstance(vals, list) else [vals]:
                name = " ".join(str(v).split()).strip(" .,;")[:120]
                if not name or _SPEAKER.match(name) or name.lower() in _PRONOUNS:
                    continue
                grounded = named_in(near, name) or (role == "ответственный" and task_id is not None
                                                    and named_in(open_tasks.get(task_id, ""), name))
                if grounded:
                    p = team.find(name).person
                    roles.append({"role": role, "person": p.full_name if p else name, "in_team": bool(p)})
        out.append(Extracted(kind, text, nums, quote[:1500], rows[0].src, rows[-1].src, rows[0].ts, task_id,
                             _event_date(it.get("date"), kind, meeting_date), roles, how))
    return out


def same_point(a: str, b: str) -> bool:
    """Одна и та же мысль: одна формулировка покрывает другую целиком (с
    точностью до формы слова), и на общие слова приходится ≥ 0,6.

    Почему не Жаккар с порогом. Замер 03.10.26 на парах с известным ответом
    (tests: test_merge_known_pairs): «отчёт номер 1 / номер 2» и «регламент
    приёмки / отгрузки» одного человека — 0,67 и по основам, и по словам от
    трёх букв (формула ответа ERP), то есть склеились бы; настоящий дубль с
    другими падежами — 0,33, не склеился бы. Различие пунктов — в слове,
    которое есть у каждой стороны своё; если такое слово есть с обеих
    сторон, это два пункта. Цена: пересказ другими словами не склеивается —
    лишний пункт лучше потерянного (вывод ERP)."""
    wa, wb = content_words(a), content_words(b)
    if min(len(wa), len(wb)) < 3:
        return False
    only_a = [w for w in wa if not any(same_lexeme(w, x) for x in wb)]
    only_b = [w for w in wb if not any(same_lexeme(w, x) for x in wa)]
    if only_a and only_b:
        return False
    common = len(wa) - len(only_a)
    return common / (common + len(only_a) + len(only_b)) >= 0.6


def merge(found: list[Extracted]) -> list[Extracted]:
    """Одна строка — одна единица; одна и та же мысль того же вида — одна
    (same_point). Правило ERP _distinct «60 % у более короткой» сливало
    «спецификация на шкаф» и «на стол»."""
    out: list[Extracted] = []
    for it in sorted(found, key=lambda x: (x.task_id is None,)):
        dup = any(set(it.nums) & set(o.nums) or (it.kind == o.kind and same_point(it.text, o.text)) for o in out)
        if not dup:
            out.append(it)
    return out


def effective(u: dict, task_status: dict[int, str], today: date | None = None) -> tuple[str, str]:
    """(статус, пояснение) с учётом задачи и даты; база не меняется."""
    today = today or date.today()
    st = u["status"]
    if st not in OPEN:
        return st, u.get("closed_note") or ""
    if u["kind"] in BY_TASK and u.get("task_id") and task_status.get(u["task_id"]) in ("done", "dropped"):
        return "closed", "задача выполнена" if task_status[u["task_id"]] == "done" else "задача снята"
    if u["kind"] in DATED and u.get("planned_date") and u["planned_date"] < today.isoformat():
        return "closed", f"дата прошла {u['planned_date']}"
    return st, ""


def initial_status(kind: str) -> str:
    return "active" if kind in DATED else "open"


class UnitsExtractor:
    """Вызывается конвейером внутри общего бюджета прогона."""

    def __init__(self, pipe, team: Team, gate):
        self.pipe, self.team, self.gate = pipe, team, gate

    def _head(self, meeting_date: str, listing: str) -> str:
        role = self.pipe.theme.get("prompts.domain_role", "")
        return (f"{role}\nТы извлекаешь из КУСКА записи рабочей встречи {meeting_date} значимые ЕДИНИЦЫ.\n"
                f"{KINDS_TEXT}\n{ANSWER_TEXT}\n\nОткрытые задачи (справка, не источник фактов):\n{listing}\n\n"
                f"{DATA_NOT_INSTRUCTIONS}")

    def run(self, project_id: int, meeting: dict, source, budget, existing_tasks) -> dict:
        lines = numbered(source.text)
        by_n = {ln.n: ln for ln in lines}
        md = meeting.get("date")
        mdate = lenient_date(md)
        active = [t for t in self.pipe.reg.list(project_id)]
        open_tasks = {t["id"]: f"{t['description']} — {t['assignee'] or 'не назначен'}" for t in active}
        listing = "\n".join(f"T{tid}: {txt}" for tid, txt in open_tasks.items()) or "(открытых задач нет)"
        found: list[Extracted] = []
        failed_ranges: list[tuple[int, int]] = []
        parts = chunk(lines)
        for part in parts:
            body, _ = fence(_render(part), "кусок записи, строки пронумерованы")
            try:
                out = self.pipe._call(self.pipe.gen, budget, "units", self._head(md or "", listing), body,
                                      meeting["id"])
                found += parse_items(out.get("items") if isinstance(out, dict) else None, by_n, self.team,
                                     open_tasks, mdate, "куски")
            except (ValueError, json.JSONDecodeError, AnswerTruncated):
                failed_ranges.append((part[0].src, part[-1].src))   # кусок пропущен — прежнее не стираем
        # виды единиц — из темы units.kinds (письмо 47: список был, но никем не читался)
        allowed = set(self.pipe.theme.get("units.kinds") or KIND_RU)
        units = merge([u for u in found if u.kind in allowed])

        # задачи из единиц — через общие проверки и не дублируя реестр
        tasks, held = [], []
        for u in [u for u in units if u.kind == "task" and not u.task_id]:
            who = next((r["person"] for r in u.roles if r["role"] == "ответственный"), None)
            g = self.gate.check(TaskDraft(u.text, who, quote=u.quote), source, existing_tasks)
            (tasks if g.accepted else held).append((u, g))
        units = [u for u in units if u.kind != "task"]

        closings = self._close_by_voice(project_id, meeting, lines, by_n, units, budget)
        return {"units": units, "tasks": tasks, "held": held, "closings": closings, "failed_ranges": failed_ranges,
                "chunks": len(parts)}

    def _close_by_voice(self, project_id: int, meeting: dict, lines, by_n, new_units, budget) -> list[dict]:
        """Закрыть открытые единицы прошлых встреч и вопросы этой встречи,
        на которые ответили позже в той же записи. Одна фраза — одна единица."""
        prev = self.pipe.s.q("SELECT u.* FROM units u JOIN meetings m ON m.id = u.meeting_id "
                             "WHERE u.project_id=? AND u.status IN ('open','active') AND u.kind IN "
                             "('open_question','decision','agreement') AND m.date < ?",
                             (project_id, meeting.get("date") or "9999"))
        refs = {f"U{u['id']}": ("db", u) for u in prev}
        # Закрытие внутри своей встречи — по теме, по умолчанию выключено: неточный
        # механизм не расширяют, пока он не прошёл замер (ERP 03.10.26, п. 5)
        if self.pipe.theme.get("units.close_same_meeting", False):
            for i, u in enumerate(new_units):
                if u.kind in CLOSABLE:
                    refs[f"N{i}"] = ("new", u)
        if not refs:
            return []
        listing = "\n".join(f"{r}: [{KIND_RU[(v[1]['kind'] if v[0] == 'db' else v[1].kind)]}] "
                            f"{v[1]['text'] if v[0] == 'db' else v[1].text}" for r, v in refs.items())
        head = (f"{self.pipe.theme.get('prompts.domain_role', '')}\nНиже — ОТКРЫТЫЕ пункты. Найди пункты, которые "
                "закрывает эта запись: на вопрос дан ответ; решение или договорённость заменены или отменены. Только "
                "если это прямо сказано. Обсуждение без итога, новый вопрос, намерение — НЕ закрывают. "
                "Подтверждение прежнего решения («подтвердили», «в силе») — НЕ закрытие.\n"
                'Ответ — JSON: {"closed": [{"unit": "U12", "lines": [до 3 номеров], "how": "закрыт|заменён", '
                '"answer": "чем закрыт, 5–6 слов"}]}.\n\nОткрытые пункты (справка):\n' + listing +
                f"\n\n{DATA_NOT_INSTRUCTIONS}")
        body, _ = fence(_render(lines), "запись встречи, строки пронумерованы")
        try:
            out = self.pipe._call(self.pipe.gen, budget, "units_close", head, body, meeting["id"])
        except (ValueError, json.JSONDecodeError, AnswerTruncated):
            return []
        result, used_lines = [], set()
        for it in (out.get("closed") if isinstance(out, dict) and isinstance(out.get("closed"), list) else []):
            if not isinstance(it, dict) or str(it.get("unit")) not in refs:
                continue
            nums = sorted({int(m.group()) for x in (it.get("lines") or []) for m in [re.search(r"\d+", str(x))]
                           if m and int(m.group()) in by_n})[:3]
            if not nums or used_lines & set(nums):
                continue                   # одна фраза закрывает только одну единицу
            src, unit = refs[str(it["unit"])]
            if src == "new" and nums[0] <= max(unit.nums):
                continue                   # ответ должен прозвучать после вопроса
            quote = _quote([by_n[n] for n in nums])
            if len(words(quote)) < MIN_QUOTE_WORDS or not_resolved(quote, self.pipe.neg):
                continue
            kind = unit["kind"] if src == "db" else unit.kind
            if kind in DATED and not changes_decision(quote):
                continue                   # подтверждение решения ≠ закрытие
            used_lines |= set(nums)
            result.append({"ref": str(it["unit"]), "src": src, "unit": unit, "quote": quote[:1500],
                           "how": "replaced" if str(it.get("how") or "").startswith("замен") else "closed",
                           "note": " ".join(str(it.get("answer") or "").split())[:300]})
        return result


def apply(store, project_id: int, meeting_id: int, res: dict, now_s: str) -> dict:
    """Запись результата в базу (внутри транзакции конвейера). Прежние
    авто-единицы встречи заменяются, кроме решённых человеком, закрытых и
    попавших в пропущенные куски."""
    mine = store.q("SELECT * FROM units WHERE meeting_id=?", (meeting_id,))
    failed = res["failed_ranges"]

    def in_failed(u):
        return any(a <= (u["line_from"] or 0) <= b for a, b in failed)
    keep_lines = set()
    for u in mine:
        if u["decided_by"] or u["closed_how"] or in_failed(u):
            keep_lines |= set(range(u["line_from"] or 0, (u["line_to"] or 0) + 1))
            continue
        store.delete("units", u["id"])
    added = 0
    new_ids: dict[int, int] = {}
    for i, u in enumerate(res["units"]):
        if any(ln in keep_lines for ln in range(u.line_from, u.line_to + 1)):
            continue
        new_ids[i] = store.insert("units", project_id=project_id, meeting_id=meeting_id, kind=u.kind, text=u.text,
                                  quote=u.quote, status=initial_status(u.kind), task_id=u.task_id,
                                  line_from=u.line_from, line_to=u.line_to, ts=u.ts, planned_date=u.date,
                                  roles=u.roles, extracted_by=u.how, created_at=now_s, updated_at=now_s)
        added += 1
    closed = 0
    for c in res["closings"]:
        uid = c["unit"]["id"] if c["src"] == "db" else new_ids.get(int(c["ref"][1:]))
        if uid is None:
            continue
        row = store.get("units", uid)
        if row and row["status"] in OPEN:
            store.update("units", uid, prev_status=row["status"], status=c["how"], closed_meeting_id=meeting_id,
                         closed_quote=c["quote"], closed_note=c["note"], closed_how="голос", updated_at=now_s)
            closed += 1
    return {"added": added, "closed": closed}


def reopen(store, unit_id: int, by: str) -> dict | None:
    u = store.get("units", unit_id)
    if not u:
        return None
    status = u["prev_status"] if u["prev_status"] in OPEN else initial_status(u["kind"])
    store.update("units", unit_id, status=status, closed_meeting_id=None, closed_quote="", closed_note="",
                 closed_how="", prev_status="", decided_by=by, updated_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    return store.get("units", unit_id)


def remove(store, unit_id: int, by: str) -> dict | None:
    u = store.get("units", unit_id)
    if not u:
        return None
    store.update("units", unit_id, prev_status=u["status"], status="removed", closed_how="человек",
                 closed_note="убрано вручную", decided_by=by, updated_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    return store.get("units", unit_id)
