# -*- coding: utf-8 -*-
"""Паспорт проекта MeetFlow (решение владелицы 20.11.2026): только свои задачи проекта, 1–3 решения, два статуса."""
from meetflow.core import kontekst_protokola as k
from meetflow.core.store import Store


def _store():
    s = Store(":memory:")
    s.insert("projects", name="Проект", theme="", aliases="[]", active=1, archived=0)
    s.insert("meetings", project_id=1, date="2026-11-19", label="Встреча")
    s.insert("tasks", project_id=1, description="Открытая задача", assignee="Попков", status="active",
             date_set="2026-11-10")
    s.insert("units", meeting_id=1, project_id=1, kind="decision", text="Решение проекта", status="active")
    s.insert("units", meeting_id=1, project_id=1, kind="decision", text="Спорное решение", status="open")
    return s


def test_паспорт_берёт_задачи_и_два_статуса():
    текст = k.паспорт(_store(), 1, {"id": 1, "date": "2026-11-20"}, "Проект")
    assert "Открытая задача" in текст
    assert "Решение проекта — подтверждено" in текст
    assert "Спорное решение — уточняется" in текст


def test_общая_встреча_без_проекта_не_смешивается():
    assert k.паспорт(_store(), None, {"id": 1, "date": "2026-11-20"}, "Проект") == ""
