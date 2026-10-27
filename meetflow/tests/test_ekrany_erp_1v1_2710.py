"""Экраны ERP 1 в 1 (27.10.2026): фронт MeetFlow — фронт ERP, сервер MeetFlow отвечает на адреса ERP тем же видом.

Проверки — по правилам ERP, перенесённым в слой `meetflow/web/erp`: «Команда» и вход, значки, «Встречи по проекту» и
«Подготовка встречи» (одна встреча на дату, вторая по подтверждению, ключ повтора, удаление пустой, отмена с планом,
«Свести в одну» и «Вернуть на новую дату»), источники и материалы, сборка через очередь, реестр задач (замок версии,
«Актуализировать», «оперативная», «Вернуть», удаление). Данные вымышленные, модель — заглушка.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TRANSCRIPT

STATIC = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"
W = {"X-Requested-With": "erp-webapp"}


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    pid2 = st.insert("projects", name="Цех", theme="erp_rollout", archived=0)
    ids = {}
    for fio, role in (("Орлова Анна", "super_admin"), ("Петров Илья", "project_admin"), ("Сидорова Вера", "member")):
        ids[role] = st.insert("accounts", login=None, full_name=fio, role=role, password_hash="", active=1, confirmed=1)

    def h(role="super_admin", project=pid):
        return {**W, "X-User-Id": str(ids[role]), "X-Project-Id": str(project)}
    c.h, c.ids, c.pid, c.pid2, c.st, c.app = h, ids, pid, pid2, st, app
    return c


def iso(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# --- фронт ---------------------------------------------------------------------------------------------------------

def test_фронт_erp_целиком_светлая_тема_и_выбор_проекта():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for f in ("app.js", "nav.js", "meeting.js", "prep.js", "registry.js", "razbor.js", "polotno.js", "system.js", "tema.js",
              "conflicts.js", "operativnaya.js"):
        assert f'src="{f}?v=' in html, f
        assert (STATIC / f).exists()
    for label in ("Встречи по проекту", "Актуализировать задачи из реестра", "Договорённости", "Статус проекта",
                  "Подготовка встречи", "Команда", "Разбор", "Параметры системы", "Мониторинг RealTime", "Модели",
                  "База голосов", "Разбор голосов", "Как пользоваться", "Вы работаете как"):
        assert label in html, label
    assert 'id="project-select"' in html and "Все проекты" in html
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'headers["X-Project-Id"] = String(выбранныйПроект());' in js
    assert "`Проект — ${п.name}`" in js and '"Все проекты компании"' in js
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "--bg: #fafafa;" in css and "prefers-color-scheme: dark" not in css


def test_встречи_без_формы_создания_и_подготовка_с_ближайшей():
    nav = (STATIC / "nav.js").read_text(encoding="utf-8")
    proto = nav[nav.index("async function renderProtocols()"):nav.index("routes.meetings = ")]
    assert "Встречи по проекту" in proto and "prep-new-form" not in proto and "Новая встреча заводится в «Подготовке встречи»" in proto
    assert "Ближайшая встреча ${esc(fmtRuDate(ближайшая.date))} — план встречи" in proto
    prep = nav[nav.index("async function renderPrep()"):nav.index("routes.prep = renderPrep;")]
    for s in ("Ближайшая встреча: ${esc(fmtRuDate(б.date))}, ${esc(деньНедели(б.date))}", "Открыть план встречи",
              "изменить дату", "Другая дата…", "сформировать план", "план собран", "протокол готов", "встреча ещё не прошла",
              "Архив — встречи старше"):
        assert s in prep, s


# --- «Команда» и вход ------------------------------------------------------------------------------------------------

def test_команда_правила_erp(env):
    c, h = env, env.h
    r = c.post("/users", json={"full_name": "Кузнецов Олег"}, headers=h())
    assert r.status_code == 201 and r.json()["access_role"] == "member" and r.json()["login"] is None
    assert c.post("/users", json={"full_name": "Олег Кузнецов"}, headers=h()).status_code == 409   # перестановка — тот же
    assert c.post("/users", json={"full_name": "Кузнецов"}, headers=h()).status_code == 400       # одно слово без роли
    # назначать администратора — только суперадмин
    uid = r.json()["id"]
    assert c.patch(f"/users/{uid}", json={"access_role": "project_admin"}, headers=h("project_admin")).status_code == 403
    assert c.patch(f"/users/{uid}", json={"access_role": "project_admin"}, headers=h()).json()["access_role"] == "project_admin"
    # последнего суперадмина не понизить и не отключить
    sa = c.ids["super_admin"]
    assert c.patch(f"/users/{sa}", json={"access_role": "member"}, headers=h()).status_code == 400
    assert c.post(f"/users/{sa}/active", json={"is_active": False}, headers=h()).status_code == 400
    # логин видит только суперадмин; внешним доступ не выдаётся
    ext = c.post("/users", json={"full_name": "Иван", "is_external": True, "organization": "Подрядчик",
                                 "project_role": "прораб", "name_short_reason": "так он подписывается"}, headers=h()).json()
    assert c.post(f"/users/{ext['id']}/access", json={"email": "ivan"}, headers=h()).status_code == 400
    lst = c.get("/users", headers=h("member")).json()
    assert all("login" not in u for u in lst)
    # подтверждённые люди «Команды» — в людях проекта (по ним работает конвейер)
    names = {p["full_name"] for p in c.st.q("SELECT full_name FROM people WHERE project_id=?", (c.pid,))}
    assert "Кузнецов Олег" in names and "Орлова Анна" in names


def test_вход_общий_пароль_первый_вход_и_временный_пароль(env):
    c, h, st = env, env.h, env.st
    from meetflow.web.erp.bezopasnost import hash_password
    st.set_setting("shared_password_hash", hash_password("Общий-пароль-42"))
    ppl = c.get("/auth/first-login/people").json()
    assert ppl["shared_password_set"] and any(p["full_name"] == "Сидорова Вера" for p in ppl["people"])
    r = c.post("/auth/first-login", json={"user_id": c.ids["member"], "login": "vsidorova", "password": "Общий-пароль-42"},
               headers=W)
    assert r.status_code == 200 and r.json()["user"]["login"] == "vsidorova"
    assert c.get("/auth/first-login/people").json()["people"] == [p for p in c.get("/auth/first-login/people").json()["people"]
                                                                    if p["full_name"] != "Сидорова Вера"]
    # «Выдать доступ» администратору — временный пароль один раз, со сменой при входе
    g = c.post(f"/users/{c.ids['project_admin']}/access", json={"email": "ipetrov"}, headers=h())
    assert g.status_code == 200 and g.json()["temporary_password"] and g.json()["valid_hours"] == 24
    assert c.post("/auth/login", json={"login": "ipetrov", "password": "неверный"}, headers=W).status_code == 401
    ok = c.post("/auth/login", json={"login": "ipetrov", "password": g.json()["temporary_password"]}, headers=W)
    assert ok.status_code == 200 and ok.json()["user"]["must_change_password"] is True
    assert c.post("/auth/login", json={"login": "ipetrov", "password": "x"}).status_code == 403    # без защитного заголовка


def test_значки_по_ролям(env):
    c, h = env, env.h
    b = c.get("/badges", headers=h()).json()
    assert set(b) >= {"conflicts", "system", "under_question", "razbor", "possible", "voice_review"}
    m = c.get("/badges", headers=h("member")).json()
    assert m["conflicts"] is None and m["system"] is None and m["razbor"] is None
    assert c.get("/badges").status_code == 401


# --- встречи ---------------------------------------------------------------------------------------------------------

def test_одна_встреча_на_дату_вторая_по_подтверждению_и_ключ_повтора(env):
    c, h = env, env.h
    d = iso(5)
    a = c.post("/meetings", json={"date": d, "request_key": "k1"}, headers=h())
    assert a.status_code == 201
    again = c.post("/meetings", json={"date": d, "request_key": "k1"}, headers=h())
    assert again.json()["id"] == a.json()["id"]                         # обрыв сети — та же встреча
    busy = c.post("/meetings", json={"date": d}, headers=h())
    assert busy.status_code == 409 and busy.json()["existing_id"] == a.json()["id"]
    chk = c.get(f"/meetings/date-check?date={d}", headers=h()).json()
    assert chk["busy"] and chk["meetings"][0]["id"] == a.json()["id"]
    second = c.post("/meetings", json={"date": d, "second_same_day": True}, headers=h())
    assert second.status_code == 201 and second.json()["second_same_day"] is True
    # в другом проекте дата свободна; «Все проекты» не заводят
    assert c.post("/meetings", json={"date": d}, headers=h(project=c.pid2)).status_code == 201
    assert c.post("/meetings", json={"date": d}, headers=h(project=0)).status_code == 400
    lst = c.get("/meetings", headers=h()).json()
    assert {m["project_id"] for m in lst} == {c.pid}
    assert len(c.get("/meetings", headers=h(project=0)).json()) == 3


def test_удаление_пустой_отмена_с_планом_и_сводка(env):
    c, h, st = env, env.h, env.st
    m1 = c.post("/meetings", json={"date": iso(3)}, headers=h()).json()["id"]
    assert c.get(f"/meetings/{m1}/delete-check", headers=h()).json()["can_delete"]
    assert c.delete(f"/meetings/{m1}", headers=h("member")).status_code == 403
    assert c.delete(f"/meetings/{m1}", headers=h()).json()["deleted"] is True
    m2 = c.post("/meetings", json={"date": iso(4)}, headers=h()).json()["id"]
    st.update("meetings", m2, plan_md="План встречи", plan_built_at="2026-10-27T10:00:00")
    chk = c.get(f"/meetings/{m2}/delete-check", headers=h()).json()
    assert not chk["can_delete"] and chk["can_cancel"] and "собран план" in chk["cancel_text"]
    assert c.post(f"/meetings/{m2}/cancel-with-plan", headers=h()).json()["cancelled"] is True
    assert all(m["id"] != m2 for m in c.get("/meetings", headers=h()).json())
    # «Свести в одну»: материалы переезжают, опустевшая удаляется; «Вернуть на новую дату» — обратно
    a = c.post("/meetings", json={"date": iso(8)}, headers=h()).json()["id"]
    b = c.post("/meetings", json={"date": iso(8), "second_same_day": True}, headers=h()).json()["id"]
    up = c.post(f"/meetings/{b}/materials", headers=h(), files={"file": ("смета.txt", "Смета на стеллажи".encode())},
                data={"description": "к плану"})
    assert up.status_code == 201 and up.json()["description"] == "к плану"
    res = c.post(f"/meetings/{b}/merge", json={"to": a}, headers=h()).json()
    assert res["moved"] == 1 and res["deleted"] is True
    sv = c.get(f"/meetings/{a}/merged", headers=h()).json()
    assert sv and sv[0]["from_id"] == b and sv[0]["count"] == 1
    back = c.post(f"/meetings/{a}/unmerge", json={"from_id": b, "date": iso(9)}, headers=h()).json()
    assert back["moved"] == 1 and len(c.get(f"/meetings/{back['meeting']['id']}/materials", headers=h()).json()) == 1


def test_источники_сборка_через_очередь_и_путь(env):
    c, h = env, env.h
    fut = c.post("/meetings", json={"date": iso(2)}, headers=h()).json()["id"]
    assert c.post(f"/meetings/{fut}/prepare-minutes", headers=h()).status_code == 400      # будущая — после встречи
    past = c.post("/meetings", json={"date": iso(-1)}, headers=h()).json()["id"]
    r = c.post(f"/meetings/{past}/prepare-minutes", headers=h())
    assert r.status_code == 400 and "Собирать протокол не из чего" in r.json()["detail"]
    t = c.post(f"/meetings/{past}/sources/text", json={"text": TRANSCRIPT}, headers=h("member"))
    assert t.status_code == 201 and t.json()["original_filename"].startswith("Вставленный текст")
    assert c.post(f"/meetings/{past}/sources/text", json={"text": TRANSCRIPT}, headers=h()).status_code == 409
    srcs = c.get(f"/meetings/{past}/sources", headers=h()).json()
    assert len(srcs) == 1 and srcs[0]["kind"]
    assert c.get("/meetings", headers=h()).json()[0]["состояние_протокола"]
    q = c.post(f"/meetings/{past}/prepare-minutes?confirm=1", headers=h())
    assert q.status_code == 200 and q.json()["status"] in ("queued", "already_running", "already_queued")
    c.app.state.queue.wait(c.st.q("SELECT id FROM build_queue WHERE meeting_id=?", (past,))[0]["id"], timeout=60)
    g = c.get(f"/meetings/{past}/generation", headers=h()).json()
    assert set(g) >= {"running", "queued", "queue_lines", "pending"}
    path = c.get(f"/meetings/{past}/path", headers=h()).json()
    assert [s["k"] for s in path["steps"]] == ["intake", "transcript", "draft", "decision", "saved", "next_plan"]
    mins = c.get(f"/meetings/{past}/minutes", headers=h()).json()
    if mins["available"]:
        assert mins["content_md"] and isinstance(mins["minor_findings"], list)
        exp = c.get(f"/meetings/{past}/minutes/export", headers=h())
        assert exp.status_code == 200 and exp.content[:2] == b"PK"
    basis = c.get(f"/meetings/{fut}/plan-basis", headers=h()).json()
    assert basis["previous"]["state"] in ("minutes", "source", "none", "empty")


def test_дата_встречи_и_ведущий_вручную(env):
    c, h = env, env.h
    m = c.post("/meetings", json={"date": iso(6), "label": "дата ориентировочная"}, headers=h()).json()["id"]
    r = c.patch(f"/meetings/{m}/date", json={"date": iso(7)}, headers=h())
    assert r.status_code == 200 and r.json()["date"] == iso(7) and r.json()["label"] is None
    assert c.patch(f"/meetings/{m}/date", json={"date": iso(7)}, headers=h("member")).status_code == 403
    led = c.patch(f"/meetings/{m}/leader", json={"user_id": c.ids["project_admin"]}, headers=h())
    assert led.json()["leader_source"] == "вручную" and led.json()["leader_user_id"] == c.ids["project_admin"]


# --- реестр ----------------------------------------------------------------------------------------------------------

def _task(env, **kw):
    vals = {"project_id": env.pid, "description": "Подготовить акт приёмки", "assignee": "Сидорова Вера", "status": "active",
            "date_set": iso(-3), "version": 1}
    vals.update(kw)
    return env.st.insert("tasks", **vals)


def test_реестр_вид_строки_и_снятые_не_показываются(env):
    c, h = env, env.h
    t1 = _task(env)
    _task(env, description="Снятая задача", status="dropped")
    _task(env, description="Чужой проект", project_id=env.pid2)
    rows = c.get("/tasks?status=active", headers=h()).json()
    assert [r["id"] for r in rows] == [t1]
    r = rows[0]
    for k in ("responsible_text", "due_date", "can_actualize", "status_at", "operational_hint", "version", "under_question_label"):
        assert k in r
    assert r["responsible_user_id"] == c.ids["member"] and r["project_name"] is None
    allp = c.get("/tasks?status=active", headers=h(project=0)).json()
    assert len(allp) == 2 and all(x["project_name"] for x in allp)


def test_замок_версии_и_правки(env):
    c, h = env, env.h
    tid = _task(env)
    v = c.get(f"/tasks/{tid}", headers=h()).json()["version"]
    ok = c.patch(f"/tasks/{tid}/due", json={"due_date": "30.11.2026", "version": v}, headers=h())
    assert ok.status_code == 200 and ok.json()["due_date"] == "2026-11-30"
    stale = c.patch(f"/tasks/{tid}/description", json={"description": "Иначе", "version": v}, headers=h())
    assert stale.status_code == 409                                       # экран видел прежнюю версию
    v2 = ok.json()["version"]
    assert c.patch(f"/tasks/{tid}/description", json={"description": "Подготовить акт", "version": v2},
                   headers=h()).json()["description"] == "Подготовить акт"
    assert c.patch(f"/tasks/{tid}/status", json={"new_status": "done"}, headers=h("member")).status_code == 403
    assert c.post(f"/tasks/{tid}/operational", json={"value": True}, headers=h()).json()["operational"] is True
    done = c.patch(f"/tasks/{tid}/status", json={"new_status": "done"}, headers=h())
    assert done.json()["status"] == "done"
    assert c.get("/tasks/closed/count", headers=h()).json()["count"] == 1
    assert c.get("/tasks/closed", headers=h()).json()["items"][0]["id"] == tid
    assert c.post(f"/tasks/{tid}/revert", headers=h()).json()["status"] == "active"
    assert c.delete(f"/tasks/{tid}", headers=h()).status_code == 204
    assert c.get(f"/tasks/{tid}", headers=h()).status_code == 404


def test_актуализировать_ответственный_и_карточка_ведущему(env):
    c, h, st = env, env.h, env.st
    tid = _task(env)
    other = _task(env, description="Чужая задача", assignee="Петров Илья")
    assert c.post(f"/tasks/{other}/note", json={"kind": "on_track"}, headers=h("member")).status_code == 403
    r = c.post(f"/tasks/{tid}/note", json={"kind": "reschedule", "due_date": "10.12.2026", "text": "ждём поставку"},
               headers=h("member"))
    assert r.status_code == 200 and r.json()["last_comment"].startswith("Нужен перенос срока до 10.12.2026")
    assert r.json()["due_date"] is None                                    # участник срок не меняет — решает ведущий
    cards = st.q("SELECT * FROM cards WHERE kind='member_note' AND status='open'")
    assert len(cards) == 1
    lead = c.post(f"/tasks/{tid}/note", json={"kind": "reschedule", "due_date": "10.12.2026"}, headers=h("project_admin"))
    assert lead.json()["due_date"] == "2026-12-10"


def test_поиск_по_задачам_и_закрытые_словами(env):
    c, h = env, env.h
    _task(env, description="Смонтировать стеллажи второго ряда")
    _task(env, description="Убрать поддоны", status="done", date_closed=iso(-1))
    r = c.get("/tasks/search?q=стеллажи", headers=h()).json()
    assert [t["description"] for t in r["tasks"]] == ["Смонтировать стеллажи второго ряда"]
    z = c.get("/tasks/search?q=поддоны закрытые задачи", headers=h()).json()
    assert z["closed_included"] and [t["description"] for t in z["tasks"]] == ["Убрать поддоны"]


def test_задача_под_вопросом_подтвердить_или_снять(env):
    c, h, st = env, env.h, env.st
    tid = _task(env, doubt_reason="без опоры в записи")
    row = c.get(f"/tasks/{tid}", headers=h()).json()
    assert row["under_question_label"] and row["source_anchor"] == "без опоры в записи"
    assert c.get(f"/tasks/{tid}", headers=h("member")).json()["source_anchor"] is None
    assert c.post(f"/tasks/{tid}/under-question", json={"action": "confirm"}, headers=h()).json()["under_question_label"] is None
    assert c.post(f"/tasks/{tid}/under-question", json={"action": "drop"}, headers=h()).status_code == 400


# --- группа в: протокол на полотне, замечания, единицы -----------------------------------------------------------------

PROTO = """Протокол встречи 20.10.2026

**Стеллажи:** договорились закончить монтаж второго ряда.

| № | Задача | Ответственный | Срок | Откуда |
|---|---|---|---|---|
| 1 | Закончить монтаж второго ряда | Сидорова Вера | 30.10.2026 | запись |
"""


def _meeting_with_protocol(env):
    st = env.st
    mid = st.insert("meetings", project_id=env.pid, date=iso(-2), protocol_md=PROTO, protocol_built_at="2026-10-25T10:00:00",
                    review_notes='[{"issue": "Срок назван неточно, проверьте дату", "quote": "до конца месяца", "severity": "minor"}]')
    st.insert("protocol_versions", meeting_id=mid, version=1, protocol_md=PROTO, model="заглушка", built_at="2026-10-25T10:00:00")
    tid = _task(env, description="Закончить монтаж второго ряда", source_meeting_id=mid, due_date="2026-10-30")
    st.insert("sources", meeting_id=mid, name="Расшифровка.txt", kind="transcript", text=TRANSCRIPT, digest="x1", meta="{}")
    return mid, tid


def test_полотно_черновик_готово_и_запрет_пересборки(env):
    c, h, st = env, env.h, env.st
    mid, tid = _meeting_with_protocol(env)
    ctx_ = c.get(f"/meetings/{mid}/minutes/edit-context", headers=h()).json()
    assert ctx_["own_tasks"] and ctx_["draft"] is None and ctx_["log"] == []
    row = next(r for r in ctx_["rows"] if r["kind"] == "task")
    assert row["task"]["id"] == tid and row["task"]["due"] == "30.10.2026"
    assert c.get(f"/meetings/{mid}/minutes/edit-context", headers=h("member")).status_code == 403
    old = "**Стеллажи:** договорились закончить монтаж второго ряда."
    r = c.post(f"/meetings/{mid}/minutes/edits", json={"version_id": ctx_["version_id"], "ops": [
        {"kind": "block", "old": old, "new": "**Стеллажи:** договорились закончить монтаж второго ряда до 30.10."}]}, headers=h())
    assert r.status_code == 200
    assert "до 30.10" not in c.get(f"/meetings/{mid}/minutes", headers=h()).json()["content_md"]   # до «Готово» — прежняя
    assert c.get(f"/meetings/{mid}/minutes/edit-context", headers=h()).json()["draft"]["edits"] == 1
    assert c.post(f"/meetings/{mid}/minutes/edits/finish", json={"version_id": ctx_["version_id"]}, headers=h()).json()["saved"]
    mins = c.get(f"/meetings/{mid}/minutes", headers=h()).json()
    assert "до 30.10" in mins["content_md"] and mins["hand_edited"] is True
    assert len(st.q("SELECT id FROM protocol_versions WHERE meeting_id=?", (mid,))) == 2
    assert c.post(f"/meetings/{mid}/prepare-minutes?confirm=1&rebuild=true", headers=h()).status_code == 409
    log = c.get(f"/meetings/{mid}/minutes/edit-context", headers=h()).json()["log"]
    assert log and log[0]["place"] == "абзац"


def test_полотно_поля_задачи_сразу_в_реестр_под_версией(env):
    c, h = env, env.h
    mid, tid = _meeting_with_protocol(env)
    ctx_ = c.get(f"/meetings/{mid}/minutes/edit-context", headers=h()).json()
    row = next(r for r in ctx_["rows"] if r["kind"] == "task")
    ok = c.post(f"/meetings/{mid}/minutes/edits", json={"ops": [{"kind": "task", "task_id": tid, "version": row["task"]["version"],
                                                                  "responsible": "Петров Илья", "due": "05.11.2026"}]}, headers=h())
    assert ok.status_code == 200
    t = c.get(f"/tasks/{tid}", headers=h()).json()
    assert t["responsible_text"] == "Петров Илья" and t["due_date"] == "2026-11-05"
    assert "Петров Илья | 05.11.2026" in c.get(f"/meetings/{mid}/minutes", headers=h()).json()["content_md"]
    stale = c.post(f"/meetings/{mid}/minutes/edits", json={"ops": [{"kind": "task", "task_id": tid,
                                                                     "version": row["task"]["version"], "due": ""}]}, headers=h())
    assert stale.status_code == 409
    bad = c.post(f"/meetings/{mid}/minutes/edits", json={"ops": [{"kind": "task", "task_id": tid, "status": "dropped"}]},
                 headers=h())
    assert bad.status_code == 400                                         # снятие — только с причиной
    c.post(f"/meetings/{mid}/minutes/edits", json={"ops": [{"kind": "block", "old": "**Стеллажи:** договорились закончить "
                                                            "монтаж второго ряда.", "new": "**Стеллажи:** иначе."}]}, headers=h())
    assert c.post(f"/meetings/{mid}/minutes/edits/discard", headers=h()).json()["ok"]
    assert c.get(f"/meetings/{mid}/minutes/edit-context", headers=h()).json()["draft"] is None


def test_замечания_проверки_решения_и_возврат(env):
    c, h = env, env.h
    mid, _ = _meeting_with_protocol(env)
    notes = c.get(f"/meetings/{mid}/minutes", headers=h()).json()["minor_findings"]
    assert notes and notes[0]["run_id"] == mid and notes[0]["dismissed"] is False
    r = c.post(f"/review-notes/{mid}/0", json={"action": "keep"}, headers=h())
    assert r.status_code == 200 and "оставлено как есть" in r.json()["message"]
    assert c.get(f"/meetings/{mid}/minutes", headers=h()).json()["minor_findings"][0]["dismissed"] is True
    assert c.get("/review-notes/decisions", headers=h()).json()[0]["outcome"] == "keep"
    c.post(f"/review-notes/{mid}/0", json={"action": "undo"}, headers=h())
    assert c.get(f"/meetings/{mid}/minutes", headers=h()).json()["minor_findings"][0]["dismissed"] is False
    assert c.post(f"/review-notes/{mid}/0", json={"action": "keep"}, headers=h("member")).status_code == 403


def test_точечная_правка_и_единицы(env):
    c, h, st = env, env.h, env.st
    mid, _ = _meeting_with_protocol(env)
    r = c.post(f"/meetings/{mid}/minutes/point-edit", json={"find": "второго ряда.", "replace": "второго ряда полностью."},
               headers=h())
    assert r.status_code == 200 and "полностью" in c.get(f"/meetings/{mid}/minutes", headers=h()).json()["content_md"]
    assert c.post(f"/meetings/{mid}/minutes/point-edit", json={"find": "нет такого", "replace": "x"}, headers=h()).status_code == 400
    uid = st.insert("units", meeting_id=mid, project_id=env.pid, kind="decision", text="Монтаж — до конца месяца",
                    quote="договорились закончить монтаж", status="active")
    units = c.get(f"/meetings/{mid}/units", headers=h()).json()
    assert units[0]["kind"] == "Решение" and units[0]["status"] == "действует"
    assert c.patch(f"/units/{uid}", json={"action": "reject"}, headers=h()).json()["status"] == "убрано"
    assert c.patch(f"/units/{uid}", json={"action": "reopen"}, headers=h()).json()["status"] in ("действует", "открыт")
    assert c.get("/units/meetings", headers=h()).json()[0]["id"] == mid


# --- группа д: договорённости, статус проекта, поиск -------------------------------------------------------------------

def test_договорённости_виды_режим_тени_и_поиск(env):
    c, h, st = env, env.h, env.st
    mid = st.insert("meetings", project_id=env.pid, date=iso(-3))
    st.insert("units", meeting_id=mid, project_id=env.pid, kind="decision", text="Монтаж второго ряда — до конца месяца",
              quote="договорились", status="active")
    st.insert("units", meeting_id=mid, project_id=env.pid, kind="open_question", text="Кто принимает погрузчик", status="open")
    d = c.get("/agreements", headers=h()).json()
    assert d["total"] == 2 and d["mode"] == "on" and {x["kind"] for x in d["items"]} == {"решение", "открытый вопрос"}
    assert c.get("/agreements?kind=открытые", headers=h()).json()["total"] == 1
    assert c.get("/agreements?q=погрузчик", headers=h()).json()["items"][0]["text"] == "Кто принимает погрузчик"
    assert c.get(f"/agreements?meeting_id={mid}", headers=h()).json()["total"] == 2
    assert c.post("/agreements/settings", json={"agreements_mode": "shadow"}, headers=h("project_admin")).status_code == 403
    c.post("/agreements/settings", json={"agreements_mode": "shadow"}, headers=h())
    assert c.get("/agreements", headers=h("member")).json()["items"] == []
    assert c.get("/agreements", headers=h()).json()["total"] == 2


def test_статус_проекта_пересчёт_и_полотно(env):
    c, h = env, env.h
    _task(env, due_date=iso(-5))
    assert c.get("/project-status/summary", headers=h()).json()["available"] is False
    assert c.get("/project-status/staleness", headers=h()).json()["reason"] == "not_generated_yet"
    r = c.post("/project-status/refresh", headers=h("member"))
    assert r.status_code == 200 and r.json()["result"]["status"] == "saved"
    s = c.get("/project-status/summary", headers=h()).json()
    assert s["available"] and "просрочено — 1" in s["content_md"]
    assert c.get("/project-status/roadmap", headers=h()).json()["available"]
    assert c.get("/project-status/summary/export", headers=h()).content[:2] == b"PK"
    assert c.get("/project-status/summary", headers=h(project=0)).status_code == 400
    ctx_ = c.get("/project-status/summary/edit-context", headers=h()).json()
    first = ctx_["display_md"].split("\n")[0]
    c.post("/project-status/summary/edits", json={"ops": [{"kind": "block", "old": first, "new": first + " (уточнено)"}]},
           headers=h())
    c.post("/project-status/summary/edits/finish", json={}, headers=h())
    assert "(уточнено)" in c.get("/project-status/summary", headers=h()).json()["content_md"]
    c.post("/project-status/refresh", headers=h())
    assert "(уточнено)" in c.get("/project-status/summary", headers=h()).json()["content_md"]     # правленное не затирается


def test_поиск_два_этапа(env):
    c, h, st = env, env.h, env.st
    _task(env, description="Смонтировать стеллажи второго ряда")
    mid = st.insert("meetings", project_id=env.pid, date=iso(-2))
    st.insert("sources", meeting_id=mid, name="Расшифровка.txt", kind="transcript", digest="d9", meta="{}",
              text="00:00:01\tПетров Илья\tПогрузчик привезут в четверг\n00:00:09\tОрлова Анна\tХорошо")
    r = c.get("/search?q=стеллажи", headers=h()).json()
    assert r["stage"] == 1 and r["results"][0]["source_type"] == "task"
    deep = c.get("/search?q=погрузчик четверг", headers=h()).json()
    assert deep["deep"] is True and deep["message"].startswith("Идёт глубокий поиск")
    d2 = c.get("/search/deep?q=погрузчик четверг", headers=h()).json()
    assert d2["results"][0]["source_type"] == "transcript_hit" and d2["results"][0]["speaker"] == "Петров Илья"
    assert c.get("/search/deep?q=несуществующее слово", headers=h()).json()["message"] == "По запросу информации нет"
    assert c.get("/search/markers", headers=h()).json()["examples"]


# --- группа е: «Разбор», карточки, «Возможные поручения», правила оператора --------------------------------------------

def _card(env, kind, payload, meeting_id=None, title="Карточка"):
    import json as _j
    return env.st.insert("cards", project_id=env.pid, meeting_id=meeting_id, kind=kind, title=title,
                         payload=_j.dumps(payload, ensure_ascii=False), status="open", created_at="2026-10-27T09:00:00")


def test_разбор_одна_очередь_и_карточки_в_виде_erp(env):
    c, h = env, env.h
    tid = _task(env, doubt_reason="без опоры в записи")
    _card(env, "task_doubt", {"task_id": tid, "description": "Подготовить акт приёмки"})
    t2 = _task(env, description="Согласовать график", assignee=None)
    cid = _card(env, "assign_person", {"task_id": t2, "named": "Вера", "candidates": [{"id": 1, "name": "Сидорова Вера"}]})
    _card(env, "technical", {"error": "x"})
    d = c.get("/razbor", headers=h()).json()
    assert d["total"] == 2 and {x["source"] for x in d["items"]} == {"task", "card"} and d["norm"] == 15
    assert c.get("/razbor", headers=h("member")).status_code == 403
    lst = c.get("/task-conflicts?status=open", headers=h()).json()
    assert [x["id"] for x in lst] == [cid] and lst[0]["source"] == "unconfirmed_person" and lst[0]["candidates"]
    assert c.get("/badges", headers=h()).json()["razbor"] == 2
    r = c.post("/razbor/batch", json={"source": "task", "ids": [tid], "action": "to_task"}, headers=h()).json()
    assert r["done"] == 1 and c.get(f"/tasks/{tid}", headers=h()).json()["under_question_label"] is None


def test_карточка_отметки_исполнителя_и_замечания(env):
    c, h, st = env, env.h, env.st
    tid = _task(env)
    note = _card(env, "member_note", {"task_id": tid, "note": "Сделано — проверьте", "proposed": "done", "by": "Сидорова Вера"})
    assert c.patch(f"/task-conflicts/{note}", json={"action": "accept"}, headers=h()).json()["status"] == "accepted"
    assert c.get(f"/tasks/{tid}", headers=h()).json()["status"] == "done"
    assert c.patch(f"/task-conflicts/{note}", json={"action": "accept"}, headers=h()).status_code == 409
    rf = _card(env, "review_finding", {"issue": "Срок не прозвучал", "quote": "до пятницы"})
    c.patch(f"/task-conflicts/{rf}", json={"action": "reject"}, headers=h())
    assert st.get("cards", rf) is None                                      # «Замечание неверно» — карточки нет
    held = _card(env, "held_task", {"description": "Закупить стеллажи", "quote": "закупить стеллажи"})
    c.patch(f"/task-conflicts/{held}", json={"action": "custom", "custom_value": "Закупить стеллажи для второго ряда"},
            headers=h())
    assert any(t["description"] == "Закупить стеллажи для второго ряда" for t in c.get("/tasks", headers=h()).json())


def test_возможные_поручения_порог_и_решения(env):
    c, h, st = env, env.h, env.st
    from meetflow.core import vozmozhnye
    mid = st.insert("meetings", project_id=env.pid, date=iso(-1))
    pa = st.insert("possible_assignments", project_id=env.pid, meeting_id=mid, meeting_date=iso(-1), text="Надо бы убрать склад",
                   reason=vozmozhnye.НЕТ_АДРЕСАТА, state="новое", created_at=vozmozhnye.now())
    lst = c.get("/possible-assignments", headers=h()).json()
    assert lst["unresolved"] == 1 and lst["items"][0]["description"] == "Надо бы убрать склад"
    assert c.get("/badges", headers=h()).json()["possible"] == 1
    r = c.post(f"/possible-assignments/{pa}/to-task", json={"responsible": "Петров Илья"}, headers=h()).json()
    assert r["state"] == "в задачу" and c.get(f"/tasks/{r['task_id']}", headers=h()).json()["responsible_text"] == "Петров Илья"
    assert c.post(f"/possible-assignments/{pa}/not-task", headers=h()).status_code == 409
    assert c.get("/possible-assignments/threshold", headers=h()).json()["enabled"] is False
    assert c.put("/possible-assignments/threshold", json={"enabled": True}, headers=h()).json()["enabled"] is True
    assert c.put("/possible-assignments/settings", json={"days": 400}, headers=h()).status_code == 400


def test_порог_сборки_задача_без_адресата_в_возможные(make_pipe, store, project):
    from meetflow.core import vozmozhnye
    from conftest import TRANSCRIPT as TR
    vozmozhnye.задать(store, True)
    p = make_pipe()
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    p.ingest(project, mid, "t 01.10.2026.txt", TR.encode())
    start = vozmozhnye.now()
    tid = p.reg.add(project, "Обновить спецификации склада", None, mid, "обновить спецификации")
    assert vozmozhnye.разделить_после_сборки(store, p.reg, project, mid, start) == 1
    assert store.get("tasks", tid)["status"] == "dropped"
    assert store.q("SELECT text FROM possible_assignments")[0]["text"] == "Обновить спецификации склада"


def test_правила_оператора_отмена_и_возврат(env):
    c, h, st = env, env.h, env.st
    rid = st.insert("operator_rules", project_id=env.pid, kind="not_a_task", key="уборк склад", active=1,
                    created_at="2026-10-27T09:00:00")
    assert c.get("/operator-rules", headers=h()).json()[0]["state"] == "действует"
    c.post(f"/operator-rules/{rid}/revoke", headers=h())
    assert c.get("/operator-rules", headers=h()).json()[0]["state"] == "отменено"
    c.post(f"/operator-rules/{rid}/restore", headers=h())
    assert c.get("/operator-rules", headers=h()).json()[0]["state"] != "отменено"


# --- группа ж: «Параметры системы», «Мониторинг RealTime», «Модели», «База голосов», «Разбор голосов», темы ----------

def test_мониторинг_вид_erp_и_только_суперадмину(env):
    c, h = env, env.h
    assert c.get("/project-status/monitoring", headers=h("project_admin")).status_code == 403
    d = c.get("/project-status/monitoring", headers=h()).json()
    for k in ("services_live", "watch_folder", "recognition", "queues", "autorun", "awaiting_total", "llm_cost",
              "runs_14_days", "llm_usage_7_days", "data_state", "paths", "disk", "auto_backup", "server", "roles",
              "conflict_drop_unresolved_days", "service_log_keep_days", "auth_required"):
        assert k in d, k
    assert all({"name", "ok", "detail"} <= set(s) for s in d["services_live"])
    assert d["queues"]["conflicts_norm"]["norm"] == 15
    # «Все проекты» — папка не показывается: у каждого проекта своя
    d0 = c.get("/project-status/monitoring", headers=h(project=0)).json()
    assert d0["watch_folder"]["folder"] == "" and "выберите проект" in d0["watch_folder"]["poll_every_note"]


def test_идущий_проход_папки_не_завис(env, tmp_path):
    """Пульс прохода (dbc24a5) сохранён: идущий проход папки — «идёт проход…», а не «завис»."""
    import time
    c = env
    intake = c.app.state.intake
    intake._scanning[c.pid] = {"started": "2026-10-27T10:00:00", "step": "распознавание", "file": "a.mp3",
                               "pulse": time.monotonic()}
    st = intake.state(c.pid)
    assert st["scan_in_progress"] and not st["stalled"]


def test_папка_приёмник_по_проекту_в_два_шага_с_паролем(env, tmp_path):
    c, h = env, env.h
    from meetflow.web.erp.bezopasnost import hash_password
    c.st.update("accounts", c.ids["super_admin"], password_hash=hash_password("Пароль-для-проверки-1"))
    folder = tmp_path / "vhod"
    folder.mkdir()
    r = c.post("/project-status/watch-folder", json={"path": str(folder)}, headers=h(project=0))
    assert r.status_code == 400 and "выберите проект" in r.json()["detail"]
    q = c.post("/project-status/watch-folder", json={"path": str(folder)}, headers=h()).json()
    assert "Склад" in q["question"] and q["preview"]["files_total"] == 0
    bad = c.post("/project-status/watch-folder", json={"path": str(folder), "repeat_path": str(folder), "confirm": True,
                                                       "current_password": "не тот"}, headers=h())
    assert bad.status_code == 403
    ok = c.post("/project-status/watch-folder", json={"path": str(folder), "repeat_path": str(folder), "confirm": True,
                                                      "current_password": "Пароль-для-проверки-1"}, headers=h())
    assert ok.status_code == 200, ok.text
    assert Path(c.app.state.intake.folder(c.pid)) == folder.resolve()
    other = c.post("/project-status/watch-folder", json={"path": str(folder)}, headers=h(project=c.pid2))
    assert other.status_code == 400 and "другого проекта" in other.json()["detail"]
    assert c.post("/project-status/watch-folder/interval", json={"seconds": 120}, headers=h()).json() == {"seconds": 120}
    assert c.get("/project-status/monitoring", headers=h()).json()["watch_folder"]["poll_every_sec"] == 120


def test_выключатели_и_сроки(env):
    c, h = env, env.h
    assert c.post("/project-status/autorun", json={"enabled": True}, headers=h()).json() == {"enabled": True}
    assert c.get("/project-status/autorun", headers=h(project=c.pid2)).json() == {"enabled": False}
    assert c.post("/project-status/conflict-drop-days", json={"days": 0}, headers=h()).status_code == 400
    assert c.post("/project-status/conflict-drop-days", json={"days": 5}, headers=h()).json() == {"days": 5}
    assert c.post("/project-status/service-log-keep", json={"days": 14}, headers=h()).json() == {"days": 14}
    assert c.get("/project-status/monitoring", headers=h()).json()["service_log_keep_days"] == 14
    sub = c.post("/project-status/system-subprojects", json={"items": [{"name": "Склад А"}, {"name": "Склад А"}]},
                 headers=h()).json()
    assert sub["items"] == [{"name": "Склад А"}] and sub["all"] == "Весь проект Склад"
    sp = c.post("/project-status/system-project", json={"name": "Склад Северный", "aliases": "Северный; СС"}, headers=h())
    assert sp.json() == {"name": "Склад Северный", "aliases": "Северный; СС"}


def test_общий_пароль_закрывает_сессии_по_нему(env):
    c, h = env, env.h
    assert c.get("/project-status/shared-password", headers=h()).json()["is_set"] is False
    cols = {r["name"] for r in c.st.q("PRAGMA table_info(sessions)")}
    vals = {"account_id": c.ids["member"], "token": "t-1", "via_shared": 1, "created_at": "2026-10-27T10:00:00",
            "expires_at": "2099-01-01T00:00:00"}
    sid = c.st.insert("sessions", **{k: v for k, v in vals.items() if k in cols})
    assert c.post("/project-status/shared-password", json={"new_password": "123"}, headers=h()).status_code == 400
    r = c.post("/project-status/shared-password",
               json={"new_password": "Север-Склад-27x", "repeat_password": "Север-Склад-27x"}, headers=h()).json()
    assert r["is_set"] and r["sessions_closed"] == 1 and c.st.get("sessions", sid) is None


def test_системные_сообщения_закрыть_и_удалить(env):
    from meetflow.core.store import now
    c, h = env, env.h
    for i in range(3):
        c.st.insert("cards", kind="technical", title=f"Сбой {i}", payload='{"message": "проверка"}', status="open",
                    created_at=now())
    d = c.get("/project-status/errors?with_total=true", headers=h()).json()
    assert d["total"] == 3 and {"id", "created_at", "source", "context", "message", "resolved"} <= set(d["items"][0])
    assert c.post(f"/project-status/errors/{d['items'][0]['id']}/resolve", headers=h()).status_code == 204
    assert c.get("/project-status/errors/count", headers=h()).json()["count"] == 2
    assert c.post("/project-status/errors/delete-all", json={}, headers=h()).status_code == 400
    assert c.post("/project-status/errors/delete-all", json={"confirm": True}, headers=h()).json()["count"] == 3


def test_ожидает_ввода_вид_erp(env):
    c, h = env, env.h
    d = c.get("/project-status/awaiting-input", headers=h()).json()
    assert {"total", "groups", "note", "under_question"} <= set(d)
    for g in d["groups"]:
        assert {"title", "count", "what", "consequence", "where", "where_text"} <= set(g)


def test_темы_планёрок_день_недели_и_выбор_вручную(env):
    c, h = env, env.h
    mon = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=7)
    mid = c.st.insert("meetings", project_id=c.pid, date=mon.isoformat(), status="planned")
    assert c.post("/meeting-topics", json={"name": "Стройка"}, headers=h("project_admin")).status_code == 403
    t = c.post("/meeting-topics", json={"name": "Стройка", "weekdays": [1], "sections": ["Объекты", "Сроки"]},
               headers=h()).json()
    assert t["weekdays"] == [1] and t["sections"] == ["Объекты", "Сроки"]
    assert c.post("/meeting-topics", json={"name": "стройка"}, headers=h()).status_code == 409
    got = c.get(f"/meeting-topics/meeting/{mid}", headers=h()).json()
    assert got["name"] == "Стройка" and got["source"] == "по дню недели"
    assert c.app.state.pipe._skeleton(c.st.get("meetings", mid)) == ["Объекты", "Сроки"]
    off = c.put(f"/meeting-topics/meeting/{mid}", json={"topic_id": None}, headers=h("project_admin")).json()
    assert off["name"] is None and off["source"] == "вручную"
    c.patch(f"/meeting-topics/{t['id']}", json={"is_active": False}, headers=h())
    assert c.put(f"/meeting-topics/meeting/{mid}", json={"topic_id": t["id"]}, headers=h()).status_code == 400


def test_словарь_распознавания(env):
    c, h = env, env.h
    d = c.get("/recognition-settings", headers=h()).json()
    assert {"asr_vocab", "project_only_heard"} <= set(d) and "Склад" in d["asr_vocab"]["preview"]
    d2 = c.put("/recognition-settings", json={"key": "asr_vocab", "enabled": True}, headers=h()).json()
    assert d2["asr_vocab"]["enabled"] is True and d2["asr_vocab"]["setting"] is True
    assert c.put("/recognition-settings", json={"key": "лишнее", "enabled": True}, headers=h()).status_code == 400


def test_база_и_разбор_голосов_без_базы(env):
    c, h = env, env.h
    assert c.get("/project-status/voice-base", headers=h()).json()["configured"] is False
    q = c.get("/voice/review", headers=h()).json()
    assert q["configured"] is False and q["gruppy"] == []
    assert c.post("/voice/review/decision", json={"ids": [1], "reshenie": "yes", "imya": "Иван"}, headers=h()).status_code == 400
    assert c.post("/voice/review/ne-po-pravilu", json={"ids": [1]}, headers=h()).status_code == 409


def test_модели_только_суперадмину(env):
    c, h = env, env.h
    assert c.get("/project-status/models", headers=h("project_admin")).status_code == 403
    assert c.post("/project-status/models/role", json={"role": "generate", "point": "x", "action": "move"},
                  headers=h()).status_code == 400


def test_проекты_завести_переименовать_архив(env):
    """Многопроектность — разрешённое отличие от ERP: «Параметры системы» → «Проекты»."""
    c, h = env, env.h
    assert c.get("/projects-list/all", headers=h("project_admin")).status_code == 403
    n = c.post("/projects-list", json={"name": "Цех сборки", "aliases": "ЦС; сборка"}, headers=h())
    assert n.status_code == 201 and n.json()["aliases"] == ["ЦС", "сборка"]
    assert c.post("/projects-list", json={"name": "цех  сборки"}, headers=h()).status_code == 409
    pid = n.json()["id"]
    assert c.patch(f"/projects-list/{pid}", json={"name": "Цех сборки 2", "aliases": ""}, headers=h()).json()["name"] == "Цех сборки 2"
    assert c.patch(f"/projects-list/{pid}", json={"archived": True}, headers=h()).json()["archived"] is True
    assert pid not in [p["id"] for p in c.get("/projects-list", headers=h()).json()]
    assert c.patch(f"/projects-list/{pid}", json={"archived": False}, headers=h()).json()["archived"] is False
    nav = (STATIC / "nav.js").read_text(encoding="utf-8")
    assert '{ k: "projects", label: "Проекты", href: "#system/projects" }' in nav and "async function renderProjectsAdmin()" in nav


def test_фронт_erp_v73_рассуждение_и_голоса():
    """Фронт ERP взят с b0d8ab7 (статика v73): «Модели» — рассуждение точки, «Ждут опознания голоса» открыта."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "рассуждениеТочки" in js
