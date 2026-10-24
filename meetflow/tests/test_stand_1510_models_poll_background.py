"""Находка стенда 12 (ERP, стенд 8020): экран мониторинга ждал опроса серверов моделей — при молчащем сервере
«Система» 12,2 с. В MeetFlow «Проверить связь» по всем точкам шло по очереди и синхронно (таймаут OpenRouter 900 с).
Теперь: итог опроса в памяти 20 с, обновление фоном, все точки разом, экран ждёт не больше 0,5 с — иначе прошлый итог
с возрастом. Тест написан до правки и падал."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.shared import model_routes as mr

SUPER = {"X-User-Role": "super_admin"}


@pytest.fixture
def slow(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"endpoints": {
        "a": {"kind": "openai", "url": "http://10.0.0.1:1234", "model": "ma"},
        "b": {"kind": "openai", "url": "http://10.0.0.2:1234", "model": "mb"},
        "c": {"kind": "ollama", "url": "http://localhost:11434", "model": "mc"}},
        "roles": {"generate": ["a", "b"], "verify": ["c"]}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    pings = []

    def ping(route, **kw):
        pings.append(route.name)
        time.sleep(1.0)                  # молчащий сервер
        return True, "ответ: да"
    monkeypatch.setattr(mr, "ping", ping)
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    return TestClient(app), pings


def test_screen_waits_at_most_half_a_second_and_polls_in_parallel(slow):
    c, pings = slow
    t0 = time.monotonic()
    r = c.get("/api/monitoring/models/status", headers=SUPER).json()
    assert time.monotonic() - t0 < 0.9, "экран ждал опроса"
    assert r["running"] and r["results"] == [] and r["age_sec"] is None
    time.sleep(1.4)                      # три точки по 1 с — разом, а не 3 с по очереди
    r = c.get("/api/monitoring/models/status", headers=SUPER).json()
    assert not r["running"] and {x["name"] for x in r["results"] if x["ok"]} == {"a", "b", "c"}
    assert r["age_sec"] is not None and r["age_sec"] < 20
    n = len(pings)
    c.get("/api/monitoring/models/status", headers=SUPER)
    assert len(pings) == n, "итог моложе 20 с — повторного опроса нет"


def test_status_is_super_admin_only(slow):
    c, _ = slow
    assert c.get("/api/monitoring/models/status", headers={"X-User-Role": "project_admin"}).status_code == 403
