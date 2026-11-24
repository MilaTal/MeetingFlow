"""«Тест2_Митфлоу» (20.11.2026): подтверждение задачи администратором пересобирает протокол встречи-источника.

Проверяем не только кнопку реестра (`PATCH /tasks/{id}/status`), но и путь «Разбора»: карточки закрытия
(`closing_candidate`, `mass_closing` — частично или полностью), принятая отложенная задача (`held_task`),
подтверждение/снятие «под вопросом», возврат в работу и отметка исполнителя. Все пути должны поставить
встречу-источник в очередь один раз — `BuildQueue.enqueue` схлопывает повторы по встрече.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from meetflow.web.app import create_app

@pytest.fixture
def env(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.app, c.store = app, app.state.store
    c.pid = c.store.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    c.mid = c.store.insert("meetings", project_id=c.pid, date="2026-11-19", label="Встреча 19.11")
    aid = c.store.insert("accounts", login=None, full_name="Петров Илья", role="project_admin",
                         password_hash="", active=1, confirmed=1)
    c.h = {"X-User-Role": "project_admin", "X-User-Id": str(aid), "X-Project-Id": str(c.pid)}
    c.calls = []
    c.app.state.queue.enqueue = lambda *a, **kw: c.calls.append((a, kw)) or 1
    return c


def _task(env, **kw):
    vals = {"project_id": env.pid, "description": "Подготовить акт приёмки", "assignee": "Сидорова Вера",
            "status": "active", "date_set": "2026-11-19", "source_meeting_id": env.mid, "version": 1}
    vals.update(kw)
    return env.store.insert("tasks", **vals)


def _card(env, kind, payload, meeting_id=None, title="Карточка"):
    return env.store.insert("cards", project_id=env.pid, meeting_id=meeting_id, kind=kind, title=title,
                            payload=json.dumps(payload, ensure_ascii=False), status="open",
                            created_at="2026-11-20T09:00:00")


def _assert_rebuild(env):
    assert env.calls, "пересборка не поставлена"
    assert env.calls[-1][0][1] == env.mid and "пересборка" in env.calls[-1][0][2]


def test_closing_candidate_accept_enqueues_rebuild(env):
    tid = _task(env)
    cid = _card(env, "closing_candidate", {"task_id": tid, "quote": "Акт подписан"})
    r = env.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=env.h)
    assert r.status_code == 200 and env.store.get("tasks", tid)["status"] == "done"
    _assert_rebuild(env)


def test_mass_closing_accept_enqueues_one_rebuild_for_partial_and_full(env):
    ids = [_task(env, description=f"Задача {i}") for i in range(3)]
    cid = _card(env, "mass_closing", {"closings": [{"task_id": i, "quote": "готово", "status": "done"} for i in ids]})
    r = env.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=env.h)
    assert r.status_code == 200
    assert [env.store.get("tasks", i)["status"] for i in ids] == ["done", "done", "done"]
    assert len(env.calls) == 1 and env.calls[0][0][1] == env.mid


def test_mass_closing_reject_does_not_enqueue(env):
    tid = _task(env)
    cid = _card(env, "mass_closing", {"closings": [{"task_id": tid, "quote": "почти", "status": "done"}]})
    r = env.post(f"/api/cards/{cid}/resolve", json={"status": "rejected"}, headers=env.h)
    assert r.status_code == 200 and env.store.get("tasks", tid)["status"] == "active"
    assert env.calls == []


def test_held_task_accept_enqueues_rebuild(env):
    cid = _card(env, "held_task", {"description": "Подписать договор", "assignee": "Сидорова Вера",
                                   "quote": "Договор подписан, отправили."}, meeting_id=env.mid)
    r = env.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=env.h)
    assert r.status_code == 200
    assert env.store.q("SELECT id FROM tasks WHERE description='Подписать договор'")
    _assert_rebuild(env)


def test_under_question_confirm_and_drop_enqueue_rebuild(env):
    tid = _task(env, doubt_reason="без опоры в записи")
    r = env.post(f"/tasks/{tid}/under-question", json={"action": "confirm"}, headers=env.h)
    assert r.status_code == 200 and not env.store.get("tasks", tid).get("doubt_reason")
    _assert_rebuild(env)
    env.calls.clear()
    tid2 = _task(env, description="Сомнительная задача", doubt_reason="без опоры в записи")
    r2 = env.post(f"/tasks/{tid2}/under-question", json={"action": "drop"}, headers=env.h)
    assert r2.status_code == 200 and env.store.get("tasks", tid2)["status"] == "dropped"
    _assert_rebuild(env)


def test_revert_dropped_task_enqueues_rebuild(env):
    tid = _task(env, status="dropped", date_closed="2026-11-19")
    r = env.post(f"/tasks/{tid}/revert", headers=env.h)
    assert r.status_code == 200 and env.store.get("tasks", tid)["status"] == "active"
    _assert_rebuild(env)


def test_описание_ставит_пересборку(env):
    """Пример 19.11: №382/№386 уточнили в реестре — протокол должен пересобраться сам, без отдельного подтверждения."""
    tid = _task(env, description="Сделать единую этикетку (артикул, наименование)")
    r = env.patch(f"/tasks/{tid}/description", json={"description": "Сделать единую этикетку (артикул, штрих-код/QR-код, название)",
                                                     "version": 1}, headers=env.h)
    assert r.status_code == 200
    _assert_rebuild(env)


def test_ручной_список_участников_ставит_пересборку(env):
    r = env.patch(f"/api/meetings/{env.mid}/participants", json={"names": "Сидорова Вера, Мария"}, headers=env.h)
    assert r.status_code == 200
    _assert_rebuild(env)


def test_комментарий_к_задаче_ставит_пересборку(env):
    """Пункт 2 файлов 22.11: комментарий к задаче — тоже повод пересобрать протокол встречи-источника."""
    tid = _task(env)
    r = env.post(f"/api/tasks/{tid}/comment", json={"text": "Уточнил у Фадеевой: артикула достаточно"},
                 headers=env.h)
    assert r.status_code == 200
    _assert_rebuild(env)


def test_та_же_формулировка_не_плодит_пересборку(env):
    tid = _task(env, description="Формулировка без изменений")
    r = env.patch(f"/tasks/{tid}/description", json={"description": "Формулировка без изменений", "version": 1}, headers=env.h)
    assert r.status_code == 200 and not env.calls


def test_исполнитель_и_срок_ставят_пересборку(env):
    tid = _task(env)
    r = env.patch(f"/tasks/{tid}/responsible", json={"responsible_text": "Иванов Иван", "version": 1}, headers=env.h)
    assert r.status_code == 200 and env.calls
    env.calls.clear()
    r2 = env.patch(f"/tasks/{tid}/due", json={"due_date": "2026-12-01", "version": 2}, headers=env.h)
    assert r2.status_code == 200
    _assert_rebuild(env)


def test_проект_и_подпроект_ставят_пересборку(env):
    tid = _task(env)
    pid2 = env.store.insert("projects", name="Цех", theme="erp_rollout", archived=0)
    r = env.patch(f"/tasks/{tid}/project", json={"project_id": pid2, "version": 1}, headers=env.h)
    assert r.status_code == 200 and env.calls
    env.calls.clear()
    tid2 = _task(env, description="Задача в подпроекте")
    env.store.insert("projects", name="Площадка", theme="erp_rollout", archived=0, parent_id=env.pid)
    r2 = env.patch(f"/tasks/{tid2}/subproject", json={"subproject": "Площадка", "version": 1}, headers=env.h)
    assert r2.status_code == 200
    _assert_rebuild(env)


def test_оперативная_ставит_пересборку(env):
    tid = _task(env)
    r = env.post(f"/tasks/{tid}/operational", json={"value": True, "version": 1}, headers=env.h)
    assert r.status_code == 200
    _assert_rebuild(env)


def test_новая_задача_и_удаление_ставят_пересборку(env):
    r = env.post("/tasks", json={"description": "Новая задача встречи", "source_meeting_id": env.mid}, headers=env.h)
    assert r.status_code == 201
    _assert_rebuild(env)
    tid = r.json()["id"]
    env.calls.clear()
    version = env.store.get("tasks", tid)["version"]
    r2 = env.delete(f"/tasks/{tid}", params={"version": version}, headers=env.h)
    assert r2.status_code == 204
    _assert_rebuild(env)


def test_массовое_удаление_ставит_одну_пересборку(env):
    ids = [_task(env, description=f"Удалить {i}") for i in range(2)]
    r = env.post("/tasks/bulk-delete", json={"ids": ids}, headers=env.h)
    assert r.status_code == 200 and r.json()["deleted"] == 2
    assert len(env.calls) == 1 and env.calls[0][0][1] == env.mid


def test_старый_api_статуса_и_оперативной_ставит_пересборку(env):
    tid = _task(env)
    r = env.patch(f"/api/tasks/{tid}", json={"status": "done"}, headers=env.h)
    assert r.status_code == 200 and env.calls
    env.calls.clear()
    tid2 = _task(env, description="Вторая задача")
    r2 = env.post(f"/api/tasks/{tid2}/operational", json={"on": True}, headers=env.h)
    assert r2.status_code == 200
    _assert_rebuild(env)


def test_member_note_accept_done_enqueues_rebuild(env):
    tid = _task(env)
    cid = _card(env, "member_note", {"task_id": tid, "proposed": "done", "note": "Сделано"})
    r = env.patch(f"/task-conflicts/{cid}", json={"action": "accept"}, headers=env.h)
    assert r.status_code == 200 and env.store.get("tasks", tid)["status"] == "done"
    _assert_rebuild(env)
