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
