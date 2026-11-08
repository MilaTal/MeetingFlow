# -*- coding: utf-8 -*-
"""«Пересобрать протокол» — только администратор и суперадминистратор (слово владелицы 08.11.2026).

Было 05.11: только админ; 06.11: всем ролям; 08.11: снова только админ и суперадмин, без обходных путей.
Тест перевёрнут дважды вместе с решением и держит все три роли.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from meetflow.web.app import create_app

КОРЕНЬ = Path(__file__).resolve().parents[1]


def test_маршрут_пересборки_требует_администратора():
    код = (КОРЕНЬ / "meetflow" / "web" / "erp" / "vstrechi.py").read_text(encoding="utf-8")
    assert "u = ctx.need_admin(request)" in код, "сервер обязан требовать администратора"
    assert "ctx.need_user(request) if rebuild" not in код, "обходного пути для участника быть не должно"


def _клиент(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    mid = st.insert("meetings", project_id=pid, date="2026-11-01", label="Встреча")
    роли = {}
    for роль in ("super_admin", "project_admin", "member"):
        роли[роль] = st.insert("accounts", login=None, full_name=роль, role=роль, password_hash="", active=1,
                               confirmed=1)
    return c, pid, mid, роли


def _заголовки(pid, uid):
    return {"X-Requested-With": "erp-webapp", "X-User-Id": str(uid), "X-Project-Id": str(pid)}


def test_участнику_пересборка_запрещена(tmp_path):
    c, pid, mid, роли = _клиент(tmp_path)
    r = c.post(f"/meetings/{mid}/prepare-minutes?rebuild=true", headers=_заголовки(pid, роли["member"]))
    assert r.status_code == 403, r.text


def test_администратору_и_суперадминистратору_пересборка_разрешена(tmp_path):
    c, pid, mid, роли = _клиент(tmp_path)
    for роль in ("project_admin", "super_admin"):
        r = c.post(f"/meetings/{mid}/prepare-minutes?rebuild=true", headers=_заголовки(pid, роли[роль]))
        assert r.status_code != 403, f"{роль}: {r.status_code} {r.text[:120]}"
