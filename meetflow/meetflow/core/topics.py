# -*- coding: utf-8 -*-
"""Тема планёрки — основа из Проекта ERP (`services/tema_planerki.py`, решения владелицы 24.10.2026), перенос 27.10.2026.

Тема — самостоятельная сущность (`meeting_topics`). День недели темы ставит её по умолчанию всем встречам этого дня;
выбор человека на подготовке встречи сильнее («вручную», в том числе «без темы»). Разделы темы заменяют общий скелет
протокола, тема пишется в шапку протокола и плана. Выключенная тема не действует; удаления нет.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from .store import Store

ВРУЧНУЮ = "вручную"
ПО_ДНЮ = "день недели"


def _d(value) -> date | None:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def по_дню(store: Store, day: date | None) -> dict | None:
    if day is None:
        return None
    for t in store.q("SELECT * FROM meeting_topics WHERE COALESCE(is_active,1)=1 ORDER BY id"):
        try:
            days = [int(x) for x in json.loads(t.get("weekdays") or "[]")]
        except (TypeError, ValueError):
            days = []
        if day.isoweekday() in days:
            return t
    return None


def тема_встречи(store: Store, meeting: dict) -> dict | None:
    """Действующая тема встречи: выбранная человеком, иначе — по дню недели; «без темы» вручную — нет темы."""
    tid = meeting.get("topic_id")
    if tid:
        rows = store.q("SELECT * FROM meeting_topics WHERE id=?", (tid,))
        return rows[0] if rows and rows[0].get("is_active", 1) else None
    if (meeting.get("topic_source") or "") == ВРУЧНУЮ:
        return None
    return по_дню(store, _d(meeting.get("date")))


def в_словарь(t: dict) -> dict:
    j = lambda k: json.loads(t.get(k) or "[]") if isinstance(t.get(k), str) else (t.get(k) or [])  # noqa: E731
    return {"id": t["id"], "name": t.get("name") or "", "weekdays": [int(x) for x in j("weekdays")],
            "sections": j("sections"), "head_names": j("head_names"), "objects": j("objects"), "hint": t.get("hint") or "",
            "carry_same_topic": bool(t.get("carry_same_topic")), "is_active": bool(t.get("is_active", 1))}
