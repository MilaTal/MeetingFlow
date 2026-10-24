"""Раздел 0 задания 24.10.2026: общая «Команда» (team_shared) — MeetFlow видит её только на чтение.

Общая база заводится Планёркой и ERP; в неё попадают только подтверждённые люди. Здесь проверяется:
счётчики (всего, внутренние, внешние), отметка «внешний», файл не меняется, путь по умолчанию — рядом
с базой голосов, понятные причины при отсутствии файла и схемы не по договору, доступ только супер-админу.
"""
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.team_shared import team_shared_state
from meetflow.web.app import create_app

SUPER = {"X-User-Role": "super_admin", "X-User-Name": "admin"}
ADMIN = {"X-User-Role": "project_admin"}


def _team_db(path, contract=True):
    con = sqlite3.connect(path)
    if contract:
        con.executescript("""
            CREATE TABLE people (
                uid TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                role TEXT, department TEXT, project_role TEXT, organization TEXT,
                is_external INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
        """)
        con.executemany(
            "INSERT INTO people (uid, full_name, role, department, organization, is_external, updated_at, updated_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [("u1", "Игнатов Иван", "Директор", "Руководство", None, 0, "2026-10-01T10:00:00", "planerka"),
             ("u2", "Петрова Анастасия", "", "Отдел закупок", None, 0, "2026-10-01T10:00:00", "erp"),
             ("u3", "Сидоров Пётр", "", "", "Склад-Сервис", 1, "2026-10-01T10:00:00", "planerka")])
    else:
        con.execute("CREATE TABLE people (uid TEXT PRIMARY KEY, full_name TEXT)")
    con.commit()
    con.close()


@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    return TestClient(app, raise_server_exceptions=False)


def test_team_shared_counts_and_read_only(tmp_path, monkeypatch):
    monkeypatch.delenv("TEAM_SHARED", raising=False)
    db = tmp_path / "team_shared.db"
    _team_db(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    st = team_shared_state(str(db))
    assert st["ok"] and st["enabled"]
    assert st["people"] == 3 and st["people_confirmed"] == 3
    assert st["internal"] == 2 and st["external"] == 1
    assert st["by_department"] == {"Руководство": 1, "Отдел закупок": 1}
    assert [p["full_name"] for p in st["people_list"]] == ["Игнатов Иван", "Петрова Анастасия", "Сидоров Пётр"]
    assert st["people_list"][2]["external"] is True
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before          # только чтение


def test_team_shared_not_set_missing_and_schema(tmp_path, monkeypatch):
    monkeypatch.delenv("TEAM_SHARED_PATH", raising=False)
    monkeypatch.delenv("VOICE_BASE_PATH", raising=False)
    assert "не задан" in team_shared_state(None)["detail"]
    assert "не найден" in team_shared_state(str(tmp_path / "нет.db"))["detail"]
    assert "папка" in team_shared_state(str(tmp_path))["detail"]
    bad = tmp_path / "bad.db"
    _team_db(bad, contract=False)
    st = team_shared_state(str(bad))
    assert not st["ok"] and "не по договору" in st["detail"]


def test_team_shared_defaults_next_to_voice_base(tmp_path, monkeypatch):
    monkeypatch.delenv("TEAM_SHARED_PATH", raising=False)
    db = tmp_path / "team_shared.db"
    _team_db(db)
    st = team_shared_state(voice_base_path=str(tmp_path / "voices.db"))
    assert st["ok"] and st["path"] == str(db)


def test_team_shared_off_switch(tmp_path, monkeypatch):
    db = tmp_path / "team_shared.db"
    _team_db(db)
    monkeypatch.setenv("TEAM_SHARED", "off")
    st = team_shared_state(str(db))
    assert not st["ok"] and not st["enabled"] and "выключена" in st["detail"]


def test_api_team_shared_super_admin_only(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TEAM_SHARED_PATH", str(tmp_path / "team_shared.db"))
    _team_db(tmp_path / "team_shared.db")
    assert client.get("/api/monitoring/team-shared", headers=ADMIN).status_code == 403
    r = client.get("/api/monitoring/team-shared", headers=SUPER)
    assert r.status_code == 200 and r.json()["people"] == 3 and r.json()["internal"] == 2
    pid = client.post("/api/projects", json={"name": "П"}, headers=SUPER).json()["id"]
    s = client.get(f"/api/projects/{pid}/settings", headers=SUPER).json()
    assert s["team_shared"]["people"] == 3
