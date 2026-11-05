# -*- coding: utf-8 -*-
"""След задач (записка 05.11.2026): каждая заведённая задача имеет строку в tasks_trace.jsonl."""
import json

from conftest import TRANSCRIPT
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.config import load_theme
from meetflow.core.pipeline import MeetingPipeline
from meetflow.core.store import Store


def test_каждая_задача_имеет_строку_следа(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    pid = s.insert("projects", name="П", theme="it_product")
    mid = s.insert("meetings", project_id=pid, date="2026-11-05", label="В")
    ж = tmp_path / "llm_calls.jsonl"
    pipe = MeetingPipeline(load_theme("it_product"), s, default_registry(), MockLLM(), MockLLM(), str(ж))
    pipe.ingest(pid, mid, "t.txt", TRANSCRIPT.encode("utf-8"))
    pipe.run(pid, mid)
    строки = [json.loads(l) for l in (tmp_path / "tasks_trace.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    активные = {r["id"] for r in s.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='active'", (mid,))}
    видны = {r["task_id"] for r in строки if r["meeting_id"] == mid}
    assert активные and активные <= видны
    assert all(r["путь"] in ("новая", "прежняя") for r in строки if r["meeting_id"] == mid)
