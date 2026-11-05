# -*- coding: utf-8 -*-
"""«Команда» заводится администратором; пересчёт Сводки и Карты — не платный (решение 05.11.2026).

1. `POST /users` был открыт любому вошедшему, хотя экран «Команда» участнику скрыт. Теперь 403 участнику,
   201 администратору; первого человека заводит `seed_super`, исключения для чистой базы не нужно.
2. Пересчёт Сводки и Дорожной карты идёт кодом (`dogovorennosti.rebuild`), модель не вызывается; подписи
   обещали платный расчёт с перерывом — цена, длительность и `next_manual_at` убраны.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

W = {"X-Requested-With": "erp-webapp"}
СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    ids = {}
    for фио, роль in (("Орлова Анна", "super_admin"), ("Петров Илья", "project_admin"), ("Сидорова Вера", "member")):
        ids[роль] = st.insert("accounts", login=None, full_name=фио, role=роль, password_hash="", active=1, confirmed=1)
    c.h = lambda role="super_admin": {**W, "X-User-Id": str(ids[role]), "X-Project-Id": str(pid)}
    c.pid, c.st = pid, st
    return c


def test_участник_не_заводит_запись_команды(env):
    c, st = env, env.st
    было = st.q("SELECT COUNT(*) AS n FROM accounts")[0]["n"]
    r = c.post("/users", json={"full_name": "Смирнов Олег", "access_role": "member"}, headers=c.h("member"))
    assert r.status_code == 403
    assert st.q("SELECT COUNT(*) AS n FROM accounts")[0]["n"] == было
    assert not st.q("SELECT id FROM accounts WHERE full_name=?", ("Смирнов Олег",))


def test_администратор_заводит_запись_команды(env):
    c = env
    r = c.post("/users", json={"full_name": "Смирнов Олег", "access_role": "member"}, headers=c.h("project_admin"))
    assert r.status_code == 201
    assert any(u["full_name"] == "Смирнов Олег" for u in c.get("/users", headers=c.h()).json())


def test_пересчёт_не_обещает_платный_расчёт(env):
    c = env
    assert c.post("/project-status/refresh", json={}, headers=c.h("member")).status_code in (200, 204)
    st = c.get("/project-status/refresh-status", headers=c.h("member")).json()
    assert "next_manual_at" not in st


def test_в_подписях_нет_цены_пересчёта():
    t = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "платный пересчёт" not in t
    assert "платный расчёт" not in t
    assert "next_manual_at" not in t
