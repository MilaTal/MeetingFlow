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
import os
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from ..connectors.base import (AnswerTruncated, ASRConnector, ConnectorError, LLMConnector, SourceConnector,
                               VisionConnector)
from ..connectors.registry import PluginRegistry
from . import rebuild as rebuild_mod
from .budget import BudgetExceeded, BudgetLimits, CallJournal, RunBudget
from .config import Theme
from .gates import GateConfig, TaskGate
from .negation import NegationRule
from .people import Team
from .prompts import PromptBuilder, chunks, parse_json, profile
from .registry import CardQueue, OperatorMemory, TaskRegistry
from . import deadline
from . import asr_journal, plan as plan_mod, voice_step
from . import petlya_raspoznavaniya as petlya, polnota_rasshifrovki as polnota
from . import korotkiy_protokol, schet_zadach, tablica_zadach, tekst_po_zapisi
from . import iskazheniya_nazvaniy, slovar_whisper
from .team_sync import sync_people
from ..connectors.team_shared import team_shared_state
from .dates import due_text, lenient_date
from .draft_checks import clean_document, run_code_checks
from .morph import supported_due
from .guard import classify, filter_text, line_verdict
from .security import injection_hits, looks_like_injection
from .store import Store, now
from .text import coverage, jaccard, same_word, stems, words
from .units import UnitsExtractor
from .units import apply as apply_units
from .types import Person, SourceDoc, SourceKind, TaskDraft, TaskStatus


def _as_of(rows: list[dict], meeting_date: str | None) -> list[dict]:
    """Задачи, поставленные до даты встречи включительно. Без даты у встречи или задачи — не отсекаем."""
    if not meeting_date:
        return rows
    return [r for r in rows if not (r.get("date_set") and r["date_set"][:10] > meeting_date[:10])]


@dataclass
class RunReport:
    meeting_id: int
    status: str = "ok"          # ok | stopped_by_limit | no_sources | error | busy | not_configured | not_ready
    detail: str = ""
    tasks_added: int = 0
    tasks_held: int = 0
    tasks_doubt: int = 0        # заведено под вопросом (15.10.26)
    tasks_closed: int = 0
    tasks_dropped: int = 0
    due_dropped: int = 0        # срок от модели, которого во встрече не было
    closing_cards: int = 0
    skipped_by_rule: int = 0
    units_added: int = 0
    units_closed: int = 0
    units_tasks: int = 0
    findings: list[dict] = field(default_factory=list)
    run_id: str = ""            # признак сборки: по нему считаются вызовы (25.10.2026)
    step_calls: dict = field(default_factory=dict)
    retryable: bool = False     # проходящий сбой: повтор ставит очередь (25.10.2026, п. 2)
    source_choice: str = ""     # какой источник стал текстом сборки (п. 4)
    source_reason: str = ""
    calls: int = 0
    cost_usd: float = 0.0
    protocol_saved: bool = False
    completeness: str = ""      # полнота расшифровки — строка итога сборки, в документ не идёт (26.10.2026, как ERP)
    text_check: str = ""        # текст по записи: проверено, убрано по причинам (26.10.2026, как ERP)
    text_removed: list = field(default_factory=list)     # убранные предложения (до 40) — в журнал, не в документ
    tasks_returned: int = 0     # возвращены в работу после снятия прежней пересборкой (26.10.2026, как ERP)
    tasks_by_steps: str = ""    # «задачи по шагам: от модели → после стражей → … » — итог сборки, не документ


HIDDEN = "[строка скрыта: похожа на инструкцию для модели]"


def _span(text: str) -> int:
    """Охват расшифровки по её же меткам времени: секунды от первой метки до последней; 0 — меток меньше двух."""
    marks = []
    for m in re.finditer(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text or ""):
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        marks.append(a * 3600 + b * 60 + c if m.group(3) else a * 60 + b)
    return marks[-1] - marks[0] if len(marks) >= 2 and marks[-1] >= marks[0] else 0


def choose_transcript(transcripts: list[dict]) -> tuple[dict | None, str]:
    """Одна расшифровка текстом сборки (правило 25.10.2026): своя локальная; выгрузка ВКС — только если своя пустая,
    знаков меньше половины выгрузки или покрывает меньше 70 % её времени по меткам (когда у обеих есть хотя бы две
    метки). Выбор и причина идут в итог сборки."""
    if not transcripts:
        return None, ""
    local = next((s for s in transcripts if s.get("local_asr")), None)
    other = next((s for s in transcripts if s is not local), None)
    if local is None:
        return transcripts[0], "своей локальной расшифровки нет — текстом первая доступная"
    text = (local.get("text") or "").strip()
    if not text:
        return other or local, "своя расшифровка пустая — текстом выгрузка"
    if other is not None:
        otext = (other.get("text") or "").strip()
        olen = len(otext)
        if olen and len(text) * 2 < olen:
            return other, (f"своя явно неполная ({len(text)} из {olen} знаков выгрузки) — "
                           "текстом выгрузка, своя остаётся источником имён")
        lspan, ospan = _span(text), _span(otext)
        if lspan and ospan and lspan * 10 < ospan * 7:
            return other, (f"своя покрывает {int(lspan * 100 / ospan)} % времени выгрузки — "
                           "текстом выгрузка, своя остаётся источником имён")
    return local, ""


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


# Сомнительная задача — сразу в реестр «под вопросом» с карточкой (решение владельца 15.10.26, заменяет пункт
# документа 14). Вне реестра — дубль, пустая формулировка и внедрённая инструкция: текст реестра идёт в подсказки
# модели на следующих встречах. Уже отклонённое оператором отсекается раньше — по правилу памяти.
# отсеиваются целиком: ни задачи, ни карточки — строкой в журнал разбора (владелец 15.10.26, вечер; Планёрка ddfa618)
SIFTED = {"negation_in_quote", "question_not_assignment", "condition_not_assignment", "intent_not_assignment"}
OUT_OF_REGISTRY = {"duplicate", "empty_description", "suspicious_instruction",
                   # отрицание, вопрос, условие, намерение отсеиваются ДО «под вопросом» (владелец 15.10.26, вечер)
                   "negation_in_quote", "question_not_assignment", "condition_not_assignment", "intent_not_assignment"}
REASON_TEXT = {
    "no_verbatim_quote": "нет дословной цитаты", "no_assignee": "исполнитель не назван",
    "assignee_not_in_team": "человека нет в Команде", "assignee_not_said": "исполнитель не прозвучал",
    "assignee_ambiguous": "неясно, о ком речь", "question_not_assignment": "это вопрос, а не поручение",
    "negation_in_quote": "в цитате отрицание", "report_not_assignment": "похоже на отчёт о сделанном",
    "condition_not_assignment": "условие, а не поручение", "intent_not_assignment": "намерение говорящего о себе",
    "same_or_new": "рядом признак, что это может быть другой человек",
    "department_without_head": "назван отдел, а руководителя у отдела нет",
}


def doubt_buttons(reg, project_id: int, task_id: int, description: str) -> list[dict]:
    """Кнопки карточки «под вопросом» — общей таблицей doubt_labels (Планёрка автор, владелец 15.10.26, вечер):
    «Это дубль» — только если в реестре есть похожая действующая задача."""
    from ..connectors.shared.doubt_labels import кнопки
    from .units import same_point
    similar = any(t["id"] != task_id and same_point(description, t["description"] or "")
                  for t in reg.list(project_id))
    return кнопки(similar)


def doubt_text(reasons: list[str]) -> str:
    return "; ".join(REASON_TEXT.get(r, r) for r in reasons)


def same_task_text(text: str, descriptions: list[str]) -> bool:
    """Та же задача по формулировке: основы без дат покрывают друг друга на 0,7, номера совпадают (D4, D7)."""
    mine = set(stems(_without_dates(text)))

    def same(d: str) -> bool:
        theirs = set(stems(_without_dates(d)))
        if {t for t in theirs if t.isdigit()} != {t for t in mine if t.isdigit()}:
            return False
        return max(coverage(mine, theirs), coverage(theirs, mine)) >= 0.7
    return bool(mine) and any(same(d) for d in descriptions if d)


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
        self.guard_llm: LLMConnector | None = None    # досмотр реплик к системе, если у маршрутов есть роль guard
        self.neg = NegationRule(theme.get("lexicon"), theme.get("lexicon_done"))
        self.reg = TaskRegistry(store, self.neg)
        self.cards = CardQueue(store)
        self.memory = OperatorMemory(store, theme.get("operator.confirmations", 2))
        self.journal = CallJournal(journal_path)
        # Журнал распознавания — рядом с журналом вызовов модели, отдельным файлом: распознавание не входит
        # в потолок вызовов и не тратит денег модели, но точка и её результат должны быть видны. Без пути
        # журнала (тесты, разовые прогоны) не пишем в рабочий файл вовсе.
        self.asr_journal_path = (Path(journal_path).with_name("asr_journal.jsonl")
                                 if journal_path else None)
        self.prof = profile(getattr(generator, "profile", "generic"))
        self.pb = PromptBuilder(theme.get("prompts.domain_role", ""), self.prof)
        self._configure_connectors()

    @property
    def tool_info(self) -> dict:
        """Где обработана встреча: инструмент подключения и модели (письмо meeting-registry 17, п. 4)."""
        info = {"llm_tool": getattr(self.gen, "name", ""), "generator": getattr(self.gen, "model", ""),
                "verifier": getattr(self.ver, "model", "")}
        if getattr(self.ver, "borrowed", False):        # проверяет модель черновика — в сведениях о прогоне явно
            info["verifier_note"] = self.ver.display
        return info

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

    def running_meetings(self) -> list[int]:
        """Встречи, по которым сейчас идёт сборка (замок занят) — для сообщения о смене модели."""
        with self._locks_guard:
            return [mid for (sid, mid), lock in self._locks.items() if sid == id(self.s) and lock.locked()]

    def _meeting_lock(self, meeting_id: int) -> threading.Lock:
        key = (id(self.s), meeting_id)
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _is_own_protocol(self, project_id: int, text: str) -> bool:
        """Свой протокол, присланный обратно (.md или выгрузка Word). Шапка без пометок (13.10.26),
        поэтому узнаём по строкам: не меньше 60 % содержательных строк сохранённого протокола есть в файле."""
        def lines(t: str) -> set[str]:
            return {" ".join(ln.replace("|", " ").replace("#", " ").replace("*", " ").split()).lower()
                    for ln in (t or "").splitlines() if len(ln.strip()) > 12}
        got = lines(text)
        if not got:
            return False
        for r in self.s.q("SELECT protocol_md FROM meetings m "
                          "WHERE m.project_id=? AND m.protocol_md IS NOT NULL AND m.protocol_md != ''", (project_id,)):
            own = lines(r["protocol_md"])
            if len(own) >= 3 and len(own & got) >= 0.6 * len(own):
                return True
        return False

    def _participants(self, meeting_id: int, meeting: dict) -> tuple[list[str], str]:
        """ФИО, опознанные по голосам в источниках встречи, и ведущий — для раздела «Участники».

        Источник — `voice_names` в сводке распознавания: там только имена, прошедшие правило и подтверждённые
        «Командой». Если записи не было, список пуст — модель работает по тексту, как раньше.
        """
        names: list[str] = []
        seen: set[str] = set()
        for row in self.s.q("SELECT meta FROM sources WHERE meeting_id=? AND removed_at IS NULL", (meeting_id,)):
            try:
                meta = json.loads(row.get("meta") or "{}")
            except (TypeError, ValueError):
                continue
            for name in (meta.get("voice_names") or {}).values():
                clean = " ".join(str(name or "").split())
                if clean and clean not in seen:
                    seen.add(clean)
                    names.append(clean)
        return names, " ".join(str(meeting.get("leader") or "").split())

    # ---------------------------------------------------------------- приём
    def _voice_step(self, project_id: int, meeting_id: int, wav_path: Path | None, doc, filename: str) -> None:
        """Разделение по голосам, ФИО по общей базе и вклад в базу — с записью в журнал распознавания.

        Всё, что известно о распознавании, пишется всегда, даже если голоса не разобрались: оператор должен
        видеть точку, длительность и число реплик (замечание к тестовой встрече 26.10.2026).
        """
        meta = doc.meta
        record = {
            "meeting_id": meeting_id, "file": filename, "route": meta.get("route") or meta.get("model") or "",
            "model": meta.get("model") or "", "device": meta.get("device") or "",
            "media_seconds": meta.get("media_seconds"), "segments": len(meta.get("segment_lines") or []),
            "text_chars": len(doc.text or ""),
        }
        # петли распознавания и доля распознанного — в журнал распознавания (как ERP, 26.10.2026)
        if meta.get("asr_loops"):
            record["loops"] = meta["asr_loops"].get("петель", 0)
            record["loops_line"] = meta.get("asr_loops_line", "")
            # подряд одинаковые строки, свёрнутые в первую (как ERP, 27.10.2026)
            if meta["asr_loops"].get("свёрнуто_строк"):
                record["collapsed_lines"] = meta["asr_loops"]["свёрнуто_строк"]
                record["line_series"] = meta["asr_loops"].get("серий_строк", 0)
        if meta.get("recognized_share") is not None:
            record["recognized_share"] = meta["recognized_share"]
        # подсказка распознаванию: токенов из 223, словарь вошло / отброшено (как ERP, 25.10.2026)
        if meta.get("asr_prompt_journal"):
            record["prompt_line"] = meta["asr_prompt_journal"]
        try:
            if wav_path is None or not Path(wav_path).is_file():
                meta["voice_error"] = "записи нет на диске — голоса не разобраны"
                return
            if not meta.get("segment_lines") or not meta.get("segment_times"):
                meta["voice_error"] = "точка распознавания не вернула времена реплик — голоса не разобраны"
                return
            row = self.s.q("SELECT date FROM meetings WHERE id=?", (meeting_id,))
            meeting_date = (row[0]["date"] if row else "") or ""
            base = self.s.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH") or None
            team: list[str] = []
            try:
                st = team_shared_state(voice_base_path=base)
                team = [p.get("full_name") or "" for p in (st.get("people_list") or [])]
            except Exception:  # noqa: BLE001 — без «Команды» имена не подставляются, разбор продолжается
                team = []
            result = voice_step.process(
                wav_path, doc.text, meta, meeting_id=meeting_id, meeting_date=meeting_date,
                base_path=base, team=team, settings=None)
            doc.text = result["text"]
            meta.update({
                "speakers": result.get("speakers"), "signed_lines": result.get("signed_lines"),
                "voice_names": result.get("names") or {}, "voice_base": result.get("base") or {},
                "voice_contribution": result.get("contribution") or {}, "voice_clips": result.get("clips"),
                "diarization_seconds": (result.get("diarization") or {}).get("seconds"),
                "diarization_device": (result.get("diarization") or {}).get("device"),
                "voice_notes": result.get("notes") or [],
            })
            record.update({
                "speakers": result.get("speakers"), "signed_lines": result.get("signed_lines"),
                "voice_total": (result.get("base") or {}).get("lyudey"),
                "voice_samples": (result.get("contribution") or {}).get("samples"),
                "voice_hinted": (result.get("contribution") or {}).get("hinted"),
                "clips": result.get("clips"),
                "diarization_seconds": (result.get("diarization") or {}).get("seconds"),
                "diarization_device": (result.get("diarization") or {}).get("device"),
                "notes": result.get("notes") or [],
            })
        except voice_step.VoiceStepError as exc:
            meta["voice_error"] = str(exc)
            record["error"] = str(exc)
            self.cards.open(project_id, "technical",
                            f"Голоса не разобраны: запись «{filename}»", {"detail": str(exc)[:400]}, meeting_id)
        except Exception as exc:  # noqa: BLE001 — шаг голосов не отменяет распознавание
            meta["voice_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            record["error"] = meta["voice_error"]
            self.cards.open(project_id, "technical",
                            f"Голоса не разобраны: запись «{filename}»",
                            {"detail": meta["voice_error"][:400]}, meeting_id)
        finally:
            meta["asr"] = record
            asr_journal.write(self.asr_journal_path, **record)

    def _podpis(self, meeting_id: int) -> str:
        """«Встреча 22.10.2026» — подпись карточек «Система» (слово встречи — из темы)."""
        row = self.s.get("meetings", meeting_id) or {}
        d = lenient_date(row.get("date"))
        return f"{self.theme.get('vocabulary.meeting', 'Встреча')} {d:%d.%m.%Y}" if d else \
            str(self.theme.get("vocabulary.meeting", "Встреча"))

    def _petli(self, project_id: int, meeting_id: int, doc) -> dict:
        """Петли распознавания: текст и строки сегментов чистятся (`petlya_raspoznavaniya`, близнец ERP), итог — в
        сводку и журнал распознавания; доля распознанного записи — туда же; карточка «Система» — по доле петель."""
        doc.text, итог = petlya.очистить(doc.text)
        meta = petlya.очистить_сводку(doc.meta, итог)
        if petlya.есть_находки(итог):        # петли и подряд одинаковые строки (как ERP, 27.10.2026)
            meta["asr_loops_line"] = petlya.строка_итога(итог)
        мера = polnota.по_записи(doc.text, meta.get("media_seconds"))
        if мера is not None:
            meta["recognized_share"] = мера["доля"]
        doc.meta.clear()
        doc.meta.update(meta)
        try:
            petlya.отметить(self.s, self.cards, project_id, meeting_id, self._podpis(meeting_id), итог)
        except Exception as exc:  # noqa: BLE001 — карточка не отменяет распознанный текст
            self.step_failed(project_id, meeting_id, "Карточка петель распознавания", exc)
        return итог

    def _polnota(self, project_id: int, meeting_id: int, meeting: dict, base: dict) -> str:
        """Полнота расшифровки сборки (`polnota_rasshifrovki`, близнец ERP): последняя метка против длительности
        записи; меньше 80 % — карточка «Система», снова полная — открытая карточка закрывается сама. Длительности нет —
        длина против медианы последних встреч проекта того же дня недели, только строка итога. В документ — ничего."""
        try:
            meta = json.loads(base.get("meta") or "{}")
        except (TypeError, ValueError):
            meta = {}
        мера = polnota.по_записи(base.get("text") or "", meta.get("media_seconds"))
        if мера is not None:
            polnota.отметить(self.s, self.cards, project_id, meeting_id, self._podpis(meeting_id), мера)
            return polnota.строка_итога(мера)
        d = lenient_date(meeting.get("date"))
        if d is None:
            return ""
        обычные = []
        for r in self.s.q("SELECT m.date, s.text FROM sources s JOIN meetings m ON m.id = s.meeting_id "
                          "WHERE m.project_id=? AND s.meeting_id != ? AND s.kind=? AND s.removed_at IS NULL "
                          "ORDER BY m.date DESC, s.id", (project_id, meeting_id, SourceKind.TRANSCRIPT.value)):
            md = lenient_date(r["date"])
            if md is not None and md.isoweekday() == d.isoweekday():
                обычные.append(len(r["text"] or ""))
        return polnota.короче_обычной(len(base.get("text") or ""), обычные,
                                      polnota.основа_сравнения(None, d.isoweekday()))

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
                # словарь проектов в подсказке распознавания — по выключателю «Параметров системы» (как ERP)
                сборка = slovar_whisper.подсказка_сборка(self.s, project_id)
                if сборка.текст and hasattr(c, "initial_prompt"):
                    c.initial_prompt = сборка.текст
                try:
                    doc = c.transcribe(path)
                finally:
                    if hasattr(c, "initial_prompt"):
                        c.initial_prompt = ""
                if doc.meta.get("asr_prompt_sent"):
                    doc.meta.update(сборка.meta())
                    doc.meta["asr_project_vocab"] = bool(сборка.словарь_вошло)
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
        if doc.meta.get("own_output") or self._is_own_protocol(project_id, doc.text):
            return {"status": "rejected", "reason": "Это выгрузка самой системы — она не может быть источником встречи."}
        if isinstance(c, ASRConnector):
            # Петли распознавания — сразу после распознавания, до голосов и до сохранения (как ERP, 26.10.2026):
            # повторы сверх двух убираются, строки и их времена остаются; доля убранного больше 1 % — карточка.
            self._petli(project_id, meeting_id, doc)
            # Голоса — до сохранения и до удаления записи: разделению и отрывкам нужен звук. Сбой шага не
            # отменяет распознанный текст, причина уходит в журнал и карточку.
            self._voice_step(project_id, meeting_id, path, doc, filename)
        dup = self.s.q("SELECT id FROM sources WHERE meeting_id=? AND digest=? AND removed_at IS NULL",
                       (meeting_id, doc.content_digest))
        if dup:
            return {"status": "duplicate", "source_id": dup[0]["id"]}
        sid = self.s.insert("sources", meeting_id=meeting_id, name=doc.name, kind=doc.kind.value, text=doc.text,
                            digest=doc.content_digest, created_at=now(), local_asr=int(isinstance(c, ASRConnector)),
                            meta=json.dumps(doc.meta, ensure_ascii=False))
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
    def step_failed(self, project_id: int, meeting_id: int, step: str, e: BaseException | str) -> None:
        """Одна точка для сбоев шагов сборки (стенд 40, ERP 9e8af1a): ошибка шага не глотается — оператор
        получает техническую карточку с причиной; прогон и сохранённое при этом не отменяются."""
        detail = e if isinstance(e, str) else f"{type(e).__name__}: {str(e)[:400]}"
        self.cards.open(project_id, "technical", f"Шаг сборки не выполнен: {step}", {"detail": detail}, meeting_id)

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
            budget.answered.setdefault(purpose, []).append(res.model)
            if isinstance(res.raw, dict) and res.raw.get("provider"):
                budget.answered.setdefault("_external", []).append(f"{res.raw.get('route') or res.model} ({res.raw['provider']})")
            raw = res.raw if isinstance(res.raw, dict) else {}
            # поставщик и вид цены — для предела расхода по поставщику и «поставщик / расчёт / не задан» (стенд 46)
            self.journal.write(purpose=purpose, meeting_id=meeting_id, model=res.model, attempt=attempt,
                               prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                               cost_usd=res.cost_usd, seconds=round(res.seconds, 2), chars=len(system) + len(user),
                               **{k: raw[k] for k in ("route", "provider", "cost_source", "cached_tokens",
                                                      "reasoning_effort")   # рассуждение вызова (27.10.2026)
                                  if raw.get(k) is not None})
            try:
                return parse_json(res.text, self.prof.strip_think)
            except (ValueError, json.JSONDecodeError) as e:
                self.journal.bad_answer(purpose, meeting_id, res.model, res.text, f"{type(e).__name__}: {e}")
                if attempt:
                    raise
                user = user + "\n\nНапоминание: только JSON по схеме."
        raise AssertionError("unreachable")

    # ---------------------------------------------------------------- прогон
    def build_plan(self, project_id: int, meeting_id: int) -> dict:
        """План встречи до её начала — один вызов модели, как «Подготовка встречи» в ERP."""
        meeting = self.s.get("meetings", meeting_id)
        if not meeting or meeting.get("project_id") != project_id:
            raise ValueError("Встреча не найдена.")
        data = plan_mod.collect(self.s, meeting)
        source = plan_mod.source_text(data)
        if not source.strip():
            source = "Прошлого протокола, открытых пунктов, задач и материалов пока нет."
        budget = RunBudget(BudgetLimits(**self.theme.get("budget", {})))
        names = [str(m.get("name") or "") for m in data.get("materials") or []]
        sysm, user = self.pb.plan(plan_mod.SECTIONS, source, names)
        out = self._call(self.gen, budget, "plan", sysm, user, meeting_id)
        sections = {name: str(_dict(out, "sections").get(name) or "") for name in plan_mod.SECTIONS}
        gist = plan_mod.суть_модели(out.get("materials_gist") if isinstance(out, dict) else None, names)
        markdown = plan_mod.render(meeting, sections, data.get("materials") or [], gist)
        self.s.update("meetings", meeting_id, plan_md=markdown, plan_built_at=now())
        return {"markdown": markdown, "sections": sections, "calls": budget.calls,
                "cost_usd": round(budget.cost_usd, 4), "model": self.gen.model}

    def run(self, project_id: int, meeting_id: int, limits: BudgetLimits | None = None) -> RunReport:
        lock = self._meeting_lock(meeting_id)
        if not lock.acquire(blocking=False):
            return RunReport(meeting_id, status="busy", detail="Протокол этой встречи уже формируется.")
        try:
            начало = now()
            rep = self._run(project_id, meeting_id, limits)
            # узкий порог (как ERP 24.10.2026, перенос 27.10.2026): задача без адресата — строкой «Возможных поручений»
            if getattr(rep, "protocol_saved", False):
                from . import vozmozhnye
                try:
                    vozmozhnye.разделить_после_сборки(self.s, self.reg, project_id, meeting_id, начало)
                except Exception as e:  # noqa: BLE001 — сбой порога не отменяет сохранённый протокол
                    self.step_failed(project_id, meeting_id, "Возможные поручения", e)
            return rep
        finally:
            lock.release()

    def _run(self, project_id: int, meeting_id: int, limits: BudgetLimits | None) -> RunReport:
        rep = RunReport(meeting_id)
        # признак сборки: номер встречи повторяется (стенд, удаление), по нему счёт вызовов не складывается
        self.journal.run_id = f"{meeting_id}-{datetime.now():%Y%m%dT%H%M%S}-{threading.get_ident()}"
        rep.run_id = self.journal.run_id
        if getattr(self.gen, "configured", True) is False:
            # модели по умолчанию нет (13.10.26, 15.10.26): роль не назначена — ни одного вызова, оператору карточка
            rep.status, rep.detail = "not_configured", self.gen.not_configured_text
            self.cards.open(project_id, "technical", "Сборка не начата: модель не настроена",
                            {"detail": rep.detail}, meeting_id)
            return rep
        # чистка нерешённых карточек по сроку (operator.card_cleanup_days): была написана, но не вызывалась (письмо 47)
        # порог с экрана «Параметры системы → Пороги» важнее темы (владелец 11.10.26, как в Планёрке)
        days = self.s.get_setting("card_cleanup_days")
        self.cards.cleanup(project_id, int(days if days is not None else self.theme.get("operator.card_cleanup_days", 0) or 0))
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
        base, rep.source_reason = choose_transcript(transcripts) if transcripts else (None, "")
        if base is None:
            base = notes[0]
        rep.source_choice = base.get("name") or ""
        if base.get("kind") == SourceKind.TRANSCRIPT.value:
            try:
                rep.completeness = self._polnota(project_id, meeting_id, meeting, base)
            except Exception as exc:  # noqa: BLE001 — мера полноты не останавливает сборку
                self.step_failed(project_id, meeting_id, "Полнота расшифровки", exc)
        source = SourceDoc(base["name"], SourceKind(base["kind"]), base["text"])
        notes_text = "\n".join(n["text"] for n in notes) if transcripts else ""
        # пробный запрос перед сборкой (стенд 39, ERP 689c739): готова ли модель принять запрос такого размера;
        # не готова — следующая точка; не готова ни одна — сборка не начинается, одна карточка на встречу
        if hasattr(self.gen, "probe"):
            ready, tries = self.gen.probe(chars=min(len(source.text) + len(notes_text), 200_000))
            for t in tries:
                self.journal.write(purpose="probe", meeting_id=meeting_id, point=t.get("point"), ok=t.get("ok"),
                                   reason=t.get("reason", ""), seconds=t.get("seconds"))
            if not ready:
                rep.status = "not_ready"
                rep.detail = "Модель не готова: " + "; ".join(f"{t.get('point')}: {t.get('reason')}" for t in tries)
                title = "Сборка не начата: модель не готова"
                if not self.s.q("SELECT id FROM cards WHERE meeting_id=? AND title=? AND status='open'",
                                (meeting_id, title)):
                    self.cards.open(project_id, "technical", title,
                                    {"detail": "пробный запрос перед сборкой — ни одна точка роли генерации не ответила",
                                     "points": [{"point": t.get("point"), "reason": t.get("reason")} for t in tries]},
                                    meeting_id)
                return rep

        # Общая «Команда» → проектная: без этого подсказка модели и страж исполнителя работают по пустому
        # списку, хотя подтверждённые люди есть (задание владелицы 26.10.2026).
        sync_people(self.s, project_id, self.s.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH"))
        people = [Person(p["full_name"], p["role"], p["department"], json.loads(p["aliases"] or "[]"),
                         bool(p["external"]), bool(p["confirmed"]), p["id"], p.get("organization") or "",
                         json.loads(p.get("known_marks") or "[]"))
                  for p in self.s.q("SELECT * FROM people WHERE project_id=?", (project_id,))]
        team = Team(people, self.theme.get("people.diminutives"), self.theme.get("people.department_heads"),
                    tasks=_as_of(self.reg.list(project_id, None), meeting.get("date")), today=meeting.get("date"))
        gate = TaskGate(team, self.neg, GateConfig(**self.theme.get("gates", {})))

        planned: list[tuple[TaskDraft, Any]] = []
        due_unconfirmed: dict[int, str] = {}
        due_kinds: dict[int, str] = {}           # id черновика → вид срока: «сегодня» / «оценка» (12.10.26)     # id черновика → срок модели, не прозвучавший рядом (12.10.26)
        held: list[tuple[TaskDraft, list[str], str, Any]] = []
        doubt = 0                         # заведено под вопросом этим прогоном (15.10.26)
        closings: list[tuple[int, str]] = []
        closing_cards: list = []          # (задача, цитата, почему[, описание])
        removals: list[tuple[int, str]] = []
        sections: dict[str, str] = {}
        stopped: BudgetExceeded | None = None     # остановка по пределу: сделанное сохраняется (01/10)
        closing_mentioned = 0                     # «названо больше 60» — в журнал прогона, не в документ (13.10)
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
            # «Проект только при прозвучавшем названии» (выключатель «Параметров системы», как ERP 24.10.2026): другой
            # проект справочника в начале формулировки без опоры в записи снимается; проект встречи не снимается
            if drafts:
                _md, описания, _св = iskazheniya_nazvaniy.применить_к_встрече(
                    self.s, project_id, "", [d.description for d in drafts], source.text)
                drafts = [replace(d, description=о) if о != d.description else d for d, о in zip(drafts, описания)]
            # реестр «на дату встречи»: поставленное позже D не делает поручение D дублем (стенд 42, 371f967)
            existing = [(r["description"], r["assignee"]) for r in _as_of(self.reg.list(project_id), meeting.get("date"))]
            this_meeting = self.s.q("SELECT id, source_quote, description, assignee, status FROM tasks "
                                    "WHERE source_meeting_id=?", (meeting_id,))
            # уже заведённое этой встречей: (номер задачи, цитата, исполнитель, основы описания). Ключ только
            # по цитате терял второе поручение из той же строки, в том числе другому человеку (01/4)
            known = [(r["id"], r["source_quote"], r["assignee"] or "", set(stems(r["description"])))
                     for r in this_meeting]
            kept_ids: set[int] = set()      # задачи прежней сборки, которые новая сборка подтвердила
            back_ids: set[int] = set()      # снятые прежней пересборкой и найденные снова — вернуть с прежним номером
            repeats = 0                     # поручения, которые сборка узнала как свою прежнюю задачу

            def hit_kept(tid: int) -> None:
                """Узнали задачу этой встречи: в работе — подтверждена; снята пересборкой — вернуть (26.10.2026)."""
                kept_ids.add(tid)
                if rebuild_mod.снята_пересборкой(self.s, tid):
                    back_ids.add(tid)

            def already_set(quote: str, who: str, desc: str) -> int | None:
                """Номер уже заведённой задачи этой встречи или -1, если совпала с заведённой в этом же прогоне;
                None — не совпала ни с чем."""
                ds = set(stems(desc))
                for tid, q, a, s0 in known:
                    if q == quote and a == who and jaccard(ds, s0) >= 0.5:
                        return tid if tid is not None else -1
                return None
            for d in drafts:
                if self.memory.lookup(project_id, "not_a_task", " ".join(sorted(set(stems(d.description))))):
                    rep.skipped_by_rule += 1
                    continue
                g = gate.check(d, source, existing)
                who = g.assignee.label if g.assignee else ""
                if g.quote and (hit := already_set(g.quote, who, g.description)) is not None:
                    if hit > 0:
                        hit_kept(hit)
                    repeats += 1
                    continue  # повторный прогон той же встречи: эта задача уже заведена
                if d.due_date:            # срок — только если прозвучал рядом с цитатой (01/6)
                    said = supported_due(d.due_date, self._window(source.lines, g.quote or d.quote), meeting.get("date"))
                    proposed = d.due_date
                    kind = None
                    md = lenient_date(meeting.get("date"))
                    if md is not None:
                        # относительный срок — в дату от даты встречи; «к следующей встрече» — маркер без даты
                        # (решение владелицы 20.10.2026); фраза из записи важнее даты модели (общий deadline.py)
                        win = self._window(source.lines, g.quote or d.quote)
                        if said is not None and lenient_date(said) is None:
                            dl = deadline.resolve(said, md)
                            if dl.due is not None:
                                said, kind = f"{dl.due:%d.%m.%Y}", dl.kind
                            elif dl.kind == deadline.NEXT_MEETING:
                                said, kind = None, deadline.NEXT_MEETING
                        elif said is None:
                            heard = {(x, k) for x, k, _p in deadline._candidates(win, md)}
                            if len({x for x, _k in heard}) == 1:
                                x, kind = next(iter(heard))
                                said = f"{x:%d.%m.%Y}" if x is not None else None
                        if said is not None and kind is None:
                            same = [k for x, k, _p in deadline._candidates(win, md) if x == lenient_date(said)]
                            kind = same[0] if same else None
                        if said is not None and lenient_date(said) == md:
                            kind = deadline.TODAY
                    d = replace(d, due_date=said)
                    if kind is not None:
                        due_kinds[id(d)] = kind
                    if said is None and kind != deadline.NEXT_MEETING:
                        # не молча: задача без срока и карточка, как в Планёрке (владелец 12.10.26)
                        rep.due_dropped += 1
                        due_unconfirmed[id(d)] = proposed
                if g.accepted:
                    planned.append((d, g))
                    existing.append((g.description, who))
                    known.append((None, g.quote, who, set(stems(g.description))))
                else:
                    held.append((d, g.reasons, g.quote, g))

            # строки, похожие на внедрённую инструкцию, не становятся основанием закрытия (01/12)
            inj_lines = {i for i, ln in enumerate(source.lines) if looks_like_injection(ln)}
            if self.guard_llm:   # обращение к системе без явной темы — досмотр моделью, не больше 10 строк за прогон
                unsure = [i for i, ln in enumerate(source.lines) if i not in inj_lines and line_verdict(ln)["unsure"]]
                for i in unsure[:10]:
                    said = classify(self.guard_llm, source.lines[i])
                    if said:
                        inj_lines.add(i)
                    elif said is None:
                        self.cards.open(project_id, "suspicious_source", "Досмотр не ответил: реплика обращена к "
                                        "системе, решите, деловая ли она", {"line": i + 1, "quote": source.lines[i][:200]},
                                        meeting_id)
                if any(i in inj_lines for i in unsure[:10]):
                    self.cards.open(project_id, "suspicious_source", "Досмотр пометил реплики, обращённые к системе",
                                    {"lines": sorted(i + 1 for i in unsure[:10] if i in inj_lines)}, meeting_id)
            # и не идут в протокол, единицы и проверку: строка заменяется пометкой, нумерация та же
            safe_text = "\n".join(HIDDEN if i in inj_lines else ln for i, ln in enumerate(source.lines))
            safe_source = SourceDoc(source.name, source.kind, safe_text) if inj_lines else source
            if inj_lines:   # протокол не отказываем; пометка — оператору карточкой, документ чистый (владелец 13.10.26)
                nums = ", ".join(str(i + 1) for i in sorted(inj_lines)[:10]) + ("…" if len(inj_lines) > 10 else "")
                self.cards.open(project_id, "suspicious_source",
                                f"В записи {len(inj_lines)} реплик(и) обращены к самой системе, а не к участникам",
                                {"lines": nums, "note": "в разбор не взяты"}, meeting_id)
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
                    if cstats.get("mentioned", 0) > 60:   # в журнал прогона: не документ и не карточка (03.10, 13.10)
                        closing_mentioned = cstats["mentioned"]
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
                    participants, leader = self._participants(meeting_id, meeting)
                    sysm, user = self.pb.protocol(self._skeleton(meeting), safe_source.text, notes_text,
                                                  participants=participants, leader=leader)
                    try:
                        out = self._call(self.gen, budget, "protocol", sysm, user, meeting_id)
                        sections = {k: str(v)[:20000] for k, v in _dict(out, "sections").items()
                                    if k in self._skeleton(meeting)}
                    except AnswerTruncated:
                        # разделы не поместились в потолок ответа — протокол и задачи сохраняются без них
                        cap = int(self.theme.get("llm.max_answer_tokens", 4096))
                        sections = {s: None for s in self._skeleton(meeting)}   # None — раздел не собран
                        self.cards.open(project_id, "technical", "Разделы протокола не собраны",
                                        {"detail": f"ответ модели длиннее потолка {cap} токенов"}, meeting_id)
                        limited = True

                    # 3а. единицы встречи (решения, договорённости, вопросы, вехи) — по флагу темы
                    if self.theme.get("units.enabled"):
                        try:
                            ures = UnitsExtractor(self, team, gate).run(project_id, {**meeting, "id": meeting_id},
                                                                         safe_source, budget, existing)
                            if ures["failed_ranges"]:     # неразобранный кусок виден (01/22) — и карточкой (стенд 40)
                                rep.detail = (f"Единицы встречи: не разобрано кусков {len(ures['failed_ranges'])} "
                                              f"из {ures['chunks']}.")
                                self.step_failed(project_id, meeting_id, "Единицы встречи: разбор части записи",
                                                 rep.detail)
                        except BudgetExceeded as e:
                            # единицы — дополнение: протокол сохраняется и без них
                            rep.detail, limited = f"Единицы встречи не собраны: {e}", True
            except BudgetExceeded as e:
                stopped = e
        except Exception as e:  # сбой модели, ответ не той формы, любой сбой коннектора — не наружу (01/7)
            model_err = isinstance(e, (ConnectorError, ValueError, json.JSONDecodeError))
            # проходящий сбой — недоступность модели и сети; формат, потолок и обрыв ответа сами не пройдут
            rep.retryable = isinstance(e, ConnectorError) and not isinstance(e, (AnswerTruncated, BudgetExceeded))
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
            sections = {s: None for s in self._skeleton(meeting)}   # причина — в карточке ниже
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
                    # отдел без руководителя: исполнитель пустой, отдел — в карточке (владелец 10.10.26 при сверке
                    # скиллов: так в скилле meetflow и движке; отменяет «в графе исполнителя — отдел», письмо 36)
                    if pend.get("reason") == "new_person":
                        # документ 14: фамилия и имя, похожих нет — сразу в «Команду» «не подтверждён», задача на
                        # него, оператору карточка на подтверждение; в одном прогоне — одна запись на человека
                        who, np_id, np_new = new_person(pend["name"])
                    tid = self.reg.add(project_id, g.description, who, meeting_id, g.quote, d.due_date, mdate,
                                       due_kinds.get(id(d)))
                    added.append((tid, d, g))
                    if id(d) in due_unconfirmed:
                        self._due_card(project_id, meeting_id, tid, g, due_unconfirmed[id(d)], mdate)
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
                for d, reasons, quote, g in held:
                    # уверенная близняшка этого прогона вытесняет сомнительную — без карточки (15.10.26, Планёрка b85d70f)
                    if same_task_text(d.description, [getattr(x[2], "description", "") for x in added]):
                        continue
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
                    if set(reasons) & SIFTED:
                        self.journal.write(purpose="triage", meeting_id=meeting_id, verdict="отсеяно",
                                           reasons=sorted(set(reasons) & SIFTED), description=d.description[:300],
                                           quote=(quote or d.quote or "")[:300])
                        continue
                    if not set(reasons) & OUT_OF_REGISTRY:
                        # под вопросом: в реестр и в протокол как обычная, причина — служебная, карточка обязательна
                        who = g.assignee.label if g.assignee else None
                        # пересборка: та же задача этой встречи уже заведена — без цитаты повтор узнаётся по
                        # формулировке и исполнителю (находка циклов ролей ERP и Планёрки, 15.10.26)
                        hit = next((r["id"] for r in this_meeting
                                    if (r["assignee"] or None) == who
                                    and same_task_text(g.description or d.description, [r["description"]])), None)
                        if hit is not None:
                            hit_kept(hit)
                            continue
                        tid = self.reg.add(project_id, g.description or d.description, who, meeting_id, quote,
                                           d.due_date, mdate, due_kinds.get(id(d)), doubt_reason=doubt_text(reasons))
                        added.append((tid, d, g))
                        doubt += 1
                        payload["task_id"] = tid
                        payload["buttons"] = doubt_buttons(self.reg, project_id, tid, g.description or d.description)
                        self.cards.open(project_id, "task_doubt", f"Задача под вопросом: {d.description[:120]}",
                                        payload, meeting_id)
                        continue
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
                        if same_task_text(unit.text, [getattr(x[2], "description", "") for x in added]):
                            continue        # D4: та же задача уже заведена этим прогоном — карточка была бы ложной тревогой
                        hit = next((r["id"] for r in this_meeting
                                    if same_task_text(g.description or unit.text, [r["description"]])), None)
                        if hit is not None:
                            hit_kept(hit)
                            continue        # пересборка: эта задача встречи уже заведена
                        if set(g.reasons) & SIFTED:                  # отсеяно — строкой в журнал разбора
                            self.journal.write(purpose="triage", meeting_id=meeting_id, verdict="отсеяно",
                                               reasons=sorted(set(g.reasons) & SIFTED), description=unit.text[:300])
                            continue
                        if not set(g.reasons) & OUT_OF_REGISTRY:     # под вопросом — и на этом пути (15.10.26)
                            tid = self.reg.add(project_id, g.description or unit.text,
                                               g.assignee.label if g.assignee else None, meeting_id, unit.quote,
                                               None, mdate, doubt_reason=doubt_text(g.reasons))
                            added.append((tid, TaskDraft(unit.text, None), g))
                            doubt += 1
                            self.cards.open(project_id, "task_doubt", f"Задача под вопросом: {unit.text[:120]}",
                                            {"task_id": tid, "description": unit.text, "reasons": g.reasons,
                                             "quote": unit.quote, "from": "единицы встречи",
                                             "buttons": doubt_buttons(self.reg, project_id, tid, unit.text)},
                                            meeting_id)
                            continue
                        self.cards.open(project_id, "held_task", f"Задача из записи не заведена: {unit.text[:120]}",
                                        {"description": unit.text, "reasons": g.reasons, "quote": unit.quote,
                                         "from": "единицы встречи"}, meeting_id)
                # Снятая прежней пересборкой и найденная снова — в работу с прежним номером (ERP 26.10.2026); до
                # снятия «не вошедших» и до сборки таблицы: строка задачи в документе не теряется.
                when_rb = rebuild_mod.когда_сейчас()
                for tid in sorted(back_ids):
                    if rebuild_mod.вернуть(self.s, self.reg, tid, when_rb):
                        rep.tasks_returned += 1
                # Пересборка снимает задачи прежней сборки, которых нет в новой (решение владелицы 21.10.2026).
                # Неполное извлечение (остановка по пределу) ничего не снимает: «не найдена» не доказано.
                res = rebuild_mod.drop_missing(self.s, self.reg, meeting_id, mdate,
                                               kept_ids | {tid for tid, _d, _g in added},
                                               incomplete=stopped is not None)
                for t, edits in res["kept"]:
                    # одна карточка на задачу за всё время: повторная пересборка новых не заводит
                    if any(json.loads(c["payload"] or "{}").get("task_id") == t["id"]
                           for c in self.s.q("SELECT payload FROM cards WHERE kind='rebuild_kept' AND meeting_id=?",
                                             (meeting_id,))):
                        continue
                    self.cards.open(project_id, "rebuild_kept",
                                    f"Задача не вошла в пересборку, но правилась человеком: {(t['description'] or '')[:100]}",
                                    {"task_id": t["id"], "description": t["description"], "edits": edits,
                                     "when": res["when"]}, meeting_id)
                # пометка «оперативная» из раздела секретаря — сама, до таблицы (как ERP, 26.10.2026)
                if notes:
                    self._operativnye_po_sekretaryu(project_id, notes)
                protocol_md = self._render_protocol(meeting, sections, added, closings, srcs, removals,
                                                    record=safe_source.text + ("\n" + notes_text if notes_text else ""),
                                                    people=[p.full_name for p in team.people], rep=rep,
                                                    base_kind=source.kind.value)
                # то же правило для абзацев «**Проект** – …» тела: без опоры — «Проект не определён» (как ERP)
                protocol_md, _оп, _св = iskazheniya_nazvaniy.применить_к_встрече(self.s, project_id, protocol_md, [],
                                                                                 safe_source.text)
                protocol_md, marks = clean_document(protocol_md)   # проверка кодом до сохранения (13.10.26)
                # задачи по шагам — одной строкой итога сборки (schet_zadach, близнец ERP 26.10.2026). Шага «после
                # фильтра опоры» у MeetFlow нет: таблица документа строится из реестра, а не из таблицы черновика.
                mine = self.s.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='active'", (meeting_id,))
                md_h = lenient_date(mdate)
                rep.tasks_by_steps = schet_zadach.строка({
                    "от модели": len(drafts), "после стражей": len(planned) + doubt + repeats,
                    "заведено в реестр": len(mine),
                    "строк в таблице документа": schet_zadach.строк_задач(
                        protocol_md, f"{md_h:%d.%m.%Y}" if md_h else None),
                    "пояснение": f"новых {len(added)}, возвращено {rep.tasks_returned}"})
                if marks:
                    self.cards.open(project_id, "technical", "Из протокола убрана системная пометка",
                                    {"marks": marks[:10]}, meeting_id)
                role = self.theme.get("prompts.domain_role")
                protocol_md, filtered = filter_text(protocol_md, (role,) if isinstance(role, str) else ())
                if filtered:   # модель пересказала служебное — заменено, оператор знает (письмо 10.10, строки 15–20)
                    self.cards.open(project_id, "suspicious_source", "В протоколе скрыт служебный текст системы",
                                    {"filter": "output"}, meeting_id)
                built = now()
                self.s.update("meetings", meeting_id, protocol_md=protocol_md, protocol_built_at=built,
                              built_from=[s["name"] for s in srcs])
                # версия: прежняя остаётся в истории; модель — та, что написала текст (43, 47)
                wrote = budget.answered.get("protocol") or budget.answered.get("extract_tasks") or []
                if budget.answered.get("_external"):
                    # собран внешней моделью — строкой в системных сообщениях, в документе пометки нет (инструкция 14.10.26)
                    self.cards.open(project_id, "technical", f"Протокол встречи {meeting.get('date') or ''} собран внешней моделью",
                                    {"points": sorted(set(budget.answered["_external"]))}, meeting_id)
                n = self.s.q("SELECT COUNT(*) AS n FROM protocol_versions WHERE meeting_id=?", (meeting_id,))[0]["n"]
                self.s.insert("protocol_versions", meeting_id=meeting_id, version=n + 1, protocol_md=protocol_md,
                              model=", ".join(dict.fromkeys(wrote)), built_at=built)
        except Exception as e:  # всё откатилось — реестр не наполовину
            rep.status, rep.detail = "error", "Сбой при сохранении — изменения не применены."
            self.cards.open(project_id, "technical", "Сбой сохранения прогона", {"error": type(e).__name__},
                            meeting_id)
            return rep
        rep.tasks_added, rep.tasks_closed = len(added), closed
        if stopped is None and "ноль на шаге" in rep.tasks_by_steps:
            self.cards.open(project_id, "technical", "Сборка: задачи пропали между шагами",
                            {"detail": rep.tasks_by_steps}, meeting_id)
        rep.tasks_held = len(held) - doubt          # вне реестра: дубли и отсечённое; под вопросом — в реестре
        rep.tasks_doubt = doubt
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
        except Exception as e:  # любой сбой проверки не отменяет сохранённое; оператору — карточка (стенд 40)
            rep.findings = [{"issue": f"Проверка не выполнена: {type(e).__name__}", "severity": "minor"}]
            self.step_failed(project_id, meeting_id, "Проверка протокола", e)
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
        rep.step_calls = dict(budget.steps)
        if rep.status == "ok" and limited:
            rep.status = "ok_limited"         # сохранено, но часть остановлена пределом — не «успешный» (01/8)
        self.journal.write(run=meeting_id, status=rep.status, calls=rep.calls, step_calls=rep.step_calls,
                           cost_usd=rep.cost_usd,
                           added=rep.tasks_added, held=rep.tasks_held, closed=rep.tasks_closed,
                           dropped=rep.tasks_dropped, skipped_by_rule=rep.skipped_by_rule,
                           stopped_by=budget.stopped_by, stand=self.stand, closing_mentioned=closing_mentioned,
                           **({"polnota_rasshifrovki": rep.completeness} if rep.completeness else {}),
                           **({"tekst_po_zapisi": rep.text_check, "tekst_ubrano": rep.text_removed}
                              if rep.text_check else {}),
                           **({"zadachi_po_shagam": rep.tasks_by_steps} if rep.tasks_by_steps else {}),
                           answered_by={k: sorted(set(v)) for k, v in budget.answered.items() if not k.startswith("_")},
                           **self.tool_info)
        return rep

    # ---------------------------------------------------------------- помощники
    def _due_card(self, project_id: int, meeting_id: int, task_id: int, g, proposed: str, mdate: str | None) -> None:
        """Карточка «срок под вопросом» — те же текст и поля, что в Планёрке (92498b5): задача заведена без срока,
        предложенный моделью срок — на решение. «Подтвердить» ставит его в задачу."""
        md = lenient_date(mdate)
        word = self.theme.get("vocabulary.meeting", "Встреча")
        when = f"{md:%d.%m.%y}" if md else ""
        iso = lenient_date(proposed)
        evidence = (f"{word} {when}. Модель предложила срок {proposed}, но рядом с поручением в записи он не прозвучал "
                    "— задача заведена без срока." + (f" Цитата: «{(g.quote or '')[:300]}»" if g.quote else ""))[:2000]
        self.cards.open(project_id, "due_unconfirmed", f"Срок под вопросом: {g.description[:100]}",
                        {"task_id": task_id, "field": "due_date", "current_value": None,
                         "proposed_value": iso.isoformat() if iso else None, "proposed_text": proposed,
                         "source": "due_unconfirmed", "confidence": "low", "evidence_quote": evidence,
                         "quote": g.quote}, meeting_id)

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

    def _operativnye_po_sekretaryu(self, project_id: int, notes: list[dict]) -> dict:
        """Строка раздела «Оперативные задачи» протокола секретаря (заметки встречи) ставит пометку сама; ручное решение
        человека главнее (`tablica_zadach.отметить_по_секретарю`, как ERP 26.10.2026). Сбой разбора сохранение не роняет."""
        try:
            строки = [x for n in notes for x in tablica_zadach.строки_раздела_секретаря(n.get("text"))]

            def похожая(a: str, b: str) -> float:
                sa, sb = set(stems(_without_dates(a))), set(stems(_without_dates(b)))
                return max(coverage(sa, sb), coverage(sb, sa)) if sa and sb else 0.0
            return tablica_zadach.отметить_по_секретарю(self.s, строки, похожая=похожая, project_id=project_id)
        except Exception as exc:  # noqa: BLE001
            self.step_failed(project_id, None, "Пометка «оперативная» по протоколу секретаря", exc)
            return {}

    def _topic(self, meeting: dict) -> dict | None:
        """Тема планёрки встречи (как ERP 24.10.2026, перенос 27.10.2026): выключенная тема не действует."""
        from .topics import тема_встречи
        return тема_встречи(self.s, meeting)

    def _skeleton(self, meeting: dict) -> list[str]:
        """Разделы протокола: у темы со своей структурой — её разделы по порядку, иначе — разделы темы проекта."""
        tp = self._topic(meeting)
        try:
            secs = [s for s in json.loads((tp or {}).get("sections") or "[]") if str(s).strip()]
        except (TypeError, ValueError):
            secs = []
        return [str(s).strip() for s in secs] or list(self.theme["protocol_skeleton"])

    def _render_protocol(self, meeting: dict, sections: dict[str, str | None], added, closings, srcs,
                         removals=(), *, record: str | None = None, people=(), rep: RunReport | None = None,
                         base_kind: str = "transcript") -> str:
        """Документ для читателя — без системных пометок: модель, стенд, файлы, пределы и замечания
        уходят в карточки и журнал (правило владельца 13.10.26 для всех систем).

        С 27.10.2026 (перенос решений ERP 25–26.10.2026): каждое предложение разделов проверяется по записи
        (`tekst_po_zapisi`: без опоры, заглушки, утверждение из вопроса и повторы не пишутся; раздел без строк — не
        пишется), заглушка «Не обсуждалось» не ставится, длинные абзацы делятся (`korotkiy_protokol.разбить_длинные`);
        таблица задач — как у секретаря (`tablica_zadach`: семь колонок, «Поставленные на встрече» и «Оперативные
        задачи», горизонт двух встреч); снятые задачи в документ не идут (раздела «Снято по встрече» нет)."""
        th = self.theme
        date_s = meeting.get("date") or datetime.now().strftime("%Y-%m-%d")
        try:
            date_h = datetime.strptime(date_s, "%Y-%m-%d").strftime(th.get("formats.date", "%d.%m.%Y"))
        except ValueError:
            date_h = date_s
        out = [f"# {th.word('protocol')} {date_h}", ""]
        tp = self._topic(meeting)
        if tp:                                   # тема — в шапку протокола (как ERP)
            out += [f"Тема: {tp['name']}", ""]
        for sec in self._skeleton(meeting):
            body = sections.get(sec, "")
            if body is None:              # не собран (предел, потолок ответа) — пусто, причина в карточке
                out += [f"## {sec}", ""]
                continue
            if not (body or "").strip():  # пусто — раздел не пишется: заглушка «Не обсуждалось» — системное слово
                continue
            out += [f"## {sec}", body.strip(), ""]
        head = "\n".join(out)
        if record is not None:
            head, отчёт = tekst_po_zapisi.очистить(head, record, people)
            if rep is not None:
                rep.text_check = tekst_po_zapisi.строка_хода(отчёт)
                rep.text_removed = list(отчёт.get("предложения") or [])
        head = korotkiy_protokol.разбить_длинные(head).rstrip("\n")
        out = head.split("\n") + [""]
        откуда = "запись" if base_kind == SourceKind.TRANSCRIPT.value else "заметки"
        строки = tablica_zadach.строки_встречи(
            self.s, meeting,
            lambda t: due_text(t.get("due_date"), t.get("date_set"), t.get("due_kind")) or "", откуда)
        out += tablica_zadach.раздел_задач(строки)
        if closings:
            out += [f"## {th.word('closed_tasks')}", ""]
            for i, (_tid, q) in enumerate(closings, 1):
                out.append(f"{i}. {q.strip()}")
        return "\n".join(out).rstrip("\n") + "\n"
