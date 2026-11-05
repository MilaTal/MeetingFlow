# -*- coding: utf-8 -*-
"""Формы: текст по содержанию сохраняется, запрет только на одинаковое имя (записка 0237e67)."""
from fastapi.testclient import TestClient

W = {"X-Requested-With": "erp-webapp"}


def _клиент(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    a = st.insert("accounts", login=None, full_name="Орлова Анна", role="super_admin", password_hash="", active=1, confirmed=1)
    p1 = st.insert("projects", name="Объект А", theme="erp_rollout", archived=0)
    p2 = st.insert("projects", name="Объект Б", theme="erp_rollout", archived=0)
    c.h = {**W, "X-User-Id": str(a), "X-Project-Id": str(p1)}
    return c, st, p1, p2


def test_у_проекта_нет_поля_описания_и_сохранение_не_блокируется(tmp_path):
    # Поля описания у проекта нет вовсе: форма принимает имя, родителя и архив. Значит правило «в описании
    # чужой проект» здесь неприменимо — блокировать нечего.
    c, st, p1, _p2 = _клиент(tmp_path)
    r = c.patch(f"/projects-list/{p1}", json={"description": "Правило и проект «Объект Б»"}, headers=c.h)
    assert r.status_code == 200, r.text
    assert not hasattr(st.get("projects", p1), "description") or st.get("projects", p1).get("description") in (None, "")


def test_одинаковое_имя_по_прежнему_запрещено(tmp_path):
    c, _st, p1, _p2 = _клиент(tmp_path)
    assert c.patch(f"/projects-list/{p1}", json={"name": "Объект Б"}, headers=c.h).status_code == 409
