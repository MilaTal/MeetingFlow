# -*- coding: utf-8 -*-
"""План встречи: сборка до встречи из прошлого протокола, открытых пунктов, задач и материалов."""
from __future__ import annotations

from meetflow.core import plan


def test_plan_collect_and_render(store, project, make_pipe):
    prev = store.insert("meetings", project_id=project, date="2026-09-24",
                        protocol_md="# Прошлый протокол\n\nРешили: сделать образцы.")
    cur = store.insert("meetings", project_id=project, date="2026-10-01", topic="Склад")
    store.insert("units", project_id=project, meeting_id=cur, kind="open_question",
                 text="Кто принимает изделия?", status="open")
    store.insert("tasks", project_id=project, description="Сделать образцы", assignee="Иванов Иван",
                 status="active", due_date="2026-10-05")
    store.insert("sources", meeting_id=cur, name="материалы.txt", kind="other", text="План склада")
    data = plan.collect(store, store.get("meetings", cur))
    assert data["previous"] and "образцы" in data["previous"]
    assert data["units"] and data["tasks"] and data["materials"]
    text = plan.source_text(data)
    assert "Прошлый протокол" in text and "Сделать образцы" in text and "План склада" in text
    md = plan.render(store.get("meetings", cur), {"Что обсудить": "Склад", "Задачи к встрече": "—"})
    assert md.startswith("# План встречи 01.10.2026") and "Тема: Склад" in md
    assert "## Что обсудить" in md and "## Открытые вопросы" in md


def test_build_plan_one_call(store, project, make_pipe):
    store.insert("meetings", project_id=project, date="2026-09-24", protocol_md="# Прошлый протокол")
    cur = store.insert("meetings", project_id=project, date="2026-10-01")
    pipe = make_pipe()
    out = pipe.build_plan(project, cur)
    assert out["calls"] == 1 and out["cost_usd"] == 0.0
    assert "## Что обсудить" in out["markdown"] and "## Задачи к встрече" in out["markdown"]
    saved = store.get("meetings", cur)
    assert saved["plan_md"] == out["markdown"] and saved["plan_built_at"]
