# -*- coding: utf-8 -*-
"""Неподтверждённый срок — задача без срока и карточка, как в Планёрке (решение владельца 12.10.26, письмо ветки
copilot 12.10 13-05). Раньше MeetFlow такой срок отбрасывал молча — поведение двух инструментов разошлось.
Отрицание и вопрос срока не дают: «к пятнице не успеем», «успеем до 5 октября?»."""
import pytest

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.morph import supported_due


class Say(MockLLM):
    def __init__(self, due, line):
        super().__init__()
        self.due, self.line = due, line

    def _extract(self, data):
        return {"tasks": [{"description": "Подготовить узлы подвеса и передать на склад", "assignee": "Сидоров",
                           "quote": self.line, "due_date": self.due}]}


def _run(store, project, make_pipe, due, line):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Say(due, line))
    p.ingest(project, mid, "t 01.10.2026.txt", f"[00:01:00] {line}\n".encode())
    p.run(project, mid)
    tasks = store.q("SELECT * FROM tasks WHERE source_meeting_id=?", (mid,))
    cards = [c for c in p.cards.list(project) if c["kind"] == "due_unconfirmed"]
    return p, tasks, cards


def test_подтверждённый_срок_ставится_без_карточки(store, project, make_pipe):
    _, tasks, cards = _run(store, project, make_pipe, "5 октября",
                           "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад до 5 октября.")
    assert len(tasks) == 1 and tasks[0]["due_date"] == "05.10.2026" and not cards


def test_срок_без_опоры_в_речи_задача_без_срока_и_одна_карточка(store, project, make_pipe):
    p, tasks, cards = _run(store, project, make_pipe, "10.10.2026",
                           "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад.")
    assert len(tasks) == 1 and not tasks[0]["due_date"]
    assert len(cards) == 1
    pl = cards[0]["payload"]
    assert pl["task_id"] == tasks[0]["id"] and pl["field"] == "due_date" and pl["proposed_value"] == "2026-10-10"
    assert pl["source"] == "due_unconfirmed" and pl["current_value"] is None
    # текст — как в карточке Планёрки
    assert "Модель предложила срок 10.10.2026, но рядом с поручением в записи он не прозвучал — задача заведена без " \
           "срока." in pl["evidence_quote"] and "01.10.26" in pl["evidence_quote"]


@pytest.mark.parametrize("line", [
    "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад. К пятнице не успеем.",
    "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад. Успеем к пятнице?",
])
def test_отрицание_и_вопрос_срока_не_дают(store, project, make_pipe, line):
    _, tasks, cards = _run(store, project, make_pipe, "к пятнице", line)
    assert len(tasks) == 1 and not tasks[0]["due_date"] and len(cards) == 1


def test_прибор_на_заведомом_ответе():
    assert supported_due("до пятницы", "к пятнице не успеем", "2026-10-01") is None
    assert supported_due("05.10.2026", "успеем до 5 октября?", "2026-10-01") is None
    assert supported_due("до пятницы", "Успеем к пятнице? Да, к пятнице сдадим.", "2026-10-01") == "до пятницы"
    assert supported_due("5 октября", "сдадим 5 октября", "2026-10-01") == "05.10.2026"


def test_подтвердить_в_карточке_ставит_срок(tmp_path):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c, H = TestClient(app), {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    pipe = app.state.pipe
    tid = pipe.reg.add(pid, "Подготовить узлы", "Сидоров Пётр", None, "", None, "2026-10-01")
    cid = pipe.cards.open(pid, "due_unconfirmed", "Срок под вопросом: Подготовить узлы",
                          {"task_id": tid, "field": "due_date", "current_value": None, "proposed_value": "2026-10-10",
                           "proposed_text": "10.10.2026", "source": "due_unconfirmed", "evidence_quote": "x"}, None)
    r = c.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=H)
    assert r.status_code == 200
    assert pipe.s.get("tasks", tid)["due_date"] == "10.10.2026"


# ---- относительные сроки (владелец 12.10.26, письмо ветки copilot 12.10 14-44: «да, для всех», как в ERP)

@pytest.mark.parametrize("due, line, expect, kind", [
    ("завтра", "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад завтра.", "02.10.2026", None),
    ("до пятницы", "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад до пятницы.", "02.10.2026", None),
    ("до конца месяца", "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад до конца месяца.",
     "31.10.2026", None),
    ("к следующему совещанию", "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад к следующему "
     "совещанию.", None, "к следующей встрече"),
])
def test_относительный_срок_в_дату(store, project, make_pipe, due, line, expect, kind):
    _, tasks, cards = _run(store, project, make_pipe, due, line)
    assert len(tasks) == 1 and tasks[0]["due_date"] == expect and tasks[0]["due_kind"] == kind and not cards


def test_фраза_важнее_даты_модели(store, project, make_pipe):
    _, tasks, cards = _run(store, project, make_pipe, "15.10.2026",
                           "Игнатов Иван: Сидоров, подготовьте узлы подвеса и передайте на склад до пятницы.")
    assert tasks[0]["due_date"] == "02.10.2026" and not cards


def test_оценка_в_показе():
    from meetflow.core.dates import due_text
    assert due_text("08.10.2026", "2026-10-01", "оценка") == "08.10.2026 (оценка)"
    assert due_text("01.10.2026", "2026-10-01", "оценка") == "сегодня (01.10.2026)"
