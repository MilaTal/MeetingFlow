"""Задачи прежней сборки встречи, не вошедшие в пересборку (решение владелицы 21.10.2026).

Правило перенесено из Планёрки (`peresborka.py`, коммит 21e280c): «при пересборке задачи не снимаются молча, по ним
заводятся карточки — снимай сразу при пересборке». Задача прежней сборки этой встречи, которой нет в новой, — «снято»
с причиной «не вошла в пересборку (дд.мм.гггг чч:мм)» и строкой в истории задачи; карточки нет.

Не снимаются:
  * задача, которую после сборки правил человек (статус, исполнитель, срок, формулировка, комментарий) — остаётся,
    по ней одна карточка «не вошла в пересборку, но правилась человеком»;
  * ничего, если извлечение было неполным (остановка по пределу, сбой шага): «не найдена в новом прогоне» не доказано.

Номера задач в протоколе MeetFlow — порядковые внутри встречи, поэтому правила Планёрки «перешла в протокол более
поздней встречи» и «строка протокола секретаря» здесь не применимы: переносится смысл — снимать только то, что новая
сборка действительно не вернула.
"""
from __future__ import annotations

from datetime import datetime

from .types import TaskStatus

FIELD = "rebuild_missing"
# Источники строк истории, которые пишет человек: правка в реестре, своя формулировка, срок, исполнитель, ответ карточкой
РУЧНЫЕ_ИСТОЧНИКИ = ("operator", "web_form", "member_note", "conflict_resolution", "task_conflict", "conflict")
ПРИЧИНА = "не вошла в пересборку ({when})"


def когда_сейчас() -> str:
    """Метка причины: местное время пересборки, «дд.мм.гггг чч:мм»."""
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def причина(when: str | None = None) -> str:
    return ПРИЧИНА.format(when=when or когда_сейчас())


def правилась_человеком(store, task_id: int) -> str:
    """Что в задаче после сборки менял человек — словами через запятую; пусто — не менял."""
    what: list[str] = []
    for h in store.q("SELECT source, evidence_quote FROM task_history WHERE task_id=? ORDER BY id", (task_id,)):
        if h["source"] not in РУЧНЫЕ_ИСТОЧНИКИ:
            continue
        text = (h["evidence_quote"] or "").strip().lower()
        if text.startswith("исполнитель"):
            what.append("исполнитель")
        elif text.startswith("срок"):
            what.append("срок")
        elif h["source"] == "member_note":
            what.append("комментарий")
        elif h["source"] in ("conflict_resolution", "task_conflict", "conflict"):
            what.append("ответ на карточку")
        elif text.startswith("своя формулировка"):
            what.append("формулировка")
        else:
            what.append("статус")
    return ", ".join(dict.fromkeys(what))


def drop_missing(store, reg, meeting_id: int | None, meeting_date: str | None, kept_ids: set[int], *,
                 incomplete: bool = False, when: str | None = None) -> dict:
    """Снять задачи прежней сборки, которых нет в новой. `kept_ids` — задачи этой встречи, которые новая сборка
    подтвердила (в том числе заведённые заново в этом прогоне). `incomplete` — извлечение неполное: ничего не снимаем."""
    when = when or когда_сейчас()
    out: dict = {"dropped": [], "kept": [], "when": when}
    if incomplete or meeting_id is None:
        return out
    kept = set(kept_ids)
    for t in store.q("SELECT id, description FROM tasks WHERE source_meeting_id=? AND status=?", 
                     (meeting_id, TaskStatus.ACTIVE.value)):
        if t["id"] in kept:
            continue
        edits = правилась_человеком(store, t["id"])
        if edits:
            out["kept"].append((dict(t), edits))
            continue
        reg.set_status(t["id"], TaskStatus.DROPPED, "rebuild", причина(when), meeting_date=meeting_date)
        out["dropped"].append(dict(t))
    return out
