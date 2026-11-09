# -*- coding: utf-8 -*-
"""Три правки 09.11.2026 по замечаниям владелицы.

1. «+ Новый проект» — всем вошедшим (было только суперу).
2. «Реестр задач» снова виден в меню проекта (встреча открывает его с фильтром по встрече).
3. «Подготовка встречи» не показывает прошедшую встречу с готовым протоколом.
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
    ids = {r: st.insert("accounts", full_name=f, role=r, active=1, confirmed=1)
           for f, r in (("Орлова Анна", "super_admin"), ("Сидорова Вера", "member"))}
    c.h = lambda role="member": {**W, "X-User-Id": str(ids[role])}
    return c


def test_участник_заводит_проект(env):
    r = env.post("/projects-list", json={"name": "Новый склад"}, headers=env.h("member"))
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Новый склад"
    assert "Новый склад" in [п["name"] for п in env.get("/projects-list", headers=env.h("member")).json()]


def test_без_входа_проект_не_заводится(env):
    assert env.post("/projects-list", json={"name": "Без входа"}, headers=W).status_code in (401, 403)


def test_кнопка_нового_проекта_для_всех():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert 'data-act="new">+ Новый проект</button>`' in js
    assert 'супер ? `<button type="button" class="pl-extra" data-act="new">' not in js


def test_реестр_задач_виден_в_меню_проекта():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    начало = js.index("const менюПроектаСтрокой")
    кусок = js[начало:js.index("const строка =", начало)]
    assert 'data-route="dashboard" href="#dashboard">Реестр задач</a>' in кусок


def test_подготовка_не_показывает_готовый_протокол():
    js = (СТАТИКА / "nav.js").read_text(encoding="utf-8")
    assert ">= сегодня && !m.has_minutes" in js, "встреча с готовым протоколом в «Подготовке» не показывается"
