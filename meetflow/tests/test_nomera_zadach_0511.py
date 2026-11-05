# -*- coding: utf-8 -*-
"""Правка номеров при пересборке (записки 02c9e85, 95e43c3, 05.11.2026).

1. Работа, снятая человеком или по его решению, не возвращается ни своим, ни новым номером (3, 5, 6 встречи 15.10).
2. Та же работа, заведённая заново, пишется в прежнюю задачу: номер и история остаются; ручная правка
   формулировки не затирается, пустые исполнитель и срок берутся у новой.
"""
from meetflow.core.rebuild import drop_missing
from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store
from meetflow.core.types import TaskStatus


def _среда():
    s = Store(":memory:")
    pid = s.insert("projects", name="П", theme="_default")
    mid = s.insert("meetings", project_id=pid, date="2026-10-15", label="В")
    return s, TaskRegistry(s), pid, mid


def _задача(s, pid, mid, текст, статус="active", assignee=None):
    return s.insert("tasks", project_id=pid, description=текст, status=статус, source_meeting_id=mid,
                    source_quote="[00:00:01] цитата", assignee=assignee, date_set="2026-10-15")


def test_снятая_человеком_работа_не_возвращается_новым_номером():
    s, reg, pid, mid = _среда()
    старая = _задача(s, pid, mid, "Сделать сводную таблицу по проекту Курск-262", статус="dropped")
    s.insert("task_history", task_id=старая, old_status="active", new_status="dropped", source="operator",
             evidence_quote="слово владелицы: не возвращать", at="2026-11-04T10:00:00")
    новая = _задача(s, pid, mid, "Сделать сводную таблицу по проекту Курск-262 по всем спецификациям")
    res = drop_missing(s, reg, mid, "2026-10-15", {новая}, new_ids={новая})
    assert s.get("tasks", новая)["status"] == "dropped"
    причина = s.q("SELECT evidence_quote FROM task_history WHERE task_id=? ORDER BY id DESC LIMIT 1", (новая,))[0]["evidence_quote"]
    assert "снята человеком" in (причина or "")
    assert s.get("tasks", старая)["status"] == "dropped"          # прежняя не возвращена
    assert res.get("dropped_human")


def test_та_же_работа_пишется_в_прежнюю_задачу():
    s, reg, pid, mid = _среда()
    старая = _задача(s, pid, mid, "Изготовить эталонные образцы покрытия из композита")
    s.insert("task_history", task_id=старая, old_status=None, new_status="active", source="meeting", at="2026-10-15")
    новая = _задача(s, pid, mid, "Изготовить эталонные образцы покрытия из композита и отправить на покраску",
                    assignee="Белов Сергей")
    res = drop_missing(s, reg, mid, "2026-10-15", {новая}, new_ids={новая})
    assert s.get("tasks", старая)["status"] == "active"           # номер прежней сохранён
    assert "отправить на покраску" in s.get("tasks", старая)["description"]
    assert s.get("tasks", старая)["assignee"] == "Белов Сергей"   # пустое поле взято у новой
    assert s.get("tasks", новая)["status"] == "dropped"
    assert res["kept_number"][0]["id"] == старая


def test_ручная_правка_формулировки_не_затирается():
    s, reg, pid, mid = _среда()
    старая = _задача(s, pid, mid, "Сделать сводную таблицу по Курск-262")
    s.insert("task_history", task_id=старая, old_status="active", new_status="active", source="operator",
             evidence_quote="своя формулировка", at="2026-10-16T10:00:00")
    новая = _задача(s, pid, mid, "Сделать сводную таблицу по проекту Курск-262 по спецификациям")
    drop_missing(s, reg, mid, "2026-10-15", {новая}, new_ids={новая})
    assert s.get("tasks", старая)["description"] == "Сделать сводную таблицу по Курск-262"
