# -*- coding: utf-8 -*-
"""Узкий порог задачи и «Возможные поручения» — основа из Проекта ERP (`services/vozmozhnye_porucheniya.py`, решение
владелицы 24.10.2026), перенос в MeetFlow 27.10.2026.

В протокол и реестр идут только поручения с адресатом (человек или отдел). Задача, которую сборка завела без исполнителя,
при включённом пороге уходит строкой «Возможных поручений»: формулировка, цитата, причина «нет адресата», состояние
«новое». Задача снимается (снятые не показываются нигде, решение 26.10.2026), строка ждёт человека: «В задачу» заводит
обычную задачу встречи, «Не задача» закрывает строку. Неразобранная строка истекает сама через `days` дней (0 — никогда).
Порог по умолчанию выключен — как в ERP: включает суперадминистратор в «Параметрах системы → Настройки».
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .store import Store, now

НЕТ_АДРЕСАТА = "нет адресата"
БЕЗ_РЕШЕНИЯ = "обсуждали без решения"
ВОПРОС_ПРОСЬБА = "вопрос-просьба"
СНЯТО_ПРОВЕРКОЙ = "снято проверкой"
ПРИЧИНЫ = (НЕТ_АДРЕСАТА, БЕЗ_РЕШЕНИЯ, ВОПРОС_ПРОСЬБА, СНЯТО_ПРОВЕРКОЙ)
НОВОЕ, В_ЗАДАЧУ, НЕ_ЗАДАЧА, ИСТЕКЛО = "новое", "в задачу", "не задача", "истекло"
СОСТОЯНИЯ = (НОВОЕ, В_ЗАДАЧУ, НЕ_ЗАДАЧА, ИСТЕКЛО)
СРОК_ПО_УМОЛЧАНИЮ = 7
ПРЕДЕЛ_ДНЕЙ = 365
ЗАГЛУШКИ = {"", "не назначен", "не назначено", "—", "-", "нет"}


class УжеРешено(ValueError):
    pass


def включён(store: Store) -> bool:
    return bool(store.get_setting("narrow_threshold", None, False))


def задать(store: Store, value: bool | None, by: str = "") -> None:
    store.set_setting("narrow_threshold", bool(value) if value is not None else None, None, by)


def срок_дней(store: Store) -> int:
    v = store.get_setting("possible_days", None, None)
    return СРОК_ПО_УМОЛЧАНИЮ if v is None else int(v)


def есть_адресат(assignee: str | None) -> bool:
    return (assignee or "").strip().lower() not in ЗАГЛУШКИ


def разделить_после_сборки(store: Store, reg, project_id: int, meeting_id: int, начало: str) -> int:
    """Порог включён: задачи этой сборки без адресата — в «Возможные поручения» (задача снимается). Возвращает число строк."""
    if not включён(store):
        return 0
    m = store.get("meetings", meeting_id) or {}
    born = {h["task_id"] for h in store.q("SELECT task_id FROM task_history WHERE source='meeting' AND old_status IS NULL "
                                          "AND at>=?", (начало,))}
    moved = 0
    for t in store.q("SELECT * FROM tasks WHERE project_id=? AND source_meeting_id=? AND status='active'", (project_id, meeting_id)):
        if t["id"] not in born or есть_адресат(t.get("assignee")):
            continue
        store.insert("possible_assignments", project_id=project_id, meeting_id=meeting_id, meeting_date=m.get("date"),
                     text=t["description"], quote=t.get("source_quote") or "", responsible="", due=t.get("due_date") or "",
                     reason=НЕТ_АДРЕСАТА, state=НОВОЕ, created_at=now())
        from .types import TaskStatus
        reg.set_status(t["id"], TaskStatus.DROPPED, "operator", "не прошла порог: нет адресата — в «Возможные поручения»",
                       by="система")
        moved += 1
    return moved


def истечь(store: Store, today: date | None = None) -> int:
    days = срок_дней(store)
    if days <= 0:
        return 0
    edge = (datetime.combine(today or date.today(), datetime.min.time()) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = store.q("SELECT id FROM possible_assignments WHERE state=? AND created_at<?", (НОВОЕ, edge))
    for r in rows:
        store.update("possible_assignments", r["id"], state=ИСТЕКЛО, decided_by="система", decided_at=now())
    return len(rows)


def в_словарь(r: dict) -> dict:
    return {"id": r["id"], "meeting_id": r.get("meeting_id"), "meeting_date": (r.get("meeting_date") or "")[:10] or None,
            "description": r.get("text") or "", "quote": r.get("quote") or "", "quote_ref": r.get("quote_ref") or "",
            "responsible_heard": r.get("responsible") or "", "due_heard": r.get("due") or "", "reason": r.get("reason") or "",
            "state": r.get("state") or НОВОЕ, "task_id": r.get("task_id"), "decided_by": r.get("decided_by") or "",
            "decided_at": (r.get("decided_at") or "")[:16] or None, "project_id": r.get("project_id")}


def проверить_открыта(r: dict) -> None:
    if (r.get("state") or НОВОЕ) != НОВОЕ:
        raise УжеРешено(f"Строка уже разобрана: «{r['state']}»" + (f" ({r['decided_by']})" if r.get("decided_by") else "")
                        + ". Обновите список")


def не_задача(store: Store, r: dict, by: str) -> None:
    проверить_открыта(r)
    store.update("possible_assignments", r["id"], state=НЕ_ЗАДАЧА, decided_by=by, decided_at=now())


def в_задачу(store: Store, reg, r: dict, by: str, *, description: str | None = None, responsible: str | None = None,
             due: str | None = None) -> int:
    проверить_открыта(r)
    text = (description or "").strip() or r.get("text") or ""
    tid = reg.add(r["project_id"], text, (responsible or "").strip() or None, None, r.get("quote") or "", due,
                  (r.get("meeting_date") or "")[:10] or None)
    store.update("tasks", tid, source_meeting_id=r.get("meeting_id"))
    reg._history(tid, "active", "active", "web_form",
                 f"Заведена из «Возможных поручений»: причина «{r.get('reason')}». Цитата: «{r.get('quote') or ''}»", by)
    store.update("possible_assignments", r["id"], state=В_ЗАДАЧУ, task_id=tid, decided_by=by, decided_at=now())
    return tid
