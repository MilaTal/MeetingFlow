"""Конвейер встречи: источник -> задачи -> закрытия -> протокол -> проверка.

Паттерн SEQUENTIAL с валидаторами кодом между шагами и ROUTER по виду
источника (курс, занятие 6). Решения владельцев, ставшие порядком шагов:
- протокол формируется и сохраняется сразу, проверка — после факта, право
  оператора, а не шлюз (24.09);
- все действия копятся и применяются одной транзакцией в конце: остановка
  по пределу или сбой не оставляют полупримененного реестра;
- один прогон на встречу за раз (замок на данных, а не на кнопке);
- повторный прогон той же встречи не плодит задач и карточек;
- одна фраза не закрывает несколько задач («Получилось.» закрыло 4 задачи);
- закрыть задачу можно только фразой из кандидатов, отобранных кодом;
- задача не закрывается фразой собственной постановки;
- заметки — акцент, а не предел: основа — расшифровка, заметки идут отдельно
  с пометкой; есть только заметки или иной текст — работаем по ним (26.09, 29.09).
"""
from __future__ import annotations

import inspect
import json
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from ..connectors.base import (AnswerTruncated, ASRConnector, ConnectorError, LLMConnector, SourceConnector,
                               VisionConnector)
from ..connectors.registry import PluginRegistry
from .budget import BudgetExceeded, BudgetLimits, CallJournal, RunBudget
from .config import Theme
from .gates import GateConfig, TaskGate
from .negation import NegationRule
from .people import Team
from .prompts import PromptBuilder, chunks, parse_json, profile
from .registry import CardQueue, OperatorMemory, TaskRegistry
from .dates import lenient_date
from .draft_checks import run_code_checks
from .morph import supported_due
from .security import injection_hits, looks_like_injection
from .store import Store, now
from .text import coverage, jaccard, same_word, stems, words
from .units import UnitsExtractor
from .units import apply as apply_units
from .types import Person, SourceDoc, SourceKind, TaskDraft, TaskStatus


@dataclass
class RunReport:
    meeting_id: int
    status: str = "ok"          # ok | stopped_by_limit | no_sources | error | busy
    detail: str = ""
    tasks_added: int = 0
    tasks_held: int = 0
    tasks_closed: int = 0
    tasks_dropped: int = 0
    due_dropped: int = 0        # срок от модели, которого во встрече не было
    closing_cards: int = 0
    skipped_by_rule: int = 0
    units_added: int = 0
    units_closed: int = 0
    units_tasks: int = 0
    findings: list[dict] = field(default_factory=list)
    calls: int = 0
    cost_usd: float = 0.0
    protocol_saved: bool = False


HIDDEN = "[строка скрыта: похожа на инструкцию для модели]"


def _takes_deadline(llm) -> bool:
    """Сторонний коннектор мог не знать про deadline — тогда без него."""
    try:
        ps = inspect.signature(llm.complete).parameters
    except (TypeError, ValueError):
        return False
    return "deadline" in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())


def _cell(text: str) -> str:
    """Ячейка таблицы протокола: «|» экранируется, а не подменяется на «/»,
    перевод строки — пробел; текст протокола совпадает с реестром (01/23)."""
    return " ".join(str(text or "").replace("\\", "\\\\").replace("|", "\\|").split())


class ShapeError(ValueError):
    """Ответ модели не той формы (вместо списка — число и т. п.)."""


def _list(out: Any, key: str) -> list:
    if not isinstance(out, dict):
        raise ShapeError(f"ответ модели не объект, а {type(out).__name__}")
    v = out.get(key, [])
    if not isinstance(v, list):
        raise ShapeError(f"поле «{key}» должно быть списком")
    return v


def _dict(out: Any, key: str) -> dict:
    if not isinstance(out, dict):
        raise ShapeError(f"ответ модели не объект, а {type(out).__name__}")
    v = out.get(key, {})
    if not isinstance(v, dict):
        raise ShapeError(f"поле «{key}» должно быть объектом")
    return v


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def noise_duplicate(reasons: list[str], unit_text: str, added_descriptions: list[str]) -> bool:
    """D4 (прогон 09.10.26): единица встречи отклонена только как дубль задачи, которую завёл этот же прогон, —
    задача не потеряна, карточка «не заведена» была бы ложной тревогой. Дубль старой задачи — по-прежнему карточка."""
    if set(reasons or []) != {"duplicate"}:
        return False
    # D7 (цикл 2): срок бывает в тексте единицы («паллеты к 20.10») и не бывает в описании задачи, или наоборот
    # («опалубку до 7 октября») — даты из сравнения убираются; номера («акт номер 0» и «1») обязаны совпасть
    mine = set(stems(_without_dates(unit_text)))

    def same(d: str) -> bool:
        theirs = set(stems(_without_dates(d)))
        if {t for t in theirs if t.isdigit()} != {t for t in mine if t.isdigit()}:
            return False
        return max(coverage(mine, theirs), coverage(theirs, mine)) >= 0.7
    return bool(mine) and any(same(d) for d in added_descriptions if d)


_DATE_IN_TEXT = re.compile(
    r"\b(?:до|к|ко|по|на)?\s*(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}(?:\.\d{2,4})?"
    r"|\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*(?:\s+\d{4})?)",
    re.IGNORECASE)


def _without_dates(text: str) -> str:
    return _DATE_IN_TEXT.sub(" ", text or "")

class MeetingPipeline:
    _locks: dict[tuple[int, int], threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, theme: Theme, store: Store, plugins: PluginRegistry,
                 generator: LLMConnector, verifier: LLMConnector | None = None,
                 journal_path: str | Path | None = None):
        self.theme, self.s, self.plugins = theme, store, plugins
        self.gen, self.ver = generator, verifier or generator
        self.neg = NegationRule(theme.get("lexicon"), theme.get("lexicon_done"))
        self.reg = TaskRegistry(store, self.neg)
        self.cards = CardQueue(store)
        self.memory = OperatorMemory(store, theme.get("operator.confirmations", 2))
        self.journal = CallJournal(journal_path)
        self.prof = profile(getattr(generator, "profile", "generic"))
        self.pb = PromptBuilder(theme.get("prompts.domain_role", ""), self.prof)
        self._configure_connectors()

    @property
    def tool_info(self) -> dict:
        """Где обработана встреча: инструмент подключения и модели (письмо meeting-registry 17, п. 4)."""
        return {"llm_tool": getattr(self.gen, "name", ""), "generator": getattr(self.gen, "model", ""),
                "verifier": getattr(self.ver, "model", "")}

    @property
    def stand(self) -> bool:
        """Стенд без модели: протокол собран заглушкой (01/19) — видно в протоколе,
        на экране и в журнале; такие прогоны не идут в стоимость успешного."""
        return getattr(self.gen, "name", "") == "mock"

    def _configure_connectors(self) -> None:
        """Ключи темы, которые раньше никто не читал (находка ревью)."""
        self.plugins.load_extra(self.theme.get("connectors.extra", []) or [])
        for c in self.plugins.all("asr"):
            if hasattr(c, "duration_min"):
                c.duration_min = self.theme.get("intake.duration_min")
                c.duration_max = self.theme.get("intake.duration_max")
                c.keep_media = bool(self.theme.get("asr.keep_media", False))
                # модель и язык распознавания — из темы; раньше подключение работало на своих умолчаниях (письмо 47)
                if self.theme.get("asr.model") and hasattr(c, "model_name"):
                    c.model_name = self.theme.get("asr.model")
                if self.theme.get("asr.language") and hasattr(c, "language"):
                    c.language = self.theme.get("asr.language")
        for c in self.plugins.all("vision"):
            if self.theme.get("llm.vision.model") and hasattr(c, "model"):
                c.model = self.theme.get("llm.vision.model")
        mb = int(self.theme.get("intake.max_text_mb", 20))
        for c in self.plugins.all("source"):
            c.max_bytes = mb * 2 ** 20
            if hasattr(c, "notes_markers"):
                c.notes_markers = list(self.theme.get("notes_markers", []))
                c.own_output_markers = list(self.theme.get("own_output_markers", [])) + [self.theme.word("sources_line")]

    def _meeting_lock(self, meeting_id: int) -> threading.Lock:
        key = (id(self.s), meeting_id)
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    # ---------------------------------------------------------------- приём
    def ingest(self, project_id: int, meeting_id: int, filename: str, data: bytes | None = None,
               path: Path | None = None) -> dict:
        """Ручная загрузка / папка-приёмник. Возвращает {"status", ...}."""
        c = self.plugins.resolve_source(filename)
        if c is None:
            return {"status": "rejected", "reason": f"Формат файла «{filename}» не поддерживается."}
        try:
            if isinstance(c, ASRConnector):
                if path is None:
                    return {"status": "rejected", "reason": "Для записи нужен путь к файлу."}
                doc = c.transcribe(path)
            elif isinstance(c, VisionConnector):
                doc = c.describe(data or b"", filename)
            else:
                assert isinstance(c, SourceConnector)
                doc = c.read(data or b"", filename)
        except ConnectorError as e:
            msg = str(e)
            if msg.startswith(("held_recording", "waiting_tools")):
                kind, _, text = msg.partition(":")
                self.cards.open(project_id, kind, f"Запись «{filename}»: {text.strip()}", {"file": filename},
                                meeting_id)
                return {"status": "held", "reason": msg}
            return {"status": "rejected", "reason": msg}
        if doc.meta.get("own_output"):
            return {"status": "rejected", "reason": "Это выгрузка самой системы — она не может быть источником встречи."}
        dup = self.s.q("SELECT id FROM sources WHERE meeting_id=? AND digest=? AND removed_at IS NULL",
                       (meeting_id, doc.content_digest))
        if dup:
            return {"status": "duplicate", "source_id": dup[0]["id"]}
        sid = self.s.insert("sources", meeting_id=meeting_id, name=doc.name, kind=doc.kind.value, text=doc.text,
                            digest=doc.content_digest, created_at=now())
        media = doc.meta.get("media_path")
        if media and not doc.meta.get("keep_media"):
            try:  # запись удаляется только после сохранения расшифровки
                Path(media).unlink()
                self.s.update("sources", sid, removed_reason="запись распознана, файл удалён")
            except OSError:
                self.cards.open(project_id, "technical", f"Не удалось удалить запись «{filename}»", {}, meeting_id)
        hits = injection_hits(doc.text)
        if hits:  # встреча не блокируется, но человек узнаёт о попытке
            self.cards.open(project_id, "suspicious_source",
                            f"В источнике «{filename}» есть текст, похожий на инструкцию для модели",
                            {"source_id": sid, "patterns": hits[:5]}, meeting_id)
        if doc.meta.get("ambiguous"):
            self.cards.open(project_id, "source_kind", f"Вид источника «{filename}» неочевиден — проверьте",
                            {"source_id": sid, "guess": doc.kind.value}, meeting_id)
        return {"status": "ok", "source_id": sid, "kind": doc.kind.value}

    # ---------------------------------------------------------------- вызов модели
    def _call(self, llm: LLMConnector, budget: RunBudget, purpose: str, system: str, user: str,
              meeting_id: int) -> Any:
        for attempt in (0, 1):
            worst = llm.worst_call_usd(len(system) + len(user)) if hasattr(llm, "worst_call_usd") else None
            budget.check(len(system) + len(user), purpose, worst_usd=worst)
            try:
                # остаток времени прогона — в вызов: один вызов не живёт дольше прогона (01/17)
                kw = {"deadline": budget.deadline} if _takes_deadline(llm) else {}
                res = llm.complete(system, user, json_mode=True, purpose=purpose, **kw)
            except ConnectorError as e:
                self.journal.write(purpose=purpose, meeting_id=meeting_id, model=llm.model, error=str(e))
                raise
            budget.add_cost(res.cost_usd, len(system) + len(user))
            self.journal.write(purpose=purpose, meeting_id=meeting_id, model=res.model, attempt=attempt,
                               prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                               cost_usd=res.cost_usd, seconds=round(res.seconds, 2), chars=len(system) + len(user))
            try:
                return parse_json(res.text, self.prof.strip_think)
            except (ValueError, json.JSONDecodeError):
                if attempt:
                    raise
                user = user + "\n\nНапоминание: только JSON по схеме."
        raise AssertionError("unreachable")

    # ---------------------------------------------------------------- прогон
    def run(self, project_id: int, meeting_id: int, limits: BudgetLimits | None = None) -> RunReport:
        lock = self._meeting_lock(meeting_id)
        if not lock.acquire(blocking=False):
            return RunReport(meeting_id, status="busy", detail="Протокол этой встречи уже формируется.")
        try:
            return self._run(project_id, meeting_id, limits)
        finally:
            lock.release()

    def _run(self, project_id: int, meeting_id: int, limits: BudgetLimits | None) -> RunReport:
        rep = RunReport(meeting_id)
        # чистка нерешённых карточек по сроку (operator.card_cleanup_days): была написана, но не вызывалась (письмо 47)
        self.cards.cleanup(project_id, int(self.theme.get("operator.card_cleanup_days", 0) or 0))
        budget = RunBudget(limits or BudgetLimits(**self.theme.get("budget", {})))
        meeting = self.s.get("meetings", meeting_id) or {}
        if meeting.get("date"):          # дата не в ISO не ломает сравнения и единицы (01/24)
            d0 = lenient_date(meeting["date"])
            meeting = {**meeting, "date": d0.isoformat() if d0 else None}
        srcs = self.s.q("SELECT * FROM sources WHERE meeting_id=? AND removed_at IS NULL ORDER BY id", (meeting_id,))
        transcripts = [s for s in srcs if s["kind"] == SourceKind.TRANSCRIPT.value]
        notes = [s for s in srcs if s["kind"] == SourceKind.NOTES.value]
        if not transcripts and not notes:
            notes = [s for s in srcs if s["kind"] == SourceKind.OTHER.value
                     and not s["name"].endswith("(описание изображения)")]
        if not transcripts and not notes:
            rep.status, rep.detail = "no_sources", "У встречи нет читаемых источников — протокол не собирается."
            return rep
        base = transcripts[0] if transcripts else notes[0]
        source = SourceDoc(base["name"], SourceKind(base["kind"]), base["text"])
        notes_text = "\n".join(n["text"] for n in notes) if transcripts else ""

        people = [Person(p["full_name"], p["role"], p["department"], json.loads(p["aliases"] or "[]"),
                         bool(p["external"]), bool(p["confirmed"]), p["id"], p.get("organization") or "",
                         json.loads(p.get("known_marks") or "[]"))
                  for p in self.s.q("SELECT * FROM people WHERE project_id=?", (project_id,))]
        team = Team(people, self.theme.get("people.diminutives"), self.theme.get("people.department_heads"),
                    tasks=self.reg.list(project_id, None), today=meeting.get("date"))
        gate = TaskGate(team, self.neg, GateConfig(**self.theme.get("gates", {})))

        planned: list[tuple[TaskDraft, Any]] = []
        held: list[tuple[TaskDraft, list[str], str]] = []
        closings: list[tuple[int, str]] = []
        closing_cards: list = []          # (задача, цитата, почему[, описание])
        removals: list[tuple[int, str]] = []
        sections: dict[str, str] = {}
        stopped: BudgetExceeded | None = None     # остановка по пределу: сделанное сохраняется (01/10)
        protocol_notes: list[str] = []            # строки-пометки в шапку протокола
        limited = False                           # дополнение (единицы, проверка) остановлено пределом (01/8)
        mass_closing = None
        ures = None
        active: list[dict] = []
        try:
            # 1. поручения — узкими вызовами по кускам
            drafts: list[TaskDraft] = []
            cut = 0
            names = [p.full_name for p in team.people]

            def extract(first: int, part: list[str], depth: int = 0) -> list:
                """Ответ оборван потолком 4096 — кусок делится пополам (прогон ERP 03.10.26: на 08.09 обрыв
                ронял всю встречу). Делить нечего — кусок пропускается с пометкой, встреча не теряется."""
                sysm, user = self.pb.extract_tasks(first, part, names)
                try:
                    return _list(self._call(self.gen, budget, "extract_tasks", sysm, user, meeting_id), "tasks")
                except AnswerTruncated:
                    if len(part) < 2 or depth >= 4:
                        self.cards.open(project_id, "limit_cut", f"Строки {first}–{first + len(part) - 1}: ответ "
                                        f"модели длиннее потолка, поручения не разобраны", {"what": "поручения"},
                                        meeting_id)
                        return []
                    half = len(part) // 2
                    return extract(first, part[:half], depth + 1) + extract(first + half, part[half:], depth + 1)
            try:
                for first, part in chunks(source.lines, self.prof.chunk_chars):
                    items = extract(first, part)
                    cut += max(0, len(items) - 40)
                    for t in items[:40]:
                        if not isinstance(t, dict) or not isinstance(t.get("description"), str) or not t["description"]:
                            continue
                        who, due = t.get("assignee"), t.get("due_date")
                        drafts.append(TaskDraft(t["description"][:4000], who if isinstance(who, str) else None,
                                                str(t.get("quote") or "")[:4000], _int(t.get("line")),
                                                due if isinstance(due, str) else None, source.name))
            except BudgetExceeded as e:
                stopped = e                       # что успели извлечь — проверяется и сохраняется
            if cut:                               # срез не молча (01/22)
                self.cards.open(project_id, "limit_cut", f"Модель предложила больше 40 задач на кусок — {cut} не "
                                f"рассмотрены", {"cut": cut, "what": "поручения"}, meeting_id)
            existing = [(r["description"], r["assignee"]) for r in self.reg.list(project_id)]
            this_meeting = self.s.q("SELECT source_quote, description, assignee FROM tasks WHERE source_meeting_id=?",
                                    (meeting_id,))
            # уже заведённое этой встречей: (цитата, исполнитель, основы описания). Ключ только
            # по цитате терял второе поручение из той же строки, в том числе другому человеку (01/4)
            known = [(r["source_quote"], r["assignee"] or "", set(stems(r["description"]))) for r in this_meeting]

            def already_set(quote: str, who: str, desc: str) -> bool:
                ds = set(stems(desc))
                return any(q == quote and a == who and jaccard(ds, s0) >= 0.5 for q, a, s0 in known)
            for d in drafts:
                if self.memory.lookup(project_id, "not_a_task", " ".join(sorted(set(stems(d.description))))):
                    rep.skipped_by_rule += 1
                    continue
                g = gate.check(d, source, existing)
                who = g.assignee.label if g.assignee else ""
                if g.quote and already_set(g.quote, who, g.description):
                    continue  # повторный прогон той же встречи: эта задача уже заведена
                if d.due_date:            # срок — только если прозвучал рядом с цитатой (01/6)
                    said = supported_due(d.due_date, self._window(source.lines, g.quote or d.quote), meeting.get("date"))
                    if said is None:
                        rep.due_dropped += 1
                    d = replace(d, due_date=said)
                if g.accepted:
                    planned.append((d, g))
                    existing.append((g.description, who))
                    known.append((g.quote, who, set(stems(g.description))))
                else:
                    held.append((d, g.reasons, g.quote))

            # строки, похожие на внедрённую инструкцию, не становятся основанием закрытия (01/12)
            inj_lines = {i for i, ln in enumerate(source.lines) if looks_like_injection(ln)}
            # и не идут в протокол, единицы и проверку: строка заменяется пометкой, нумерация та же
            safe_text = "\n".join(HIDDEN if i in inj_lines else ln for i, ln in enumerate(source.lines))
            safe_source = SourceDoc(source.name, source.kind, safe_text) if inj_lines else source
            try:
                if stopped is None:
                    # 2. закрытия — код отбирает фразы-кандидаты, модель называет номер
                    own_lines = {r["source_quote"] for r in this_meeting} | {g.quote for _, g in planned}
                    # задача, поставленная позже встречи, этой встречей не закрывается (01/3)
                    md0 = meeting.get("date")
                    active = [t for t in self.reg.list(project_id) if t["source_meeting_id"] != meeting_id
                              and not (md0 and t["date_set"] and t["date_set"] > md0)]
                    cstats: dict = {}
                    cands = self._closing_candidates(active, source.lines, exclude=own_lines, skip=inj_lines,
                                                     stats=cstats)
                    if cstats.get("mentioned", 0) > 60:   # видно одной строкой в протоколе, не карточкой
                        protocol_notes.append(f"На встрече названо {cstats['mentioned']} открытых задач; на "
                                              f"сверку закрытий взяты 60, ближе всего к сказанному.")
                    allowed = {(c["task_ref"], ph["n"]) for c in cands for ph in c["phrases"]}
                    titles = {t["id"]: t["description"] for t in active}
                    if cands:
                        sysm, user = self.pb.closing_check(cands)
                        out = self._call(self.gen, budget, "closing_check", sysm, user, meeting_id)
                        by_phrase: dict[int, set[int]] = {}
                        for c in _list(out, "closed"):
                            if not isinstance(c, dict):
                                continue
                            ph, ref = _int(c.get("phrase")), _int(c.get("task_ref"))
                            if ph is not None and ref is not None and (ref, ph) in allowed:
                                by_phrase.setdefault(ph, set()).add(ref)
                        for ph, refs in by_phrase.items():
                            quote = source.lines[ph]
                            if len(refs) != 1:
                                for r in refs:
                                    closing_cards.append((r, quote, "одна фраза указана для нескольких задач"))
                                continue
                            ref = next(iter(refs))
                            if self.neg.states_removal(quote):     # снятие раньше выполнения: «отменили» — не «сделали»
                                removals.append((ref, quote))      # снятие по голосу (решение владельца 03.10.26)
                            elif self.neg.check(quote).states_fact:
                                closings.append((ref, quote))
                            else:
                                closing_cards.append((ref, quote, "фраза не утверждает ни выполнение, ни снятие"))
                    closing_cards = [(r, q, w, titles.get(r, "")) for r, q, w in closing_cards]

                    # 2а. массовое закрытие — человеку одной карточкой, не в реестр (01/2,
                    # порог утверждён владельцем 03.10.26: больше трёх и больше половины открытых)
                    mass_max = int(self.theme.get("closing.mass_max", 3))
                    mass_share = float(self.theme.get("closing.mass_share", 0.5))
                    n_changes = len(closings) + len(removals)
                    if n_changes > mass_max and n_changes > mass_share * len(active):
                        mass_closing = [{"task_id": tid, "quote": q, "status": "done"} for tid, q in closings]
                        mass_closing += [{"task_id": tid, "quote": q, "status": "dropped"} for tid, q in removals]
                        closings, removals = [], []

                    # 3. протокол — разделы пишет модель, таблицы и шапку — код
                    sysm, user = self.pb.protocol(self.theme["protocol_skeleton"], safe_source.text, notes_text)
                    try:
                        out = self._call(self.gen, budget, "protocol", sysm, user, meeting_id)
                        sections = {k: str(v)[:20000] for k, v in _dict(out, "sections").items()
                                    if k in self.theme["protocol_skeleton"]}
                    except AnswerTruncated:
                        # разделы не поместились в потолок ответа — протокол и задачи сохраняются без них
                        sections = {s: "Не собрано: ответ модели длиннее потолка 4096 токенов." for s in
                                    self.theme["protocol_skeleton"]}
                        limited = True

                    # 3а. единицы встречи (решения, договорённости, вопросы, вехи) — по флагу темы
                    if self.theme.get("units.enabled"):
                        try:
                            ures = UnitsExtractor(self, team, gate).run(project_id, {**meeting, "id": meeting_id},
                                                                         safe_source, budget, existing)
                            if ures["failed_ranges"]:     # неразобранный кусок виден (01/22)
                                rep.detail = (f"Единицы встречи: не разобрано кусков {len(ures['failed_ranges'])} "
                                              f"из {ures['chunks']}.")
                        except BudgetExceeded as e:
                            # единицы — дополнение: протокол сохраняется и без них (правило «сразу, ничего не ждёт»)
                            rep.detail, limited = f"Единицы встречи не собраны: {e}", True
            except BudgetExceeded as e:
                stopped = e
        except Exception as e:  # сбой модели, ответ не той формы, любой сбой коннектора — не наружу (01/7)
            model_err = isinstance(e, (ConnectorError, ValueError, json.JSONDecodeError))
            rep.status = "error"
            rep.detail = f"Сбой при обращении к модели: {e}" if model_err else f"Сбой прогона: {type(e).__name__}"
            rep.calls, rep.cost_usd = budget.calls, round(budget.cost_usd, 4)
            self.cards.open(project_id, "technical", "Сбой прогона встречи",
                            {"detail": str(e)[:500], "error": type(e).__name__}, meeting_id)
            self.journal.write(run=meeting_id, status="error", error=type(e).__name__, calls=budget.calls,
                               cost_usd=budget.cost_usd, stand=self.stand, **self.tool_info)
            return rep
        if stopped is not None:
            rep.status, rep.detail = "stopped_by_limit", str(stopped)
            sections = {s: "Не собрано: прогон остановлен по пределу." for s in self.theme["protocol_skeleton"]}
            self.cards.open(project_id, "stopped_by_limit", "Прогон остановлен по пределу — протокол неполный",
                            {"detail": str(stopped), "stopped_by": budget.stopped_by}, meeting_id)

        # 4. применение — одной транзакцией
        mdate = meeting.get("date")
        try:
            with self.s.tx():
                added = []
                new_people: dict[str, int] = {}

                def new_person(name: str) -> tuple[str, int, bool]:
                    """Новый «не подтверждён» в этом прогоне: одна запись на человека, сверка по основам слов
                    («Сидоровой Ольге» = «Сидорова Ольга»), карточка — только при заведении (письмо 45)."""
                    nw = words(name)
                    for known, pid_ in new_people.items():
                        kw = words(known)
                        if len(kw) == len(nw) and all(same_word(a, b) for a, b in zip(kw, nw)):
                            return known, pid_, False
                    new_people[name] = self.s.insert("people", project_id=project_id, full_name=name, confirmed=0)
                    return name, new_people[name], True
                for d, g in planned:
                    who = g.assignee.label if g.assignee else None
                    pend = g.pending or {}
                    if pend.get("reason") == "department":
                        who = pend["name"]                   # в графе исполнителя — отдел (письмо 36)
                    if pend.get("reason") == "new_person":
                        # документ 14: фамилия и имя, похожих нет — сразу в «Команду» «не подтверждён», задача на
                        # него, оператору карточка на подтверждение; в одном прогоне — одна запись на человека
                        who, np_id, np_new = new_person(pend["name"])
                    tid = self.reg.add(project_id, g.description, who, meeting_id, g.quote, d.due_date, mdate)
                    added.append((tid, d, g))
                    if pend.get("reason") == "new_person":
                        if np_new:
                            self.cards.open(project_id, "confirm_person",
                                            f"Новый человек в «Команде»: {who} — подтвердите",
                                            {"person_id": np_id, "full_name": who, "task_id": tid, "quote": g.quote},
                                            meeting_id)
                        g.pending = None
                    elif pend.get("reason") == "department":
                        self.cards.open(project_id, "assign_person",
                                        f"Отдел без руководителя: назначьте ответственного — {g.description[:100]}",
                                        {"task_id": tid, "description": g.description, "quote": g.quote,
                                         "department": pend["name"], "reason": "department", "marks": [],
                                         "candidates": [{"id": p.id, "name": p.label,
                                                         "hints": [f"отдел «{p.department}»"]}
                                                        for p in pend["candidates"]]}, meeting_id)
                        g.pending = None
                    elif pend.get("reason") == "unknown":
                        self.cards.open(project_id, "assign_person",
                                        f"Кто исполнитель: {d.assignee} — {g.description[:100]}",
                                        {"task_id": tid, "description": g.description, "quote": g.quote,
                                         "mention": d.assignee, "reason": "unknown", "marks": [], "candidates": []},
                                        meeting_id)
                        g.pending = None
                    if d.assignee and g.assignee:
                        # другой отдел в фразе: задача заведена, рядом карточка (решение владельца 03.10.26)
                        dm = team.find(d.assignee, context=g.quote, description=g.description).dept_marks
                        if dm:
                            self.cards.open(project_id, "department_mismatch",
                                            f"Отдел не совпадает: {who} — рядом назван «{dm[0]}»",
                                            {"task_id": tid, "assignee": who, "marks": dm, "quote": g.quote,
                                             "description": g.description}, meeting_id)
                    if g.pending:
                        # задача заведена без исполнителя, рядом карточка: выбор ставит исполнителя
                        # в эту же задачу (решение владельца 03.10.26, письмо 30 оркестратора)
                        pend = g.pending
                        if pend["reason"] == "same_or_new":
                            cands = [{"id": p.id, "name": p.label, "hints": [f"рядом: {x}" for x in pend["marks"]]}
                                     for p in pend["candidates"]]
                            title = f"Тот же или новый: {d.assignee} — {g.description[:100]}"
                        else:
                            all_t = self.reg.list(project_id, None)
                            hints = {h["name"]: h for h in team.candidate_hints(d.assignee or "", g.description,
                                                                                source.lines, notes_text, all_t)}
                            cands = [hints.get(p.label) or {"id": p.id, "name": p.label, "hints": []}
                                     for p in pend["candidates"]]
                            cands.sort(key=lambda x: (-len(x["hints"]), x["name"]))
                            title = f"Кто из них: {d.assignee} — {g.description[:100]}"
                        self.cards.open(project_id, "assign_person", title,
                                        {"task_id": tid, "description": g.description, "quote": g.quote,
                                         "mention": d.assignee, "reason": pend["reason"], "marks": pend["marks"],
                                         "candidates": cands}, meeting_id)
                all_tasks = None
                seen_held: set[tuple] = set()
                for d, reasons, quote in held:
                    # одна задача, исполнитель в разных падежах («Соболева» / «Соболевой») — одна карточка;
                    # сверка по основам и по карточкам этого же прогона (письма 27 и 28)
                    key = (" ".join(sorted(set(stems(d.description)))), " ".join(sorted(set(stems(d.assignee or "")))))
                    if key in seen_held:
                        continue
                    seen_held.add(key)
                    payload = {"description": d.description[:2000], "assignee": d.assignee,
                               "reasons": reasons, "quote": quote, "due_date": d.due_date}
                    title = f"Задача не заведена: {d.description[:120]}"
                    if "department_without_head" in reasons:
                        # R15: понятная карточка — отдел, цитата, сотрудники отдела кандидатами (письмо 14)
                        m = team.find(d.assignee or "")
                        title = f"Отдел без руководителя: назначьте ответственного — {d.description[:100]}"
                        payload["department"] = d.assignee
                        payload["candidates"] = [{"id": p.id, "name": p.label, "hints": [f"отдел «{p.department}»"]}
                                                 for p in m.candidates]
                    elif "same_or_new" in reasons:
                        # «тот же или новый»: рядом признак несовпадения; ответ «это он» запоминает его
                        m = team.find(d.assignee or "", context=quote or d.quote, description=d.description)
                        payload["marks"] = m.marks
                        payload["candidates"] = [{"id": p.id, "name": p.label, "hints": [f"рядом: {x}" for x in m.marks]}
                                                 for p in m.candidates]
                    elif "assignee_ambiguous" in reasons:
                        # спорное имя: кандидаты с подсказками, выбирает человек (решение владельца 03.10.26)
                        all_tasks = all_tasks if all_tasks is not None else self.reg.list(project_id, None)
                        payload["candidates"] = team.candidate_hints(d.assignee or "", d.description, source.lines,
                                                                     notes_text, all_tasks)
                    self.cards.open(project_id, "held_task", title, payload, meeting_id)
                closed = 0
                for tid, quote in closings:
                    if self.reg.set_status(tid, TaskStatus.DONE, "meeting", quote, meeting_date=mdate):
                        closed += 1
                for tid, quote in removals:
                    if self.reg.set_status(tid, TaskStatus.DROPPED, "meeting", quote, meeting_date=mdate):
                        rep.tasks_dropped += 1
                if mass_closing:
                    self.cards.open(project_id, "mass_closing",
                                    f"Встреча закрывает сразу {len(mass_closing)} задач — подтвердите",
                                    {"closings": mass_closing, "open_tasks": len(active),
                                     "why": f"больше {mass_max} и больше {int(mass_share * 100)} % открытых"},
                                    meeting_id)
                for tid, quote, why, desc in closing_cards:
                    # в заголовке — описание задачи, внутренний номер только в данных карточки
                    self.cards.open(project_id, "closing_candidate", f"Возможно выполнено: {desc[:120]}",
                                    {"task_id": tid, "quote": quote, "why": why, "description": desc}, meeting_id)
                if ures:
                    u = apply_units(self.s, project_id, meeting_id, ures, now())
                    rep.units_added, rep.units_closed = u["added"], u["closed"]
                    for unit, g in ures["tasks"]:
                        if g.quote in {q for _, gg in planned for q in [gg.quote]}:
                            continue
                        who = g.assignee.label if g.assignee else None
                        pend = g.pending or {}
                        if pend.get("reason") == "new_person":       # документ 14 — тот же путь, что у протокола
                            who, np_id, np_new = new_person(pend["name"])
                        tid = self.reg.add(project_id, g.description, who, meeting_id, g.quote, None, mdate)
                        added.append((tid, TaskDraft(unit.text, None), g))
                        rep.units_tasks += 1
                        if pend.get("reason") == "new_person" and np_new:
                            self.cards.open(project_id, "confirm_person", f"Новый человек в «Команде»: {who} — подтвердите",
                                            {"person_id": np_id, "full_name": who, "task_id": tid,
                                             "quote": g.quote}, meeting_id)
                        elif pend:
                            self.cards.open(project_id, "assign_person",
                                            f"Кто исполнитель: {g.description[:100]}",
                                            {"task_id": tid, "description": g.description, "quote": g.quote,
                                             "reason": pend.get("reason"), "marks": pend.get("marks", []),
                                             "candidates": [{"id": p.id, "name": p.label, "hints": []}
                                                            for p in pend.get("candidates", [])]}, meeting_id)
                    for unit, g in ures["held"]:
                        if noise_duplicate(g.reasons, unit.text, [getattr(x[2], "description", "") for x in added]):
                            continue        # D4: та же задача уже заведена этим прогоном — карточка была бы ложной тревогой
                        self.cards.open(project_id, "held_task", f"Задача из записи не заведена: {unit.text[:120]}",
                                        {"description": unit.text, "reasons": g.reasons, "quote": unit.quote,
                                         "from": "единицы встречи"}, meeting_id)
                protocol_md = self._render_protocol(meeting, sections, added, closings, srcs, removals,
                                                    str(stopped) if stopped else "", protocol_notes)
                self.s.update("meetings", meeting_id, protocol_md=protocol_md, protocol_built_at=now(),
                              built_from=[s["name"] for s in srcs])
        except Exception as e:  # всё откатилось — реестр не наполовину
            rep.status, rep.detail = "error", "Сбой при сохранении — изменения не применены."
            self.cards.open(project_id, "technical", "Сбой сохранения прогона", {"error": type(e).__name__},
                            meeting_id)
            return rep
        rep.tasks_added, rep.tasks_held, rep.tasks_closed = len(added), len(held), closed
        rep.closing_cards, rep.protocol_saved = len(closing_cards), True

        # 5. проверка после факта: замечания — справка, не шлюз. Строки, похожие на
        # внедрённую инструкцию, проверяющей модели не показываются (01/12)
        try:
            if stopped is not None:
                raise BudgetExceeded(str(stopped))
            sysm, user = self.pb.verify(protocol_md, safe_source.text)
            out = self._call(self.ver, budget, "verify", sysm, user, meeting_id)
            rep.findings = [{"issue": str(f.get("issue", ""))[:500], "quote": str(f.get("quote", ""))[:500],
                             "severity": str(f.get("severity", "minor"))[:10]}
                            for f in _list(out, "findings") if isinstance(f, dict)][:20]
        except BudgetExceeded as e:
            limited = True
            rep.findings = [{"issue": f"Проверка не выполнена: {e}", "severity": "minor"}]
            if stopped is None:
                rep.detail = " ".join(x for x in ("Протокол сохранён, проверка остановлена по пределу.", rep.detail)
                                      if x)
        except Exception as e:  # любой сбой проверки не отменяет сохранённое
            rep.findings = [{"issue": f"Проверка не выполнена: {type(e).__name__}", "severity": "minor"}]
            rep.detail = " ".join(x for x in ("Протокол сохранён, проверка не выполнена.", rep.detail) if x)
        # кодовые проверки черновика — то, что модель почти не ловит (письмо meeting-registry 18):
        # оценочное слово без опоры в записи, факт из эпизода другого проекта. Справка, не шлюз.
        full_source = source.text + ("\n" + notes_text if notes_text else "")
        rep.findings = [{"issue": f["note"], "quote": f["quote"], "source_line": f["source_line"],
                         "severity": "major", "by": "код", "kind": f["kind"]}
                        for f in run_code_checks(protocol_md, full_source)] + rep.findings
        self.s.update("meetings", meeting_id, review_notes=rep.findings)
        # каждая существенная находка проверяющей модели — карточкой оператору; протокол уже сохранён
        # (решение владельца 03.10.26, письмо 38: в Планёрке находки 25.09 никуда не дошли)
        # и существенная находка кодовой проверки черновика — тоже карточка (письмо 40); мелкие — справкой
        for f in rep.findings:
            if str(f.get("severity", "")).lower() != "major":
                continue
            by = "проверка кодом" if f.get("by") == "код" else "проверяющая модель"
            title = f"{'Проверка кодом' if f.get('by') == 'код' else 'Проверка'}: {f['issue'][:150]}"
            self.cards.open(project_id, "review_finding", title,
                            {"issue": f["issue"], "quote": f.get("quote", ""), "severity": "major", "by": by,
                             "source_line": f.get("source_line", "")}, meeting_id)
        rep.calls, rep.cost_usd = budget.calls, round(budget.cost_usd, 4)
        if rep.status == "ok" and limited:
            rep.status = "ok_limited"         # сохранено, но часть остановлена пределом — не «успешный» (01/8)
        self.journal.write(run=meeting_id, status=rep.status, calls=rep.calls, cost_usd=rep.cost_usd,
                           added=rep.tasks_added, held=rep.tasks_held, closed=rep.tasks_closed,
                           dropped=rep.tasks_dropped, skipped_by_rule=rep.skipped_by_rule,
                           stopped_by=budget.stopped_by, stand=self.stand, **self.tool_info)
        return rep

    # ---------------------------------------------------------------- помощники
    @staticmethod
    def _window(lines: list[str], quote: str) -> str:
        """Цитата и соседние строки — где должен прозвучать срок."""
        hit = [i for i, ln in enumerate(lines) if ln.strip() and ln.strip() in (quote or "")]
        if not hit:
            return quote or ""
        return "\n".join(lines[max(0, min(hit) - 1):max(hit) + 2])

    @staticmethod
    def _closing_candidates(active: list[dict], lines: list[str], per_task: int = 4,
                            exclude: set[str] | None = None, skip: set[int] | None = None,
                            max_tasks: int = 60, stats: dict | None = None) -> list[dict]:
        """До 4 фраз на задачу по редким основам — модель видит 14-23 тыс.
        знаков вместо всей встречи (Планёрка closing_check). Строки постановки
        задач этой встречи кандидатами не бывают."""
        excl = {e for e in (exclude or set()) if e}
        line_stems = [set(stems(ln)) for ln in lines]
        freq: dict[str, int] = {}
        for st in line_stems:
            for w in st:
                freq[w] = freq.get(w, 0) + 1
        # 60 задач, ближе всего к сказанному на встрече, а не первые 60 по порядку; карточку «проверены первые 60»
        # убрали — оператору она ничего не давала (решение владельца 03.10.26, после прогона ERP)
        out = []
        for t in active:
            ts = {w for w in stems(t["description"]) if len(w) > 3}
            scored = []
            for i, st in enumerate(line_stems):
                if any(lines[i] in e for e in excl) or i in (skip or ()):
                    continue
                common = ts & st
                if len(common) >= 2:
                    scored.append((sum(1 / freq[w] for w in common), i))
            scored.sort(reverse=True)
            if scored:
                out.append({"task_ref": t["id"], "task": t["description"][:300], "_score": scored[0][0],
                            "phrases": [{"n": i, "text": lines[i][:400]} for _, i in scored[:per_task]]})
        out.sort(key=lambda c: -c["_score"])
        if stats is not None:
            stats["mentioned"] = len(out)            # сколько задач названо на встрече (письмо 42)
        for c in out:
            c.pop("_score")
        return out[:max_tasks]

    def _render_protocol(self, meeting: dict, sections: dict[str, str], added, closings, srcs,
                         removals=(), stopped: str = "", notes: list[str] | tuple = ()) -> str:
        th = self.theme
        date_s = meeting.get("date") or datetime.now().strftime("%Y-%m-%d")
        try:
            date_h = datetime.strptime(date_s, "%Y-%m-%d").strftime(th.get("formats.date", "%d.%m.%Y"))
        except ValueError:
            date_h = date_s
        out = [f"# {th.word('protocol')} {date_h}", "",
               f"*{th.word('sources_line')} {datetime.now().strftime(th.get('formats.datetime', '%d.%m.%Y %H:%M'))}, "
               f"{th.word('sources_from')}: " + ", ".join(s["name"] for s in srcs) + "*", ""]
        if self.stand:
            out += ["*Стенд без модели: протокол собран заглушкой, а не по смыслу встречи.*", ""]
        else:
            ti = self.tool_info
            where = {"openrouter": "OpenRouter", "ollama": "локальная модель (Ollama)"}.get(ti["llm_tool"], ti["llm_tool"])
            out += [f"*Обработано: {where}; собрала {ti['generator']}, проверяет {ti['verifier']}.*", ""]
        if stopped:
            out += [f"*Прогон остановлен по пределу — протокол неполный. {_cell(stopped)}*", ""]
        for n in notes:
            out += [f"*{n}*", ""]
        for sec in th["protocol_skeleton"]:
            out += [f"## {sec}", sections.get(sec, "").strip() or th.word("not_discussed"), ""]
        out += [f"## {th.word('new_tasks')}", ""]
        if added:
            cols = th.get("vocabulary.task_table", ["№", "Задача", "Ответственный", "Срок"])
            out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            for i, (tid, d, g) in enumerate(added, 1):
                # из реестра, после всех ворот: протокол не утверждает исполнителя, которого нет в реестре
                # (письмо 39, находка Планёрки 692d05d — таблица собиралась раньше последнего решения)
                t = self.s.get("tasks", tid) or {}
                who = t.get("assignee") or th.word("unassigned")
                due = t.get("due_date") or "—"
                out.append(f"| {i} | {_cell(t.get('description') or g.description)} | {_cell(who)} | {_cell(due)} |")
        else:
            out.append(th.word("no_new_tasks"))
        if closings:
            out += ["", f"## {th.word('closed_tasks')}", ""]
            for i, (_tid, q) in enumerate(closings, 1):
                out.append(f"{i}. {q.strip()}")
        if removals:
            out += ["", "## Снято по встрече", ""]
            for i, (_tid, q) in enumerate(removals, 1):
                out.append(f"{i}. {q.strip()}")
        return "\n".join(out) + "\n"
