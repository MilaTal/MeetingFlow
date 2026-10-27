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
    # 27.10.2026, экраны ERP 1 в 1: у адресов фронта ERP (`/project-status/models*`) личность — X-User-Id учётной записи,
    # у прежних `/api/*` — X-User-Role; правило то же — всем, кроме супер-администратора, 403
    st = app.state.store
    ids = {role: st.insert("accounts", full_name=f"Проверка {role}", role=role, active=1, confirmed=1)
           for role in ("project_admin", "member")}
    for role in ("project_admin", "member", "director"):
        for method, path in routes:
            h = {"X-User-Role": role, "X-Requested-With": "MeetFlow"}
            if not path.startswith("/api/"):
                h = {"X-User-Id": str(ids.get(role, ids["member"])), "X-Requested-With": "erp-webapp"}
            r = c.request(method, path, headers=h, json={})
            assert r.status_code == 403, (role, method, path, r.status_code)


def test_monitoring_with_endpoints_is_super_admin_only(app_client):
    app, c = app_client
    for path in ("/api/monitoring", "/api/monitoring/models", "/api/monitoring/models/status"):
        assert c.get(path, headers={"X-User-Role": "project_admin"}).status_code == 403
    assert c.get("/api/monitoring/models", headers={"X-User-Role": "super_admin"}).status_code == 200
