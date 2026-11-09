# -*- coding: utf-8 -*-
"""Сведение задач в сборке и второй проход после дополнения формулировок (09.11.2026, встреча 9).

Повод: в протоколе 09.11 остались две пары дублей из одной цитаты. Правило `укрупнить` эти пары сводит, значит в
сборке оно либо получило другие тексты (до дополнения формулировок), либо не сработало. Здесь: (1) сборка на заглушке
модели сводит две почти одинаковые задачи без исполнителя в одну; (2) второй проход `применить` ловит пару, которая
стала похожей только после дополнения. Тексты вымышленные.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import ukrupnenie_sborka as сб
from meetflow.core.config import load_theme
from meetflow.core.gates import GateResult
from meetflow.core.pipeline import MeetingPipeline
from meetflow.core.types import TaskDraft

ЗАПИСЬ = (
    "[00:13:01] Орлова Анна: Надо посмотреть по заданию на перевозку, какие данные нужно вносить.\n"
    "[00:14:21] Орлова Анна: И сделать форму и текст штампа для водителей.\n"
)


def test_сборка_сводит_две_одинаковые_задачи_без_исполнителя(store, project, meeting, tmp_path):
    class Модель(MockLLM):
        def _extract(self, data):
            return {"tasks": [
                {"description": "Посмотреть по заданию на перевозку, какие данные нужно вносить",
                 "assignee": None, "line": 0},
                {"description": "Посмотреть по заданию на перевозку, какие данные нужны, чтобы вносились верно",
                 "assignee": None, "line": 0},
            ]}

        def _units(self, data):
            return {"items": []}

    p = MeetingPipeline(load_theme("it_product"), store, default_registry(), Модель(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="дубли" + str(meeting), local_asr=1,
                 meta=json.dumps({"voice_names": {}}, ensure_ascii=False), created_at="2026-11-09T10:00:00")
    p.run(project, meeting)
    задачи = store.q("SELECT description FROM tasks WHERE source_meeting_id=?", (meeting,))
    assert len(задачи) == 1, [t["description"] for t in задачи]


def test_второй_проход_ловит_похожие_после_дополнения(store):
    pid = store.insert("projects", name="Общие встречи", theme="it_product")
    mid = store.insert("meetings", project_id=pid, date="2026-11-09")
    d1 = TaskDraft("Посмотреть по заданию", None, ЗАПИСЬ.splitlines()[0])
    d2 = TaskDraft("Проверить, какие данные нужны", None, ЗАПИСЬ.splitlines()[0])
    g1 = GateResult(accepted=True, description=d1.description, quote=d1.quote, assignee=None, reasons=[])
    g2 = GateResult(accepted=True, description=d2.description, quote=d2.quote, assignee=None, reasons=[])
    первый = сб.применить(store, pid, mid, [(d1, g1), (d2, g2)], ЗАПИСЬ, set(), "2026-11-09")
    assert len(первый["planned"]) == 2, "до дополнения формулировки разные — не сводим"
    # дополнение формулировок по окну записи сделало их одной задачей
    d1 = replace(d1, description="Посмотреть по заданию на перевозку, какие данные нужно вносить")
    d2 = replace(d2, description="Посмотреть по заданию на перевозку, какие данные нужны, чтобы вносились верно")
    g1 = replace(g1, description=d1.description)
    g2 = replace(g2, description=d2.description)
    второй = сб.применить(store, pid, mid, [(d1, g1), (d2, g2)], ЗАПИСЬ, set(), "2026-11-09")
    assert len(второй["planned"]) == 1, "второй проход обязан свести пару после дополнения"


def test_второй_проход_есть_в_сборке():
    код = (Path(__file__).resolve().parents[1] / "meetflow" / "core" / "pipeline.py").read_text(encoding="utf-8")
    assert "Укрупнение после дополнения" in код
    assert "после дополнения:" in код
    assert код.count("ukrupnenie_sborka.применить(") >= 2, "первый проход до дополнения и второй после"
