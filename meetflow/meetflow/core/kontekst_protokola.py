# -*- coding: utf-8 -*-
"""Паспорт проекта для подсказки протокола MeetFlow (перенос решения владелицы 20.11.2026).

Зачем. Протокол MeetFlow собирается только из сегодняшней записи; прошлые встречи и открытые задачи в подсказку не
идут. Владелица решила дать модели структурный контекст: состояние проекта, открытые задачи, последние 1–3 решения
за 30 дней. Это фон, а не факты сегодняшней встречи.

Границы. Модуль только читает `tasks`, `units`, `projects`, `meetings`. Он не меняет реестр и не добавляет строки в
протокол. В таблицу задач MeetFlow по-прежнему попадают только задачи этой встречи (решение владелицы 09.11.2026),
поэтому фильтр «Только новые» здесь не нужен: перенесённых строк в протоколе нет.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

ДНЕЙ = 30
РЕШЕНИЙ = 3
ЗАДАЧ = 5
ПРЕДЕЛ = 6000
СТАТУС_ПОДТВЕРЖДЕНО = "подтверждено"
СТАТУС_УТОЧНЯЕТСЯ = "уточняется"


def _дата(значение) -> date | None:
    if not значение:
        return None
    if isinstance(значение, date):
        return значение
    try:
        return date.fromisoformat(str(значение)[:10])
    except ValueError:
        return None


def _сокр(текст, предел: int) -> str:
    т = " ".join(str(текст or "").split())
    return т if len(т) <= предел else т[:предел].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _семья(store, project_id: int | None) -> list[int]:
    if project_id is None:
        return []
    return [int(project_id)] + [int(r["id"]) for r in store.q(
        "SELECT id FROM projects WHERE parent_id=?", (project_id,))]


def _задачи(store, семья: list[int], встреча: dict, предел: int = ЗАДАЧ) -> list[dict]:
    if not семья:
        return []
    метки = ",".join("?" * len(семья))
    строки = [dict(r) for r in store.q(
        f"SELECT id, description, assignee, due_date, date_set, project_id FROM tasks "
        f"WHERE status='active' AND project_id IN ({метки}) ORDER BY id DESC LIMIT 100", tuple(семья))]
    строки.sort(key=lambda t: (_дата(t.get("due_date")) is None, _дата(t.get("due_date")) or date.max,
                               -int(t.get("id") or 0)))
    return строки[:предел]


def _решения(store, семья: list[int], встреча: dict, предел: int = РЕШЕНИЙ) -> list[dict]:
    if not семья:
        return []
    метки = ",".join("?" * len(семья))
    день = _дата(встреча.get("date")) or date.today()
    порог = день - timedelta(days=ДНЕЙ)
    строки = [dict(r) for r in store.q(
        f"SELECT u.id, u.text, u.kind, u.status, u.project_id, m.date AS mdate "
        f"FROM units u LEFT JOIN meetings m ON m.id=u.meeting_id "
        f"WHERE u.kind IN ('decision','agreement') AND u.status IN ('open','active') "
        f"AND u.project_id IN ({метки}) ORDER BY u.id DESC LIMIT 60", tuple(семья))]
    итог = []
    for р in строки:
        д = _дата(р.get("mdate"))
        if д is not None and д < порог:
            continue
        итог.append(р)
        if len(итог) >= предел:
            break
    return итог


def паспорт(store, project_id: int | None, встреча: dict, source_text: str = "", *,
            предел: int = ПРЕДЕЛ, задач: int = ЗАДАЧ, решений: int = РЕШЕНИЙ) -> str:
    """Готовый блок подсказки или пустая строка. Проект не определён — пусто (общие встречи не смешиваем)."""
    семья = _семья(store, project_id)
    if not семья:
        return ""
    задачи = _задачи(store, семья, встреча, предел=задач)
    решения = _решения(store, семья, встреча, предел=решений)
    if not задачи and not решения:
        return ""
    строки = ["### Паспорт проекта (30 дней; фон, не факты сегодняшней встречи)",
              "Эти строки — прошлое состояние и открытые задачи. Не переписывай их как сегодняшний факт; "
              "факты бери из записи встречи.", ""]
    if задачи:
        строки.append("Открытые задачи:")
        for т in задачи:
            срок = f", срок {_дата(т.get('due_date')):%d.%m.%Y}" if _дата(т.get("due_date")) else ""
            поставлена = f", поставлена {_дата(т.get('date_set')):%d.%m.%Y}" if _дата(т.get("date_set")) else ""
            строки.append(f"- №{т['id']} — {_сокр(т.get('description'), 180)} — "
                          f"{_сокр(т.get('assignee') or 'не назначен', 80)}{срок}{поставлена}")
    if решения:
        строки.append("")
        строки.append("Решения:")
        for р in решения:
            статус = СТАТУС_ПОДТВЕРЖДЕНО if (р.get("status") or "") == "active" else СТАТУС_УТОЧНЯЕТСЯ
            дата = _дата(р.get("mdate"))
            строки.append(f"- {_сокр(р.get('text'), 220)} — {статус}" + (f", {дата:%d.%m.%Y}" if дата else ""))
    текст = "\n".join(строки)
    return текст[:предел]
