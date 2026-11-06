"""Системные параметры и мониторинг — как в Проекте ERP и Планёрке (владелец 11.10.26).

Вход по паролю (выключен по умолчанию; включить — подтвердив учётную запись супер-администратора; блокировка после
пяти неверных паролей; защитный заголовок), «Мониторинг RealTime» (службы «живо / нет / выкл.», папка «завис»),
«Параметры системы» (системные сообщения, ожидает ввода, состояние базы, диск и копии, пороги)."""
from datetime import date, datetime, timedelta

import pytest
from conftest import TEAM, TRANSCRIPT
from fastapi.testclient import TestClient

from meetflow.web.app import create_app

SUPER = {"X-User-Role": "super_admin", "X-User-Name": "admin"}
CSRF = {"X-Requested-With": "MeetFlow"}
PASSWORD = "пароль-для-теста"   # тестовое значение учётной записи стенда


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("MEETFLOW_WATCH_INTERVAL_SEC", raising=False)
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    app.state.accounts.save("admin", "Админ Супер", "super_admin", PASSWORD)
    c.pid = c.post("/api/projects", json={"name": "Пилот"}, headers=SUPER).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n}, headers=SUPER)
    return c


# ---------------------------------------------------------------- вход по паролю
def test_login_is_off_by_default_and_headers_work(client):
    """Перевёрнуто 06.11.2026 (решение владелицы, файл 20, вопрос 5): режим входа ядра `/api/auth/mode` закрыт — режим
    один, у слоя «Команды» (`/auth/mode`)."""
    assert client.get("/api/auth/mode").status_code == 404
    assert client.get("/auth/mode").json()["auth_required"] is False
    assert client.get("/api/monitoring/live", headers=SUPER).status_code == 200


W = {"X-Requested-With": "erp-webapp"}


def test_old_core_login_is_closed(client):
    """Перевёрнуто 06.11.2026 (вопрос 5): прежде вход ядра `/api/auth/login` (8 знаков, 15 минут, без общего пароля) и
    выключатель `/api/auth/mode` проверялись здесь. Через них участник с личным паролем и внешний обходили правила
    входа — адреса закрыты. Ни с каким паролем и заголовком они не отвечают."""
    for body in ({"login": "admin", "password": PASSWORD}, {"login": "нет-такого", "password": "x"}):
        assert client.post("/api/auth/login", json=body, headers=CSRF).status_code in (404, 405)
    for on in (True, False):
        r = client.post("/api/auth/mode", json={"auth_required": on, "login": "admin", "password": PASSWORD}, headers=SUPER)
        assert r.status_code in (404, 405)


def test_core_api_needs_session_of_the_one_login(client):
    """Вход включён — данные ядра только с сессией; сессию даёт единственный вход — слой «Команды» (суперадмину — личный
    пароль)."""
    client.app.state.accounts.set_auth_required(True, "тест")
    assert client.get(f"/api/projects/{client.pid}/tasks", headers=SUPER).status_code == 401
    assert client.get("/api/theme").status_code == 200
    r = client.post("/auth/login", json={"login": "admin", "password": PASSWORD}, headers=W)
    assert r.status_code == 200 and r.json()["user"]["access_role"] == "super_admin"
    assert client.get(f"/api/projects/{client.pid}/tasks").status_code == 200


def test_five_wrong_passwords_lock_the_account(client):
    """Перевёрнуто 06.11.2026 (вопрос 4): блокировка — по правилам слоя «Команды», 5 неудач и 2 минуты."""
    client.app.state.accounts.set_auth_required(True, "тест")
    for _ in range(5):
        client.post("/auth/login", json={"login": "admin", "password": "x"}, headers=W)
    r = client.post("/auth/login", json={"login": "admin", "password": PASSWORD}, headers=W)
    assert r.status_code in (401, 429) and "2 минуты" in r.json()["detail"]


def test_password_is_never_stored_in_clear(client):
    row = client.app.state.store.q("SELECT password_hash FROM accounts WHERE login='admin'")[0]
    assert row["password_hash"].startswith("scrypt$") and PASSWORD not in row["password_hash"]


def test_accounts_screen_is_closed(client):
    """Перевёрнуто 06.11.2026 (вопрос 5): экран учётных записей «Мониторинга» закрыт — учётные записи ведёт «Команда»."""
    assert client.get("/api/monitoring/accounts", headers=SUPER).status_code in (404, 405)
    r = client.post("/api/monitoring/accounts", json={"login": "ignatov", "full_name": "Игнатов Иван", "role": "member",
                                                      "password": "короткий"}, headers=SUPER)
    assert r.status_code in (404, 405)
    assert not client.app.state.store.q("SELECT id FROM accounts WHERE login='ignatov'")


# ---------------------------------------------------------------- Мониторинг RealTime
def test_live_services_and_project_intake(client, tmp_path):
    d = client.get(f"/api/monitoring/live?pid={client.pid}", headers=SUPER).json()
    names = {r["name"]: r["state"] for r in d["services"]}
    assert names["Модель"] == "выкл." and names["База данных"] == "живо" and names["Сервер"] == "живо"
    assert names["Папка-приёмник · Пилот"] == "выкл." and d["intake"]["interval_source"] == "по умолчанию"
    assert "awaiting_total" in d and "queue" in d


def test_interval_from_environment_is_labelled(client, monkeypatch):
    monkeypatch.setenv("MEETFLOW_WATCH_INTERVAL_SEC", "600")
    st = client.app.state.intake.state(client.pid)
    assert st["interval"] == 600 and "MEETFLOW_WATCH_INTERVAL_SEC" in st["interval_source"]
    client.post(f"/api/projects/{client.pid}/settings/watch-interval", json={"seconds": 120}, headers=SUPER)
    assert client.app.state.intake.state(client.pid)["interval_source"] == "задана на экране"


def test_stalled_folder_is_reported(client, tmp_path, monkeypatch):
    svc = client.app.state.intake
    d = tmp_path / "in"
    d.mkdir()
    svc.s.set_setting("watch_folder", str(d), client.pid)
    old = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    svc.s.set_setting("watch_last_scan", {"at": old, "status": "ok"}, client.pid)
    monkeypatch.setattr(type(svc), "running", property(lambda self: True))
    assert svc.state(client.pid)["stalled"]
    rows = {r["name"]: r for r in client.get("/api/monitoring/live", headers=SUPER).json()["services"]}
    assert rows["Папка-приёмник · Пилот"]["state"] == "нет" and "завис" in rows["Папка-приёмник · Пилот"]["detail"]



def test_long_pass_in_progress_is_not_stalled_2710(client, tmp_path, monkeypatch):
    """27.10.2026: две записи в папке — проход идёт долго (распознавание, сборка); время прохода пишется в конце,
    и экран писал «поток завис». Идущий проход с пульсом — «живо, идёт проход», зависший шаг — «проход стоит»."""
    import time as _t
    from meetflow.core import intake as intake_mod
    svc = client.app.state.intake
    d = tmp_path / "in"
    d.mkdir()
    svc.s.set_setting("watch_folder", str(d), client.pid)
    old = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    svc.s.set_setting("watch_last_scan", {"at": old, "status": "ok"}, client.pid)
    monkeypatch.setattr(type(svc), "running", property(lambda self: True))
    svc._scanning[client.pid] = {"started": old, "step": "распознавание записи", "file": "Встреча 15.10.2026.m4a",
                                 "pulse": _t.monotonic() - 600}
    st = svc.state(client.pid)
    assert st["scan_in_progress"] and not st["stalled"]
    rows = {r["name"]: r for r in client.get("/api/monitoring/live", headers=SUPER).json()["services"]}
    row = rows["Папка-приёмник · Пилот"]
    assert row["state"] == "живо" and "идёт проход" in row["detail"] and "распознавание записи" in row["detail"]
    assert "завис" not in row["detail"]
    svc._scanning[client.pid]["pulse"] = _t.monotonic() - max(3 * svc.interval(client.pid), intake_mod.STALL_STEP_SEC) - 5
    rows = {r["name"]: r for r in client.get("/api/monitoring/live", headers=SUPER).json()["services"]}
    row = rows["Папка-приёмник · Пилот"]
    assert row["state"] == "нет" and "проход стоит: распознавание записи" in row["detail"]


def test_pass_marks_step_and_clears_after_2710(client, tmp_path):
    svc = client.app.state.intake
    d = tmp_path / "in"
    d.mkdir()
    (d / "Встреча 15.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    svc.s.set_setting("watch_folder", str(d), client.pid)
    seen = []
    real = svc.pipe.ingest

    def spy(*a, **k):
        seen.append(dict(svc._scanning.get(client.pid) or {}))
        return real(*a, **k)

    svc.pipe.ingest = spy
    try:
        svc.scan_project(client.pid)       # первый проход — файл «оседает»
        svc.scan_project(client.pid)
    finally:
        svc.pipe.ingest = real
    assert seen and seen[0]["step"] == "приём файла" and seen[0]["file"] == "Встреча 15.10.2026.txt"
    assert client.pid not in svc._scanning and not svc.state(client.pid)["scan_in_progress"]

# ---------------------------------------------------------------- Параметры системы
def test_system_messages_close_one_and_all_and_expire(client):
    cards = client.app.state.pipe.cards
    for t in ("первое", "второе", "третье"):
        cards.open(None, "technical", t, {})
    msgs = client.get("/api/monitoring/system-messages", headers=SUPER).json()
    assert len(msgs) == 3
    client.post(f"/api/monitoring/system-messages/{msgs[0]['id']}/close", headers=SUPER)
    assert len(client.get("/api/monitoring/system-messages", headers=SUPER).json()) == 2
    assert client.post("/api/monitoring/system-messages/close-all", headers=SUPER).json()["closed"] == 2
    old = cards.open(None, "technical", "старое", {})
    client.app.state.store.update("cards", old, created_at="2020-01-01T00:00:00")
    assert client.get("/api/monitoring/system-messages", headers=SUPER).json() == []   # закрылось само по сроку


def test_awaiting_input_groups(client, tmp_path):
    client.app.state.pipe.cards.open(client.pid, "held_task", "Задача из записи не заведена", {})
    client.app.state.store.insert("people", project_id=client.pid, full_name="Новый Человек", confirmed=0)
    d = tmp_path / "in"
    d.mkdir()
    (d / "без даты.txt").write_text("x", encoding="utf-8")
    client.app.state.store.set_setting("watch_folder", str(d), client.pid)
    r = client.get("/api/monitoring/awaiting-input", headers=SUPER).json()
    g = {x["key"]: x for x in r["groups"]}
    assert g["cards"]["count"] == 1 and g["people"]["count"] == 1 and g["no_date"]["count"] == 1
    assert r["total"] >= 3 and all(x["need"] and x["if_not"] for x in r["groups"])


def test_thresholds_overdue_highlight_and_card_cleanup(client):
    st = client.app.state.store
    long_ago = (date.today() - timedelta(days=30)).strftime("%d.%m.%Y")
    tid = st.insert("tasks", project_id=client.pid, description="Старое", status="active", due_date=long_ago)
    st.insert("tasks", project_id=client.pid, description="Свежее", status="active",
              due_date=(date.today() + timedelta(days=3)).strftime("%d.%m.%Y"))
    rows = {t["description"]: t for t in client.get(f"/api/projects/{client.pid}/tasks").json()}
    assert rows["Старое"]["overdue"] and not rows["Свежее"]["overdue"]
    r = client.post("/api/settings/thresholds", json={"overdue_highlight_working_days": 60, "card_cleanup_days": 5},
                    headers=SUPER).json()
    assert r["card_cleanup_days"] == 5 and r["card_cleanup_source"] == "задан на экране"
    assert not {t["id"]: t for t in client.get(f"/api/projects/{client.pid}/tasks").json()}[tid]["overdue"]
    assert client.post("/api/settings/thresholds", json={"overdue_highlight_working_days": 0}, headers=SUPER).status_code == 422


def test_card_cleanup_reads_screen_threshold(client):
    st = client.app.state.store
    cid = client.app.state.pipe.cards.open(client.pid, "held_task", "старая карточка", {})
    st.update("cards", cid, created_at=(datetime.now() - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S"))
    st.set_setting("card_cleanup_days", 5)
    mid = st.insert("meetings", project_id=client.pid, date="2026-10-01", label="в")
    client.app.state.pipe.ingest(client.pid, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    client.app.state.pipe.run(client.pid, mid)
    assert st.get("cards", cid)["status"] == "rejected"


def test_backup_now_and_data_state_and_static(client):
    r = client.post("/api/monitoring/backup-now", headers=SUPER).json()
    assert r["file"].endswith(".db") and "_ручная_" in r["file"]
    s = client.get("/api/monitoring/static", headers=SUPER).json()
    assert s["backup"]["files"][0]["manual"] and s["access"]["auth_required"] is False
    assert any(a["login"] == "admin" for a in s["access"]["accounts"])
    ds = client.get("/api/monitoring/data-state", headers=SUPER).json()
    пилот = next(x for x in ds if x["project"] == "Пилот")   # «Общие встречи» — тоже строка (Доработка 2, 28.10.2026)
    assert пилот["people"] == len(TEAM)


def test_everything_is_super_admin_only(client):
    adm = {"X-User-Role": "project_admin"}
    for url in ("/api/monitoring/live", "/api/monitoring/awaiting-input", "/api/monitoring/system-messages",
                "/api/monitoring/data-state", "/api/monitoring/static", "/api/settings/thresholds",
                "/api/monitoring/decisions", "/api/monitoring/rules"):   # «accounts» закрыт 06.11.2026
        assert client.get(url, headers=adm).status_code == 403, url
