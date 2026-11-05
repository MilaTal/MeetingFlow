# -*- coding: utf-8 -*-
"""Подтверждение из «Разбора» доходит до «Команды» (находка администратора 05.11.2026).

Прежде карточка «Новый человек в «Команде»» подтверждала только `people`, а запись `accounts` оставалась
`confirmed=0`: «Разбор» карточку закрывал, «Команда» показывала «Не подтверждён», `GET /users` — `false`.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

W = {"X-Requested-With": "erp-webapp"}


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    админ = st.insert("accounts", login=None, full_name="Орлова Анна", role="super_admin", password_hash="",
                      active=1, confirmed=1)
    c.h = lambda: {**W, "X-User-Id": str(админ), "X-Project-Id": str(pid)}
    c.pid, c.st = pid, st
    return c


def _новая_карточка(env, имя: str, person_id: int) -> int:
    return env.st.insert("cards", project_id=env.pid, kind="confirm_person",
                         title=f"Новый человек в «Команде»: {имя} — подтвердите",
                         payload={"person_id": person_id, "full_name": имя, "task_id": None, "quote": ""},
                         status="open", created_at="2026-11-05T06:00:00")


def test_подтвердить_это_сотрудник_доходит_до_команды(env):
    c, st = env, env.st
    человек = st.insert("people", project_id=env.pid, full_name="Соколов Сергей", confirmed=0)
    st.insert("accounts", login=None, full_name="Соколов Сергей", role="member", password_hash="",
              active=1, confirmed=0, created_at="2026-11-05T05:00:00")
    card = _новая_карточка(env, "Соколов Сергей", человек)
    r = c.patch(f"/task-conflicts/{card}", json={"action": "confirm"}, headers=c.h())
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert st.get("people", человек)["confirmed"] == 1
    users = c.get("/users", headers=c.h()).json()
    запись = next(u for u in users if u["full_name"] == "Соколов Сергей")
    assert запись["is_confirmed"] is True
    assert st.q("SELECT confirmed FROM accounts WHERE full_name=?", ("Соколов Сергей",))[0]["confirmed"] == 1


def test_уточнить_фио_и_подтвердить_переносит_имя_и_подтверждает(env):
    c, st = env, env.st
    человек = st.insert("people", project_id=env.pid, full_name="Соколов Сергей", confirmed=0)
    st.insert("accounts", login=None, full_name="Соколов Сергей", role="member", password_hash="",
              active=1, confirmed=0, created_at="2026-11-05T05:00:00")
    card = _новая_карточка(env, "Соколов Сергей", человек)
    r = c.patch(f"/task-conflicts/{card}",
                json={"action": "custom", "custom_value": "Соколов Сергей Петрович", "project_role": "мастер"},
                headers=c.h())
    assert r.status_code == 200
    users = c.get("/users", headers=c.h()).json()
    запись = next(u for u in users if u["full_name"] == "Соколов Сергей Петрович")
    assert запись["is_confirmed"] is True and запись["access_role"] == "member"


def test_удалить_из_команды_убирает_запись(env):
    c, st = env, env.st
    человек = st.insert("people", project_id=env.pid, full_name="Соколов Сергей", confirmed=0)
    st.insert("accounts", login=None, full_name="Соколов Сергей", role="member", password_hash="",
              active=1, confirmed=0, created_at="2026-11-05T05:00:00")
    card = _новая_карточка(env, "Соколов Сергей", человек)
    assert c.patch(f"/task-conflicts/{card}", json={"action": "delete"}, headers=c.h()).status_code == 200
    assert not any(u["full_name"] == "Соколов Сергей" for u in c.get("/users", headers=c.h()).json())
