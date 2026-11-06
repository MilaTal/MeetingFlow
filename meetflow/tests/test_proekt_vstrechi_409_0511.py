# -*- coding: utf-8 -*-
"""Чужой X-Project-Id на изменяющем запросе по встрече — 409 (Д2.4)."""
from fastapi.testclient import TestClient

W = {"X-Requested-With": "erp-webapp"}


def _env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app); st = app.state.store
    a = st.insert("accounts", login=None, full_name="Орлова Анна", role="super_admin", password_hash="", active=1, confirmed=1)
    p1 = st.insert("projects", name="Объект А", theme="erp_rollout", archived=0)
    p2 = st.insert("projects", name="Объект Б", theme="erp_rollout", archived=0)
    mid = st.insert("meetings", project_id=p1, date="2026-11-05", label="В")
    c.h = lambda pid: {**W, "X-User-Id": str(a), "X-Project-Id": str(pid)}
    return c, st, p1, p2, mid


def test_чужой_проект_на_пересборке_409(tmp_path):
    c, st, p1, p2, mid = _env(tmp_path)
    r = c.post(f"/meetings/{mid}/prepare-minutes?rebuild=1", headers=c.h(p2))
    assert r.status_code == 409 and "другому проекту" in r.text


def test_свой_проект_и_все_проекты_пропускаются(tmp_path):
    c, st, p1, p2, mid = _env(tmp_path)
    for pid in (p1, 0):
        r = c.post(f"/meetings/{mid}/prepare-minutes?rebuild=1", headers=c.h(pid))
        assert r.status_code != 409, r.text


import pytest


@pytest.mark.parametrize("метод,путь", [
    ("post", "/meetings/{mid}/sources/text"),
    ("post", "/meetings/{mid}/materials"),
    ("post", "/meetings/{mid}/prepare-plan"),
    ("post", "/meetings/{mid}/accept-draft"),
    ("post", "/meetings/{mid}/move-project"),
    ("post", "/meetings/{mid}/cancel-with-plan"),
    ("patch", "/meetings/{mid}/label"),
    ("patch", "/meetings/{mid}/date"),
    ("delete", "/meetings/{mid}"),
])
def test_чужой_проект_409_на_всех_путях(tmp_path, метод, путь):
    c, st, p1, p2, mid = _env(tmp_path)
    адрес = путь.format(mid=mid)
    вызов = getattr(c, метод)
    r = вызов(адрес, headers=c.h(p2)) if метод == "delete" else вызов(адрес, headers=c.h(p2), json={})
    assert r.status_code == 409, (метод, адрес, r.status_code, r.text[:120])


@pytest.mark.parametrize("метод,путь", [
    ("delete", "/meetings/{mid}/sources/1"),
    ("delete", "/meetings/{mid}/materials/1"),
    ("post", "/meetings/{mid}/units/extract"),
    ("post", "/meetings/{mid}/units/accept-all"),
    ("post", "/meetings/{mid}/minutes/point-edit"),
    ("post", "/meetings/{mid}/plan/point-edit"),
    ("post", "/meetings/{mid}/7/edits"),
    ("post", "/meetings/{mid}/confirm-date"),
    ("post", "/meetings/{mid}/restore"),
    ("post", "/meetings/{mid}/merge"),
    ("post", "/meetings/{mid}/unmerge"),
    ("post", "/meetings/{mid}/move-materials"),
    ("patch", "/meetings/{mid}/leader"),
    ("patch", "/meetings/{mid}/subproject"),
])
def test_409_остальные_пути(tmp_path, метод, путь):
    c, st, p1, p2, mid = _env(tmp_path)
    адрес = путь.format(mid=mid)
    вызов = getattr(c, метод)
    r = вызов(адрес, headers=c.h(p2)) if метод == "delete" else вызов(адрес, headers=c.h(p2), json={})
    assert r.status_code == 409, (метод, адрес, r.status_code, r.text[:120])


def test_общая_встреча_из_вкладки_проекта_409(tmp_path):
    c, st, p1, p2, _mid = _env(tmp_path)
    mid = st.insert("meetings", project_id=None, date="2026-11-05", label="Общая")
    r = c.post(f"/meetings/{mid}/prepare-minutes?rebuild=1", headers=c.h(p1))
    assert r.status_code == 409 and "другому проекту" in r.text


def test_общая_встреча_из_общих_и_всех_проектов_проходит(tmp_path):
    c, st, p1, p2, _mid = _env(tmp_path)
    общие = st.insert("projects", name="Общие встречи", theme="erp_rollout", archived=0, general=1)
    mid = st.insert("meetings", project_id=None, date="2026-11-05", label="Общая")
    for pid in (общие, 0):
        r = c.post(f"/meetings/{mid}/prepare-minutes?rebuild=1", headers=c.h(pid))
        assert r.status_code != 409, r.text
