# -*- coding: utf-8 -*-
"""Приём входа от портала единого входа в MeetFlow — этап 2 (задание владелицы 06.11.2026).

Те же проверки, что у Проекта ERP и Планёрки (`tests/test_portal_sso_0611.py` там): без секрета приёма нет; код,
подтверждённый паролем на портале, открывает обычную сессию на 12 часов без второго пароля; код тестового режима при
включённом входе — нет; при выключенном входе человек подставляется в «Вы работаете как»; внешний, отключённый,
незнакомый — без входа; обратный канал — только с секретом; выход по сигналу портала и выход в MeetFlow закрывают все
сессии человека. Плюс своё: номер общей «Команды» для портала — только по точному и единственному совпадению ФИО.
Портал подменён, люди вымышленные.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from meetflow.web.erp import portal_vhod

СЕКРЕТ = "portal-secret-0611"
ПОРТАЛ = {"Authorization": "Bearer " + СЕКРЕТ}
W = {"X-Requested-With": "erp-webapp"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    ids = {}
    for key, fio, role, login, ext, active in (
            ("super", "Орлова Анна Сергеевна", "super_admin", "aorlova", 0, 1),
            ("member", "Сидорова Вера Ильинична", "member", "vsidorova", 0, 1),
            ("ext", "Внешний Пётр", "member", "ext", 1, 1),
            ("off", "Отключённый Иван", "member", "off", 0, 0)):
        ids[key] = st.insert("accounts", login=login, full_name=fio, role=role, password_hash="", active=active,
                             confirmed=1, external=ext)
    monkeypatch.setenv("PORTAL_SECRET", СЕКРЕТ)
    вызовы = []

    def обмен(path, body):
        вызовы.append((path, body))
        if path != "/api/sso/exchange":
            return {"ok": True}
        code = body.get("code", "")
        if body.get("system") != "meetflow" or "-" not in code:
            return None
        вид, логин = code.split("-", 1)
        return {"uid": "u-" + логин, "full_name": логин, "login": логин, "verified": вид == "c"}

    monkeypatch.setattr(portal_vhod, "_portal_call", обмен)

    def режим(вкл: bool):
        app.state.erp.accounts.set_auth_required(вкл, "тест")

    c.ids, c.st, c.режим, c.вызовы = ids, st, режим, вызовы
    return c


def _сессии(env, uid):
    return len(env.st.q("SELECT id FROM sessions WHERE account_id=?", (uid,)))


def _код(c, code):
    return c.get("/auth/portal", params={"code": code}, follow_redirects=False)


def test_без_секрета_приёма_нет(env, monkeypatch):
    monkeypatch.delenv("PORTAL_SECRET")
    env.режим(True)
    r = _код(env, "c-vsidorova")
    assert r.headers["location"] == "/" and "mf_session" not in r.headers.get("set-cookie", "")
    assert env.get("/auth/portal/accounts", headers=ПОРТАЛ).status_code == 404


def test_подтверждённый_код_открывает_сессию_на_12_часов(env):
    env.режим(True)
    r = _код(env, "c-vsidorova")
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 303 and "mf_session" in cookie and "max-age=43200" in cookie
    assert env.get("/auth/me").json()["login"] == "vsidorova"
    assert env.вызовы[0] == ("/api/sso/exchange", {"system": "meetflow", "code": "c-vsidorova"})


def test_код_тестового_режима_не_открывает_рабочий_вход(env):
    env.режим(True)
    r = _код(env, "t-vsidorova")
    assert "mf_session" not in r.headers.get("set-cookie", "") and _сессии(env, env.ids["member"]) == 0


def test_тестовый_режим_подставляет_человека(env):
    r = _код(env, "t-vsidorova")
    assert r.headers["location"] == f"/?portal_user={env.ids['member']}"


@pytest.mark.parametrize("code", ["c-ext", "c-off", "c-nobody", "мусор", "", "x" * 300])
def test_внешний_отключённый_незнакомый_без_входа(env, code):
    env.режим(True)
    r = _код(env, code)
    assert r.headers["location"] == "/" and "mf_session" not in r.headers.get("set-cookie", "")


def test_обратный_канал_только_с_секретом(env):
    assert env.get("/auth/portal/accounts").status_code == 401
    assert env.post("/auth/portal/logout", json={"login": "vsidorova"}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_номер_команды_только_по_точному_единственному_фио(env, tmp_path, monkeypatch):
    shared = tmp_path / "team_shared.db"
    con = sqlite3.connect(shared)
    con.execute("CREATE TABLE people (uid TEXT, full_name TEXT, is_external INTEGER)")
    con.executemany("INSERT INTO people VALUES (?,?,?)", [
        ("u-1", "Орлова Анна Сергеевна", 0),
        ("u-2", "Сидорова Вера Ильинична", 0), ("u-3", "Сидорова Вера Ильинична", 0),   # двое — не сопоставляем
    ])
    con.commit()
    con.close()
    monkeypatch.setenv("TEAM_SHARED_PATH", str(shared))
    rows = env.get("/auth/portal/accounts", headers=ПОРТАЛ).json()
    assert rows == [{"uid": "u-1", "login": "aorlova", "access_role": "super_admin"}]


def test_выход_по_сигналу_портала_закрывает_все_сессии(env):
    env.режим(True)
    _код(env, "c-vsidorova")
    env.cookies.clear()
    _код(env, "c-vsidorova")
    assert _сессии(env, env.ids["member"]) == 2
    r = env.post("/auth/portal/logout", json={"uid": "", "login": "vsidorova"}, headers=ПОРТАЛ)
    assert r.json() == {"closed": 2} and _сессии(env, env.ids["member"]) == 0


def test_выход_в_meetflow_закрывает_всё_и_сообщает_порталу(env, monkeypatch):
    сообщено = []
    monkeypatch.setattr(portal_vhod, "notify_logout", lambda u: сообщено.append(u["login"]))
    env.режим(True)
    _код(env, "c-vsidorova")
    первая = env.cookies.get("mf_session")
    env.cookies.clear()
    _код(env, "c-vsidorova")
    env.cookies.clear()
    env.cookies.set("mf_session", первая)
    assert env.post("/auth/logout", headers=W).status_code == 204
    assert _сессии(env, env.ids["member"]) == 0 and сообщено == ["vsidorova"]


# ---------------------------------------------------------------- пакет 2б: пароли живут на портале, команда set-password
from meetflow.web.erp.bezopasnost import hash_password, verify_password   # noqa: E402


def test_портал_раздаёт_общий_и_личный_суперадмина(env):
    общий, личный = hash_password("общий-0611"), hash_password("лично-0611")
    тело = {"shared_hash": общий, "super_admins": [{"login": "aorlova", "hash": личный}, {"login": "vsidorova", "hash": личный}]}
    assert env.post("/auth/portal/passwords", json=тело, headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = env.post("/auth/portal/passwords", json=тело, headers=ПОРТАЛ)
    assert r.status_code == 200 and r.json() == {"shared": True, "super_admins": 1}       # участнику личный не ложится
    assert env.st.get_setting("shared_password_hash") == общий
    assert verify_password("лично-0611", env.st.get("accounts", env.ids["super"])["password_hash"])
    assert not verify_password("лично-0611", env.st.get("accounts", env.ids["member"])["password_hash"] or None)
    env.режим(True)
    assert env.post("/auth/login", json={"login": "vsidorova", "password": "общий-0611"}, headers=W).status_code == 200
    env.cookies.clear()
    assert env.post("/auth/login", json={"login": "aorlova", "password": "лично-0611"}, headers=W).status_code == 200
    assert env.post("/auth/portal/passwords", json=тело, headers=ПОРТАЛ).json() == {"shared": False, "super_admins": 0}
    assert env.post("/auth/portal/passwords", json={"shared_hash": "открытый"}, headers=ПОРТАЛ).status_code == 400


def test_set_password_выдаёт_временный_и_роль_только_явно(tmp_path, capsys):
    from meetflow.__main__ import main
    from meetflow.core.store import Store
    db = str(tmp_path / "cli.db")
    Store(db)
    assert main(["set-password", "--login", "newbie", "--db", db]) == 2                  # новой записи нужна роль
    assert main(["set-password", "--login", "Newbie@company.ru", "--name", "Новиков Н.", "--role", "member", "--db", db]) == 0
    вывод = capsys.readouterr().out
    временный = вывод.split("нигде не записан): ", 1)[1].split()[0]
    st = Store(db)
    u = st.q("SELECT * FROM accounts WHERE login='newbie'")[0]
    assert u["role"] == "member" and u["must_change_password"] == 1 and u["temp_expires_at"]
    assert verify_password(временный, u["password_hash"])
    assert main(["set-password", "--login", "newbie", "--db", db]) == 0                  # существующей роль не меняется
    assert Store(db).q("SELECT role FROM accounts WHERE login='newbie'")[0]["role"] == "member"
    журнал = " ".join(r["title"] + r["payload"] for r in Store(db).q("SELECT title, payload FROM cards"))
    assert "Временный пароль выдан командной строкой: newbie" in журнал and временный not in журнал


# ---------------------------------------------------------------- человек без логина — по ФИО (находка 08.11.2026)
def _обмен_с_фио(env, monkeypatch, фио: str, verified: bool = False):
    def обмен(path, body):
        if path != "/api/sso/exchange":
            return {"ok": True}
        return {"uid": "u-x", "full_name": фио, "login": None, "verified": verified}
    monkeypatch.setattr(portal_vhod, "_portal_call", обмен)


def test_без_логина_находится_по_точному_фио(env, monkeypatch):
    uid = env.st.insert("accounts", login="", full_name="Котельников Олег Петрович", role="member", password_hash="",
                        active=1, confirmed=1, external=0)
    _обмен_с_фио(env, monkeypatch, "Котельников Олег Петрович")
    r = _код(env, "t-любой")
    assert r.headers["location"] == f"/?portal_user={uid}"


def test_без_логина_запись_без_отчества_одна(env, monkeypatch):
    uid = env.st.insert("accounts", login="", full_name="Мухин Олег", role="member", password_hash="", active=1,
                        confirmed=1, external=0)
    _обмен_с_фио(env, monkeypatch, "Мухин Олег Андреевич")
    assert _код(env, "t-любой").headers["location"] == f"/?portal_user={uid}"


def test_без_логина_двое_подходящих_никого(env, monkeypatch):
    for фио in ("Мухин Олег", "Мухин Олег Петрович"):
        env.st.insert("accounts", login="", full_name=фио, role="member", password_hash="", active=1, confirmed=1,
                      external=0)
    _обмен_с_фио(env, monkeypatch, "Мухин Олег Андреевич")
    assert _код(env, "t-любой").headers["location"] == "/"


def test_без_логина_внешний_и_отключённый_не_находятся(env, monkeypatch):
    env.st.insert("accounts", login="", full_name="Внешний Пётр Ильич", role="member", password_hash="", active=1,
                  confirmed=1, external=1)
    _обмен_с_фио(env, monkeypatch, "Внешний Пётр Ильич")
    assert _код(env, "t-любой").headers["location"] == "/"


def test_без_логина_с_паролем_портала_открывает_сессию(env, monkeypatch):
    uid = env.st.insert("accounts", login="", full_name="Семёнова Ирина Павловна", role="member", password_hash="",
                        active=1, confirmed=1, external=0)
    _обмен_с_фио(env, monkeypatch, "Семенова Ирина Павловна", verified=True)
    env.режим(True)
    r = _код(env, "c-любой")
    assert r.headers["location"] == "/" and "mf_session" in r.headers.get("set-cookie", "")
    assert _сессии(env, uid) == 1
