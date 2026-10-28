# -*- coding: utf-8 -*-
"""Снятые задачи не показываются нигде; пересборка возвращает снятую пересборкой задачу; задачи по шагам (перенос из
ERP 27.10.2026; DECISIONS ERP 26.10.2026 «прокрутка на месте …; снятые задачи не показываются нигде», «пересборка без
задач: снятая пересборкой задача, найденная снова, возвращается»).
"""
import re
from pathlib import Path

import pytest
from conftest import TEAM, TRANSCRIPT
from fastapi.testclient import TestClient

from meetflow.core import rebuild as rebuild_mod
from meetflow.connectors.llm_mock import MockLLM
from meetflow.core import tablica_zadach
from meetflow.core.types import TaskStatus
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}
FIRST = {"description": "подготовьте регламент склада до 10.10", "assignee": "Петрова Анастасия",
         "quote": "Петрова Анастасия, подготовьте регламент склада до 10.10", "line": 3}


class OnlyFirst(MockLLM):
    def _extract(self, data):
        return {"tasks": [FIRST]}


class Nothing(MockLLM):
    def _extract(self, data):
        return {"tasks": []}


# --- снятые не показываются ------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"))
    c = TestClient(app, raise_server_exceptions=False)
    c.pid = c.post("/api/projects", json={"name": "Пилот"}, headers=H).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n}, headers=H)
    c.mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{c.mid}/sources", files={"file": ("Расшифровка 01.10.2026.txt", TRANSCRIPT.encode())},
           headers=H)
    c.post(f"/api/meetings/{c.mid}/run", headers=H)
    return c


def test_снятая_не_отдаётся_списками_поиском_и_документом(client):
    tasks = client.get(f"/api/projects/{client.pid}/tasks?status=all", headers=H).json()
    drop = next(t for t in tasks if "регламент" in t["description"])
    assert client.patch(f"/api/tasks/{drop['id']}", json={"status": "dropped"}, headers=H).status_code == 200
    for st in ("active", "all", "dropped"):
        rows = client.get(f"/api/projects/{client.pid}/tasks?status={st}", headers=H).json()
        assert all(t["id"] != drop["id"] for t in rows), st
    assert client.get(f"/api/projects/{client.pid}/tasks?status=dropped", headers=H).json() == []
    assert all(t["id"] != drop["id"] for t in client.get(f"/api/meetings/{client.mid}/tasks", headers=H).json())
    found = client.get(f"/api/projects/{client.pid}/search?q=регламент", headers=H).json()
    assert "снято" not in str(found) and "регламент склада до 10.10 —" not in str(found)
    assert "tasks_dropped" not in client.get(f"/api/projects/{client.pid}/summary", headers=H).json()
    md = client.get(f"/api/meetings/{client.mid}/protocol", headers=H).json()["markdown"]
    assert "регламент склада" not in md and "| 1 | проверьте отчёт по браку" in md, "№ пересчитан без пропуска"
    docx = client.get(f"/api/meetings/{client.mid}/protocol.docx", headers=H)
    assert docx.status_code == 200 and "регламент склада".encode("utf-8") not in docx.content


def test_без_снятых_хранимое_не_меняется():
    md = ("| № | Задача | Статус |\n|---|---|---|\n| 1 | Снятая | в работе |\n| 2 | Живая | в работе |\n"
          "| 3 | Одинаковая | в работе |\n")
    out = tablica_zadach.без_снятых(md, {"Снятая", "Одинаковая"}, {"Одинаковая", "Живая"})
    assert "Снятая" not in out and "| 1 | Живая |" in out and "| 2 | Одинаковая |" in out


def test_экран_без_вкладки_снятых():
    """Снятые не показываются нигде (26.10.2026) — с 27.10.2026 реестр ERP 1 в 1: «Завершённые» — только выполненные,
    вида «Снятые» нет; прокрутка на месте — по строке действия (`запомнитьПрокрутку`)."""
    root = Path(__file__).resolve().parents[1] / "meetflow/web/static"
    reg, js = (root / "registry.js").read_text(encoding="utf-8"), (root / "app.js").read_text(encoding="utf-8")
    assert 'dropped: "Снятые"' not in reg and 'return t.status === "done" ? "выполнена" : "";' in reg
    assert "function запомнитьПрокрутку()" in js and "data-task-id" in js


# --- пересборка ------------------------------------------------------------------------------------------------------

def _build(make_pipe, store, project, gen=None):
    p = make_pipe(gen=gen)
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    rep = p.run(project, mid)
    return p, mid, rep


def test_снятая_пересборкой_возвращается_с_прежним_номером(make_pipe, store, project, monkeypatch):
    # 28.10.2026: снимается только задача без цитаты в записи — здесь цитаты «нет», как при сменившейся записи
    monkeypatch.setattr(rebuild_mod, "цитата_в_записи", lambda *a, **k: False)
    p, mid, _ = _build(make_pipe, store, project)
    first = next(t for t in store.q("SELECT * FROM tasks WHERE source_meeting_id=?", (mid,))
                 if t["description"] == FIRST["description"])
    p.gen = Nothing()
    p.run(project, mid)                                           # пересборка без поручений — снимает обе
    assert store.get("tasks", first["id"])["status"] == "dropped"
    p.gen = OnlyFirst()
    rep = p.run(project, mid)                                     # нашлась снова — та же задача, в работу
    t = store.get("tasks", first["id"])
    assert t["status"] == "active" and rep.tasks_returned == 1 and rep.tasks_added == 0
    assert store.q("SELECT COUNT(*) AS n FROM tasks WHERE description=?", (FIRST["description"],))[0]["n"] == 1
    hist = store.q("SELECT * FROM task_history WHERE task_id=? ORDER BY id DESC", (first["id"],))[0]
    assert "снова найдена в пересборке" in hist["evidence_quote"] and "прежним номером" in hist["evidence_quote"]
    md = store.get("meetings", mid)["protocol_md"]
    assert "подготовьте регламент склада до 10.10" in md
    assert "возвращено 1" in rep.tasks_by_steps


def test_снятая_человеком_не_возвращается(make_pipe, store, project):
    p, mid, _ = _build(make_pipe, store, project)
    first = next(t for t in store.q("SELECT * FROM tasks WHERE source_meeting_id=?", (mid,))
                 if t["description"] == FIRST["description"])
    p.reg.set_status(first["id"], TaskStatus.DROPPED, "web_form", by="админ")
    p.gen = OnlyFirst()
    rep = p.run(project, mid)
    assert store.get("tasks", first["id"])["status"] == "dropped" and rep.tasks_returned == 0
    assert "подготовьте регламент склада" not in store.get("meetings", mid)["protocol_md"]


def test_обычная_пересборка_не_теряет_строку_своей_задачи(make_pipe, store, project):
    p, mid, _ = _build(make_pipe, store, project)
    rep = p.run(project, mid)                                     # та же сборка ещё раз
    md = store.get("meetings", mid)["protocol_md"]
    assert "подготовьте регламент склада до 10.10" in md and "проверьте отчёт по браку" in md
    assert rep.tasks_added == 0


def test_задачи_по_шагам_в_итоге_сборки(make_pipe, store, project):
    _, _, rep = _build(make_pipe, store, project)
    assert re.search(r"задачи по шагам: от модели 2 → после стражей 2 → заведено в реестр 2 → "
                     r"строк в таблице документа 2 \(новых 2, возвращено 0\)", rep.tasks_by_steps), rep.tasks_by_steps
