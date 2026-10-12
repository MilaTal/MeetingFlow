# -*- coding: utf-8 -*-
"""Срок «сегодня (дд.мм.гггг)» — правило владельца 12.10.26, одно для Планёрки, Проекта ERP и MeetFlow.

«Срок надо ставить всегда, если есть инфо или упоминания об этом. Если была инфо „сегодня“ во время планёрки, то надо
указать в протоколе — „сегодня“ и дату планёрки, чтобы не ошибиться никому». До правки MeetFlow хранил прозвучавшее
«сегодня» голым словом: без даты оно не попадало в просрочку и не читалось через неделю. Теперь срок — дата встречи,
а показ — «сегодня (дата)». Срок раньше даты постановки сохраняется как есть и помечается."""
from pathlib import Path

from meetflow.core.dates import due_text
from meetflow.core.morph import supported_due

JS = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static" / "app.js"


def test_прозвучавшее_сегодня_становится_датой_встречи():
    assert supported_due("сегодня", "Игнатов, отправьте акт сегодня", "2026-10-05") == "05.10.2026"
    assert supported_due("до конца дня", "сегодня до конца дня пришлите", "2026-10-05") == "05.10.2026"


def test_сегодня_без_опоры_в_речи_не_принимается():
    assert supported_due("сегодня", "отправьте акт завтра", "2026-10-05") is None
    assert supported_due("сегодня", "Игнатов, отправьте акт сегодня", None) == "сегодня"     # без даты встречи — как есть


def test_показ_срока():
    assert due_text("05.10.2026", "2026-10-05") == "сегодня (05.10.2026)"
    assert due_text("2026-10-05", "2026-10-05") == "сегодня (05.10.2026)"
    assert due_text("09.10.2026", "2026-10-05") == "09.10.2026"
    assert due_text("03.10.2026", "2026-10-05") == "03.10.2026 (раньше даты постановки — как в источнике)"
    assert due_text("к следующей встрече", "2026-10-05") == "к следующей встрече"
    assert due_text(None, "2026-10-05") == ""


def test_реестр_показывает_due_text():
    assert "t.due_text || t.due_date" in JS.read_text(encoding="utf-8")


def test_api_отдаёт_сегодня_и_просрочку(tmp_path):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    H = {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    app.state.pipe.reg.add(pid, "Отправить акт", "Игнатов Иван", None, "", "05.10.2025", "2025-10-05")
    rows = c.get(f"/api/projects/{pid}/tasks", headers=H).json()
    assert rows[0]["due_text"] == "сегодня (05.10.2025)" and rows[0]["overdue"] is True    # просрочка настоящая
