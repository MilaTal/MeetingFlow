"""Заведение человека в «Команду» (письмо 13, 03.10.26): своя команда одним словом — отказ; совпадение фамилии — подтверждение.
Повод — Планёрка: 12 записей одним словом и дубль «Пересыпкин» / «Пересыпкин Сергей»."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ADMIN = {"X-User-Role": "super_admin"}   # заголовки HTTP — только ASCII, имя кириллицей не передаётся


@pytest.fixture
def client(tmp_path):
    # база и журнал — во временной папке теста; ":memory:" их приложение не держит между запросами
    import meetflow.web.app as app
    a = app.create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(a, raise_server_exceptions=False)
    pid = c.post("/api/projects", json={"name": "Проверка"}, headers=ADMIN).json()
    pid = pid.get("id", pid) if isinstance(pid, dict) else pid
    return c, pid


def people(c, pid):
    r = c.get(f"/api/projects/{pid}/people", headers=ADMIN).json()
    return r if isinstance(r, list) else r.get("people", [])


@pytest.mark.parametrize("bad", ["Пересыпкин", "Пересыпкин -", "Пересыпкин 1", "П. С."])
def test_own_team_one_word_rejected(client, bad):
    c, pid = client
    r = c.post(f"/api/projects/{pid}/people", json={"full_name": bad, "external": False}, headers=ADMIN)
    assert r.status_code == 422, (bad, r.status_code)
    assert not any(p["full_name"] == bad for p in people(c, pid))


def test_same_surname_needs_confirmation(client):
    c, pid = client
    assert c.post(f"/api/projects/{pid}/people", json={"full_name": "Пересыпкин Сергей"}, headers=ADMIN).status_code in (200, 201)
    r = c.post(f"/api/projects/{pid}/people", json={"full_name": "Пересыпкин Андрей"}, headers=ADMIN)
    assert r.status_code == 409
    assert sum("Пересыпкин" in p["full_name"] for p in people(c, pid)) == 1
    r = c.post(f"/api/projects/{pid}/people", json={"full_name": "Пересыпкин Андрей", "confirm_new": True}, headers=ADMIN)
    assert r.status_code in (200, 201)
    assert sum("Пересыпкин" in p["full_name"] for p in people(c, pid)) == 2


def test_exact_duplicate_refused_even_with_confirm(client):
    c, pid = client
    c.post(f"/api/projects/{pid}/people", json={"full_name": "Пересыпкин Сергей"}, headers=ADMIN)
    r = c.post(f"/api/projects/{pid}/people", json={"full_name": "пересыпкин  сергей", "confirm_new": True}, headers=ADMIN)
    assert r.status_code == 409
