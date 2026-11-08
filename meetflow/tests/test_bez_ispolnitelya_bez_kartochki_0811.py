"""Решение владелицы `f531a8c`: без исполнителя карточку не заводить (недоделка аудита, п. 3).

«`require_assignee` у `it_product` оставить как есть» — настройка приходит из темы `_default`, где она `false`. Здесь
держится следствие: действие, решённое на встрече, но без названного исполнителя, заводится задачей с пустым
исполнителем и **без карточки** — решает оператор при разборе реестра, а не карточка «кто это».
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.config import load_theme
from meetflow.core.gates import GateConfig, TaskGate
from meetflow.core.people import Team
from meetflow.core.pipeline import MeetingPipeline
from meetflow.core.types import Person, SourceDoc, SourceKind, TaskDraft

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Нужно свести регламент склада к пятнице, исполнителя пока не назначили.\n"
          "[00:03:00] Петрова Анастасия: Хорошо.\n")


def test_в_теме_it_product_исполнитель_не_обязателен():
    тема = load_theme("it_product")
    cfg = GateConfig(**тема.get("gates", {}))
    assert cfg.require_assignee is False, "настройка приходит из _default и не меняется (решение f531a8c)"


def test_действие_без_исполнителя_задача_без_карточки():
    src = SourceDoc("t", SourceKind.TRANSCRIPT, ЗАПИСЬ)
    g = TaskGate(Team([Person("Игнатов Иван"), Person("Петрова Анастасия")]),
                 cfg=GateConfig(require_assignee=False)).check(
        TaskDraft("Свести регламент склада", None, line_no=1), src)
    assert g.accepted and g.assignee is None and g.pending is None, (g.reasons, g.pending)
    assert "no_assignee" not in g.reasons


def test_сборка_на_it_product_без_карточки_о_исполнителе(store, project, meeting, tmp_path):
    class Модель(MockLLM):
        def _extract(self, data):
            return {"tasks": [{"description": "Свести регламент склада", "assignee": None, "line": 1,
                               "due_date": "к пятнице"}]}

        def _units(self, data):
            return {"items": []}

    p = MeetingPipeline(load_theme("it_product"), store, default_registry(), Модель(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="б" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-06T10:00:00")
    p.run(project, meeting)
    задачи = store.q("SELECT description, assignee FROM tasks WHERE source_meeting_id=?", (meeting,))
    assert задачи and задачи[0]["description"].lower().startswith("свести регламент")
    assert задачи[0]["assignee"] is None
    карточки = store.q("SELECT kind, title FROM cards WHERE meeting_id=?", (meeting,))
    assert not [c for c in карточки if c["kind"] in ("assign_person", "confirm_person", "held_task", "task_doubt")], карточки
