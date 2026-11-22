# -*- coding: utf-8 -*-
"""Участники: голоса + однозначные обращения из контекста + ручной список (12.11.2026)."""
from __future__ import annotations

from meetflow.core.people import Person, Team
from meetflow.core.pipeline import MeetingPipeline

ЛЮДИ = [Person("Петрова Анастасия"), Person("Сидоров Пётр"), Person("Власова Марина Викторовна")]


def test_обращение_добавляет_участника():
    t = Team(ЛЮДИ)
    out = MeetingPipeline._с_контекстом(
        [], ["[00:01:00] Петрова Анастасия, подготовьте отчёт.", "[00:02:00] Власова Марина, посмотрите."], t)
    assert out == ["Петрова Анастасия", "Власова Марина Викторовна"]


def test_третье_лицо_и_отдел_не_добавляются():
    t = Team(ЛЮДИ)
    lines = ["[00:01:00] Петрова Анастасия сказала, что отчёт готов.", "[00:02:00] ПТО, проверьте пломбы."]
    assert MeetingPipeline._с_контекстом([], lines, t) == []


def test_ручной_список_добавляется_и_не_дублируется():
    out = MeetingPipeline._с_ручными(["Петрова Анастасия"], {"participants_manual": "Иванов Иван, Петрова Анастасия"})
    assert out == ["Петрова Анастасия", "Иванов Иван"]


def test_битый_ручной_список_не_идёт_в_участники():
    # Клиент прислал кириллицу не в UTF-8 — в базе остались «???? ??????». Это не человек.
    out = MeetingPipeline._с_ручными(["Петрова Анастасия"],
                                      {"participants_manual": "???????? ?????? ??????????"})
    assert out == ["Петрова Анастасия"]


def test_неоднозначные_имена_остаются_как_услышано():
    """Слово владелицы 20.11.2026: неоднозначное имя не выбрасывать, а показывать как услышано.
    «Мария» — одно имя, «Макарова» — две однофамилицы; отдел и «Говорящий 1-1» в участники не идут."""
    люди = ["Петрова Анастасия", "Макарова Мария", "Афанасьева Мария", "Макарова Алина"]
    слышали = ["Петрова Анастасия", "Мария", "Макарова", "Денис", "производство", "Говорящий 1-1", "Петрова"]
    услышано = MeetingPipeline._услышанные(слышали, люди)
    assert услышано == ["Мария", "Макарова", "Денис"]
    итог = MeetingPipeline._с_услышанными(["Петрова Анастасия"], услышано)
    assert итог == ["Петрова Анастасия", "Мария", "Макарова", "Денис"]


def test_ручной_список_через_api(tmp_path):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app

    H = {"X-User-Role": "project_admin"}
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.store = app.state.store
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-11-11"}, headers=H).json()["id"]
    r = c.patch(f"/api/meetings/{mid}/participants", json={"names": "Иванов Иван, Петрова Анастасия"}, headers=H)
    assert r.status_code == 200 and r.json()["participants_manual"] == "Иванов Иван, Петрова Анастасия"
    assert c.store.get("meetings", mid)["participants_manual"] == "Иванов Иван, Петрова Анастасия"


def test_api_не_принимает_имя_без_букв(tmp_path):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app

    H = {"X-User-Role": "project_admin"}
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.store = app.state.store
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-11-11"}, headers=H).json()["id"]
    r = c.patch(f"/api/meetings/{mid}/participants", json={"names": "???????? ??????"}, headers=H)
    assert r.status_code == 422
    assert not (c.store.get("meetings", mid).get("participants_manual") or "").strip()
