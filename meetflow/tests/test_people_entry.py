"""Письмо 13 ветки meeting-registry (03.10.26): в Планёрке свою команду засорили
записи одним словом и дубль «Пересыпкин» / «Пересыпкин Сергей» — владелец
назвала это ошибкой и мусором. Проверка путей заведения человека в MeetFlow.

Путь в коде один — POST /api/projects/{pid}/people (плюс демо-команда с
вымышленными именами). Карточка «новый человек» никого не заводит сама: она
ведёт на форму «Команды». Правила:
- своя команда — два слова из букв (фамилия и имя), «Пересыпкин -» не проходит;
- новый человек сверяется с «Командой» до записи: тот же человек — отказ;
  совпала фамилия или ключ — 409 «тот же или новый?» с найденными, повтор
  с confirm_new=true — осознанное «это новый человек»;
- внешний — организация и роль; «Иван» из ТМК второй раз — отказ, из
  Газпрома — новый человек."""
import pytest
from fastapi.testclient import TestClient

from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


@pytest.fixture
def c(tmp_path):
    cl = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                    raise_server_exceptions=False)
    cl.pid = cl.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    cl.url = f"/api/projects/{cl.pid}/people"
    return cl


def _names(c):
    return sorted(p["full_name"] for p in c.get(c.url).json())


@pytest.mark.parametrize("name", ["Пересыпкин", "Пересыпкин -", "Пересыпкин  1", "П. С."])
def test_own_one_word_refused(c, name):
    assert c.post(c.url, json={"full_name": name}, headers=H).status_code == 422
    assert _names(c) == []


def test_same_person_twice_refused(c):
    assert c.post(c.url, json={"full_name": "Пересыпкин Сергей"}, headers=H).status_code == 200
    r = c.post(c.url, json={"full_name": "пересыпкин  сергей"}, headers=H)
    assert r.status_code == 409 and "уже есть" in r.json()["detail"]
    assert c.post(c.url, json={"full_name": "Пересыпкин Сергей", "confirm_new": True}, headers=H).status_code == 409
    assert _names(c) == ["Пересыпкин Сергей"]


def test_same_surname_asks_same_or_new(c):
    c.post(c.url, json={"full_name": "Пересыпкин Сергей"}, headers=H)
    r = c.post(c.url, json={"full_name": "Пересыпкин Андрей"}, headers=H)
    assert r.status_code == 409 and "Пересыпкин Сергей" in r.json()["detail"]
    assert _names(c) == ["Пересыпкин Сергей"]
    assert c.post(c.url, json={"full_name": "Пересыпкин Андрей", "confirm_new": True}, headers=H).status_code == 200
    assert _names(c) == ["Пересыпкин Андрей", "Пересыпкин Сергей"]


def test_unrelated_person_passes(c):
    c.post(c.url, json={"full_name": "Пересыпкин Сергей"}, headers=H)
    assert c.post(c.url, json={"full_name": "Гаврилов Павел"}, headers=H).status_code == 200


def test_external_same_org_refused_other_org_new(c):
    ext = {"full_name": "Иван", "external": True, "organization": "ТМК", "role": "инженер"}
    assert c.post(c.url, json=ext, headers=H).status_code == 200
    assert c.post(c.url, json=ext, headers=H).status_code == 409
    assert c.post(c.url, json={**ext, "organization": "Газпром"}, headers=H).status_code == 200
    assert _names(c) == ["Иван", "Иван"]
