"""Письмо 30 оркестратора meeting-registry (решение владельца 03.10.26, днём, заменяет утреннее
«задача после выбора»; владелец в сессии MeetFlow: «meeting-registry — оркестратор»).
Для бизнеса главное — чтобы задача не потерялась. Тесты написаны до правки.

1. Тёзки (ключ общий, имени нет): задача сразу без исполнителя + карточка «кто из них»; выбор ставит
   исполнителя в ту же задачу, новую не заводит.
2. Рабочий ключ, рядом чужая организация: задача сразу без исполнителя + «тот же или новый»; «это он»
   ставит исполнителя; «новый человек» — внешний с организацией и ролью, только подтверждением в
   карточке; без организации или роли не заводится, задача остаётся без исполнителя.
3. Решённое действие без названного исполнителя: задача с пустым исполнителем, без карточки;
   «не будем добавлять» задачей не становится."""
import json

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


class Say(MockLLM):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def _extract(self, data):
        return {"tasks": self.items}


@pytest.fixture
def env(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    for n in ("Гаврилов Павел", "Петрова Анастасия", "Петрова Мария", "Игнатов Иван"):
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n, "confirm_new": True}, headers=H)
    c.store, c.pipe = app.state.store, app.state.pipe
    return c


def run(c, line, items, d="2026-10-01"):
    c.pipe.gen = Say(items)
    mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": d}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H,
           files={"file": (f"t {d[8:]}.{d[5:7]}.{d[:4]}.txt", f"[00:01:00] {line}\n".encode())})
    return c.post(f"/api/meetings/{mid}/run", headers=H).json()


def tasks(c):
    return c.get(f"/api/projects/{c.pid}/tasks", headers=H).json()


def cards(c, kind):
    return [x for x in c.get(f"/api/projects/{c.pid}/cards", headers=H).json() if x["kind"] == kind]


# 1 — тёзки
def test_namesakes_task_first_then_choice_sets_assignee(env):
    line = "Гаврилов Павел: Петрова, подготовьте регламент приёмки до 10.10"
    r = run(env, line, [{"description": "Подготовить регламент приёмки", "assignee": "Петрова", "quote": line}])
    t = tasks(env)
    assert r["tasks_added"] == 1 and len(t) == 1 and t[0]["assignee"] is None
    card = cards(env, "assign_person")[0]
    assert card["payload"]["task_id"] == t[0]["id"] and len(card["payload"]["candidates"]) == 2
    mar = next(x for x in card["payload"]["candidates"] if x["name"] == "Петрова Мария")
    assert env.post(f"/api/cards/{card['id']}/resolve", json={"status": "accepted", "choice": str(mar["id"])},
                    headers=H).status_code == 200
    t = tasks(env)
    assert len(t) == 1 and t[0]["assignee"] == "Петрова Мария"          # та же задача, новой нет


# 2 — чужая организация
FOREIGN = "Гаврилов Павел: Подрядчик Игнатов из ТМК, пришлите график монтажа"


def test_foreign_org_task_first_this_is_him(env):
    run(env, FOREIGN, [{"description": "Прислать график монтажа", "assignee": "Игнатов", "quote": FOREIGN}])
    t = tasks(env)
    assert len(t) == 1 and t[0]["assignee"] is None
    card = cards(env, "assign_person")[0]
    assert card["payload"]["marks"]
    ivan = card["payload"]["candidates"][0]
    env.post(f"/api/cards/{card['id']}/resolve", json={"status": "accepted", "choice": str(ivan["id"])}, headers=H)
    assert tasks(env)[0]["assignee"] == "Игнатов Иван"


def test_foreign_org_new_person_needs_org_and_role(env):
    run(env, FOREIGN, [{"description": "Прислать график монтажа", "assignee": "Игнатов", "quote": FOREIGN}])
    card = cards(env, "assign_person")[0]
    url = f"/api/cards/{card['id']}/resolve"
    bad = env.post(url, json={"status": "accepted", "new_full_name": "Игнатов", "new_organization": "ТМК"}, headers=H)
    assert bad.status_code == 422 and tasks(env)[0]["assignee"] is None    # без роли — не заводится
    ok = env.post(url, json={"status": "accepted", "new_full_name": "Игнатов", "new_organization": "ТМК",
                             "new_role": "монтажник"}, headers=H)
    assert ok.status_code == 200 and tasks(env)[0]["assignee"] == "Игнатов (ТМК)"
    assert any(p["organization"] == "ТМК" for p in env.get(f"/api/projects/{env.pid}/people").json())


# 3 — решённое действие без исполнителя
def test_decided_action_without_assignee_is_task_without_card(env):
    line = "Гаврилов Павел: Решили добавить вид цены для продукции собственного производства"
    r = run(env, line, [{"description": "Добавить вид цены для продукции собственного производства",
                         "assignee": None, "quote": line}])
    t = tasks(env)
    assert r["tasks_added"] == 1 and t[0]["assignee"] is None
    assert not cards(env, "held_task") and not cards(env, "assign_person")


def test_negated_action_is_not_a_task(env):
    line = "Гаврилов Павел: Вид цены добавлять не будем"
    run(env, line, [{"description": "Добавить вид цены", "assignee": None, "quote": line}])
    assert tasks(env) == []


def test_prompt_returns_unassigned_actions():
    from meetflow.core.prompts import PromptBuilder, profile
    sysm, _ = PromptBuilder("", profile("generic")).extract_tasks(0, ["x"], [])
    assert "assignee null" in sysm and "только если исполнителя назвали" not in sysm
