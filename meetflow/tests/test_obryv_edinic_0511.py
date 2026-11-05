# -*- coding: utf-8 -*-
"""Обрыв единиц — неполная сборка: снятие не идёт (записка 05.11.2026)."""
from pathlib import Path

from meetflow.core.rebuild import drop_missing
from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store


def test_pipeline_считает_обрыв_единиц_неполной_сборкой():
    код = (Path(__file__).resolve().parents[1] / "meetflow" / "core" / "pipeline.py").read_text(encoding="utf-8")
    assert "incomplete=stopped is not None or limited" in код


def test_неполная_сборка_ничего_не_снимает():
    s = Store(":memory:")
    pid = s.insert("projects", name="П", theme="_default")
    mid = s.insert("meetings", project_id=pid, date="2026-11-05", label="В")
    tid = s.insert("tasks", project_id=pid, description="Согласовать график", status="active",
                   source_meeting_id=mid, source_quote="[00:00:01] цитата")
    res = drop_missing(s, TaskRegistry(s), mid, "2026-11-05", set(), incomplete=True)
    assert s.get("tasks", tid)["status"] == "active" and res["dropped"] == []
