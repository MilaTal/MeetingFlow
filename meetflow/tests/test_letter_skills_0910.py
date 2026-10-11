"""Письмо ветки «AI агентные скилы» 09.10 23-51 — строки, применённые к MeetFlow (владелец 10.10.26: «делай всё»).

Строка 24: заголовок SKILL.md — строгий YAML; Claude Code прощал «: » без кавычек, строгий разбор — нет
(у скилла project-briefing так и было). Описание — до 1024 знаков.
Строка 10: при сбое формата ответа модели сырой ответ пишется в локальный журнал — без него гипотезу о причине
нечем проверить (у ветки «обрезка» оказалась кавычками внутри JSON)."""
import json
from pathlib import Path

import pytest
import yaml

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.types import LLMResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("skill", sorted(p for p in (ROOT / "skill").glob("*/SKILL.md")))
def test_row24_skill_header_is_strict_yaml(skill):
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "заголовок SKILL.md начинается с ---"
    head = yaml.safe_load(text.split("---", 2)[1])
    assert isinstance(head, dict) and head.get("name") and head.get("description")
    assert len(head["description"]) <= 1024


class Garbage(MockLLM):
    def complete(self, system, user, **kw):
        if "Схема" in system or "JSON" in system or "json" in system.lower():
            return LLMResult("Вот поручения: Игнатов — отчёт, без JSON", self.model)
        return super().complete(system, user, **kw)


def test_row10_raw_answer_is_logged_when_format_fails(store, project, make_pipe, tmp_path):
    p = make_pipe(gen=Garbage())
    p.journal.path = tmp_path / "logs" / "llm_calls.jsonl"
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p.ingest(project, mid, "t 01.10.2026.txt", "[00:01:00] Игнатов Иван: Петрова Анастасия, подготовьте отчёт\n".encode())
    p.run(project, mid)
    bad = tmp_path / "logs" / "bad_answers.jsonl"
    assert bad.exists(), "сырой ответ при сбое формата не записан"
    rows = [json.loads(x) for x in bad.read_text(encoding="utf-8").splitlines()]
    assert rows and "без JSON" in rows[0]["raw"] and rows[0]["error"] and rows[0]["purpose"]
    assert all(len(r["raw"]) <= 4000 for r in rows)
