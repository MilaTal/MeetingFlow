# -*- coding: utf-8 -*-
"""План встречи: что обсудить, решения прошлой встречи, открытые вопросы, задачи к встрече.

Перенесено по заданию владелицы 26.10.2026 («подготовка и протокол 1 в 1 как в ERP»). План собирается ДО
встречи, поэтому источник — не запись, а прошлый протокол, открытые пункты, задачи и материалы текущей встречи.
Разделы пишет модель, шапку и таблицы — код; без материалов и прошлого протокола план всё равно собирается,
но честно говорит, из чего он.
"""
from __future__ import annotations

from datetime import date as date_cls

from .store import Store

SECTIONS = ["Что обсудить", "Решения прошлой встречи", "Открытые вопросы", "Задачи к встрече"]


def _iso(value) -> str:
    if isinstance(value, date_cls):
        return value.isoformat()
    return str(value or "")[:10]


def collect(store: Store, meeting: dict) -> dict:
    """Что известно до встречи: прошлый протокол, открытые пункты, задачи, материалы."""
    project_id, mid = meeting.get("project_id"), meeting.get("id")
    day = _iso(meeting.get("date"))
    prev = store.q("SELECT date, protocol_md FROM meetings WHERE project_id=? AND id<>? AND date<? "
                   "AND protocol_md IS NOT NULL AND protocol_md<>'' ORDER BY date DESC LIMIT 1",
                   (project_id, mid, day))
    units = store.q("SELECT kind, text, planned_date FROM units WHERE project_id=? AND status IN ('open','active') "
                    "ORDER BY CASE kind WHEN 'open_question' THEN 0 WHEN 'decision' THEN 1 ELSE 2 END, id",
                    (project_id,))
    tasks = store.q("SELECT description, assignee, due_date, due_kind FROM tasks WHERE project_id=? AND status='active' "
                    "ORDER BY COALESCE(due_date,'9999-12-31'), id", (project_id,))
    materials = store.q("SELECT name, kind, text FROM sources WHERE meeting_id=? AND removed_at IS NULL "
                        "AND kind NOT IN ('transcript') ORDER BY id", (mid,))
    return {
        "previous_date": prev[0]["date"] if prev else "",
        "previous": (prev[0]["protocol_md"] or "") if prev else "",
        "units": units,
        "tasks": tasks,
        "materials": materials,
    }


def source_text(data: dict, limit: int = 60_000) -> str:
    """Сводка источников для модели — обычным текстом, без разметки."""
    parts: list[str] = []
    if data.get("previous"):
        parts.append(f"Прошлый протокол ({data.get('previous_date') or 'дата не указана'}):\n"
                     + str(data["previous"])[:limit // 2])
    if data.get("units"):
        parts.append("Открытые пункты:\n" + "\n".join(
            f"- {u.get('kind')}: {u.get('text')}" + (f" (срок {u.get('planned_date')})" if u.get("planned_date") else "")
            for u in data["units"]))
    if data.get("tasks"):
        parts.append("Задачи в работе:\n" + "\n".join(
            f"- {t.get('description')} — {t.get('assignee') or 'не назначен'}"
            + (f", срок {t.get('due_date')}" if t.get("due_date") else "") for t in data["tasks"]))
    if data.get("materials"):
        parts.append("Материалы к этой встрече:\n" + "\n".join(
            f"- {m.get('name')}: {str(m.get('text') or '')[:4000]}" for m in data["materials"]))
    return "\n\n".join(parts)[:limit]


def render(meeting: dict, sections: dict) -> str:
    """План в markdown: шапка с датой и темой, затем разделы в порядке SECTIONS."""
    day = _iso(meeting.get("date"))
    head = f"# План встречи {day[8:10]}.{day[5:7]}.{day[:4]}" if len(day) >= 10 else "# План встречи"
    topic = " ".join(str(meeting.get("topic") or "").split())
    lines = [head, "", f"Тема: {topic}" if topic else "Тема: без темы", ""]
    for name in SECTIONS:
        text = " ".join(str(sections.get(name) or "").split())
        lines.append(f"## {name}")
        lines.append(text or "—")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
