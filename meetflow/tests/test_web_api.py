"""HTTP API: права проверяет сервер, человеческие ошибки, полный цикл."""
from urllib.parse import quote

import pytest
from conftest import TEAM, TRANSCRIPT
from fastapi.testclient import TestClient

from meetflow.web.app import create_app

ADMIN = {"X-User-Role": "project_admin"}
SUPER = {"X-User-Role": "super_admin"}
MEMBER = {"X-User-Role": "member"}


@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"))
    c = TestClient(app, raise_server_exceptions=False)
    pid = c.post("/api/projects", json={"name": "Пилот"}, headers=ADMIN).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{pid}/people", json={"full_name": n}, headers=ADMIN)
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=ADMIN).json()["id"]
    c.pid, c.mid = pid, mid
    return c


def _upload(c, name="Расшифровка 01.10.2026.txt", data=TRANSCRIPT.encode(), h=ADMIN):
    return c.post(f"/api/meetings/{c.mid}/sources", files={"file": (name, data)}, headers=h)


def test_health_and_theme(client):
    assert client.get("/health").json()["theme"] == "erp_rollout"
    assert client.get("/api/theme").json()["vocabulary"]["registry"] == "Реестр задач по проекту"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "app.js" in r.text


def test_member_cannot_admin(client):
    assert client.post("/api/projects", json={"name": "x"}, headers=MEMBER).status_code == 403
    assert client.post(f"/api/meetings/{client.mid}/run", headers=MEMBER).status_code == 403
    assert client.get(f"/api/projects/{client.pid}/cards", headers=MEMBER).status_code == 403
    assert client.get("/api/monitoring", headers=ADMIN).status_code == 403


def test_unknown_role_falls_back_to_member(client):
    assert client.post("/api/projects", json={"name": "x"}, headers={"X-User-Role": "god"}).status_code == 403


def test_person_requires_surname_and_name(client):
    r = client.post(f"/api/projects/{client.pid}/people", json={"full_name": "Настя"}, headers=ADMIN)
    assert r.status_code == 422


def test_full_cycle(client):
    assert _upload(client).json()["kind"] == "transcript"
    rep = client.post(f"/api/meetings/{client.mid}/run", headers=ADMIN).json()
    assert rep["status"] == "ok" and rep["tasks_added"] == 2      # + Кузнецов «не подтверждён» (документ 14)
    p = client.get(f"/api/meetings/{client.mid}/protocol").json()
    assert "Протокол встречи 01.10.2026" in p["markdown"] and isinstance(p["review_notes"], list)
    d = client.get(f"/api/meetings/{client.mid}/protocol.docx")
    assert d.status_code == 200 and d.content[:2] == b"PK"
    tasks = client.get(f"/api/projects/{client.pid}/tasks").json()
    assert tasks[0]["no"] == 1 and "project_id" not in tasks[0]


def test_bad_upload_human_message(client):
    r = _upload(client, "a.exe", b"MZ")
    assert r.status_code == 422 and "не поддерживается" in r.json()["detail"]
    r = _upload(client, "a.txt", b"")
    assert r.status_code == 422 and "пустой" in r.json()["detail"]


def test_upload_size_limit(client, monkeypatch):
    big = b"a" * (20 * 2 ** 20 + 10)
    assert _upload(client, "big.txt", big).status_code == 413


def test_status_change_rights(client):
    _upload(client)
    client.post(f"/api/meetings/{client.mid}/run", headers=ADMIN)
    tid = client.get(f"/api/projects/{client.pid}/tasks").json()[0]["id"]
    assert client.patch(f"/api/tasks/{tid}", json={"status": "done"}, headers=MEMBER).status_code == 403
    own = {"X-User-Role": "member", "X-User-Name": quote("Петрова Анастасия")}
    assert client.patch(f"/api/tasks/{tid}", json={"status": "done"}, headers=own).status_code == 200
    assert client.patch(f"/api/tasks/{tid}", json={"status": "bogus"}, headers=ADMIN).status_code == 422


def test_card_reject_becomes_rule_after_two(client):
    # карточка held_task задаётся явно: «Кузнецов» по документу 14 теперь заводится, а не задерживается
    st = client.app.state.store
    cid = st.insert("cards", project_id=client.pid, kind="held_task", title="Задача не заведена", status="open",
                    payload={"description": "проверить отчёт по браку", "reasons": ["no_verbatim_quote"]})
    card = {"id": cid}
    r = client.post(f"/api/cards/{card['id']}/resolve", json={"status": "rejected"}, headers=ADMIN).json()
    assert r["rule"] == "на паузе: 1 из 2"
    dec = client.get(f"/api/projects/{client.pid}/decisions", headers=ADMIN).json()
    assert len(dec) == 1 and dec[0]["decision"].startswith("rejected")


def test_monitoring_super_only_and_has_todo(client):
    m = client.get("/api/monitoring", headers=SUPER).json()
    # перевёрнут 15.10.26 (стенд 25): заглушек имён моделей в теме больше нет — список заглушек может быть пуст
    assert any(c["name"] == "whisper_local" for c in m["connectors"]) and isinstance(m["todo"], list)


def test_technical_errors_not_in_cards_tab(client):
    client.app.state.store.insert("cards", project_id=client.pid, kind="technical", title="сбой", status="open")
    cards = client.get(f"/api/projects/{client.pid}/cards", headers=ADMIN).json()
    assert all(c["kind"] != "technical" for c in cards)


def test_unhandled_error_is_human(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("секретная трассировка")
    monkeypatch.setattr(client.app.state.pipe, "run", boom)
    r = client.post(f"/api/meetings/{client.mid}/run", headers=ADMIN)
    assert r.status_code == 500 and "что-то пошло не так" in r.json()["detail"]
    assert "трассировка" not in r.text


def test_member_cannot_upload_source(client):
    """Перевёрнут: раньше закреплял загрузку участником (ревью). Решение ERP 12.09 —
    источники встречи загружает администратор; набор ролей — в теме permissions."""
    assert _upload(client, h=MEMBER).status_code == 403


def test_unknown_project_404(client):
    assert client.post("/api/projects/999/meetings", json={"date": "2026-10-01"}, headers=ADMIN).status_code == 404
    assert client.post("/api/projects/999/people", json={"full_name": "Игнатов Иван"}, headers=ADMIN).status_code == 404


def test_bad_status_filter_is_422_not_card_flood(client):
    for _ in range(5):
        assert client.get(f"/api/projects/{client.pid}/tasks?status=bogus").status_code == 422
    tech = client.app.state.store.q("SELECT * FROM cards WHERE kind='technical'")
    assert tech == []


@pytest.mark.parametrize("d", ["２０２６-１０-０１", "2026-02-31", "2026-1-1"])
def test_meeting_date_strict(client, d):
    assert client.post(f"/api/projects/{client.pid}/meetings", json={"date": d}, headers=ADMIN).status_code == 422


def test_same_server_error_one_card(client, monkeypatch):
    monkeypatch.setattr(client.app.state.pipe, "run", lambda *a, **k: 1 / 0)
    for _ in range(3):
        client.post(f"/api/meetings/{client.mid}/run", headers=ADMIN)
    assert len(client.app.state.store.q("SELECT * FROM cards WHERE kind='technical'")) == 1
