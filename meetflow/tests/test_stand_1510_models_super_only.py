"""Решение владельца 15.10.26 (вечер, через «Мониторинг»): раздел «Модели» целиком, включая чтение списка подключений,
— только супер-администратору; остальным 403 на сервере. Сторож обходит ВСЕ маршруты приложения с «models» в пути —
новый маршрут без проверки роли его уронит."""
import pytest
from fastapi.testclient import TestClient

from meetflow.web.app import create_app


@pytest.fixture
def app_client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    return app, TestClient(app)


def test_every_models_route_is_super_admin_only(app_client):
    app, c = app_client
    routes = [(m, r.path) for r in app.routes if "models" in getattr(r, "path", "") for m in getattr(r, "methods", ())]
    assert len(routes) >= 8, routes
    for role in ("project_admin", "member", "director"):
        for method, path in routes:
            r = c.request(method, path, headers={"X-User-Role": role, "X-Requested-With": "MeetFlow"}, json={})
            assert r.status_code == 403, (role, method, path, r.status_code)


def test_monitoring_with_endpoints_is_super_admin_only(app_client):
    app, c = app_client
    for path in ("/api/monitoring", "/api/monitoring/models", "/api/monitoring/models/status"):
        assert c.get(path, headers={"X-User-Role": "project_admin"}).status_code == 403
    assert c.get("/api/monitoring/models", headers={"X-User-Role": "super_admin"}).status_code == 200
