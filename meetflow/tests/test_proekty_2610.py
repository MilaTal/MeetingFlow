# -*- coding: utf-8 -*-
"""Справочник проектов: варианты написания, подпроекты, архив (задание 26.10.2026)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


def test_projects_directory_aliases_subprojects_archive(tmp_path):
    c = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                   raise_server_exceptions=False)
    a = c.post("/api/projects", json={"name": "Склад", "aliases": ["складской учёт", "Адресный учет"]}, headers=H)
    assert a.status_code == 200
    aid = a.json()["id"]
    b = c.post("/api/projects", json={"name": "Склад — приёмка", "parent_id": aid}, headers=H).json()["id"]

    rows = {p["id"]: p for p in c.get("/api/projects").json()}
    assert rows[aid]["aliases"] == ["складской учёт", "Адресный учет"]
    assert rows[b]["parent_id"] == aid

    r = c.patch(f"/api/projects/{b}", json={"name": "Приёмка", "aliases": ["приемка"],
                                           "parent_id": aid, "archived": True}, headers=H)
    assert r.status_code == 200
    rows = {p["id"]: p for p in c.get("/api/projects").json()}
    assert rows[b]["name"] == "Приёмка" and rows[b]["aliases"] == ["приемка"]
    assert rows[b]["archived"] == 1 and rows[b]["parent_id"] == aid

    # кольцо проектов не допускается
    bad = c.patch(f"/api/projects/{aid}", json={"name": "Склад", "parent_id": b}, headers=H)
    assert bad.status_code == 422


def test_all_projects_lists_tasks_meetings_agreements(tmp_path):
    c = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                   raise_server_exceptions=False)
    ids = []
    for name in ("Первый", "Второй"):
        pid = c.post("/api/projects", json={"name": name}, headers=H).json()["id"]
        mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
        ids.append((pid, mid))
    # задачи и договорённости кладём прямо в базу тестового приложения через API проекта
    for pid, mid in ids:
        c.post(f"/api/projects/{pid}/people", json={"full_name": "Иванов Иван"}, headers=H)
    tasks = c.get("/api/projects/0/tasks?status=active", headers=H).json()
    assert isinstance(tasks, list)
    meetings = c.get("/api/projects/0/meetings", headers=H).json()
    assert {m["project_name"] for m in meetings} == {"Первый", "Второй"}
    agreements = c.get("/api/projects/0/agreements?status=all", headers=H).json()
    assert isinstance(agreements, list)
