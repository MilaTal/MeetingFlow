"""Проект и подпроекты MeetFlow после переноса экранов ERP (27.10.2026).

Справочник ЛМ 6c6933f (`projects.parent_id`, варианты написания, архив) возвращён в экраны ERP: подпроект — проект с
надпроектом. Выбор проекта показывает его вместе с подпроектами, выбор подпроекта — только его. Подпроект задачи и встречи —
поле (вид ERP `PATCH /tasks/{id}/subproject`, только из справочника), фильтр проекта в реестре и договорённостях, приставка
«Проект – Подпроект:» формулировки на экране, отборы «Все проекты» по проекту и подпроекту. Данные вымышленные.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"
W = {"X-Requested-With": "erp-webapp"}


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    sklad = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    priemka = st.insert("projects", name="Приёмка", theme="erp_rollout", archived=0, parent_id=sklad)
    ceh = st.insert("projects", name="Цех", theme="erp_rollout", archived=0)
    ids = {r: st.insert("accounts", full_name=f, role=r, active=1, confirmed=1)
           for f, r in (("Орлова Анна", "super_admin"), ("Петров Илья", "project_admin"), ("Сидорова Вера", "member"))}

    def h(role="super_admin", project=0):
        return {**W, "X-User-Id": str(ids[role]), "X-Project-Id": str(project)}
    c.h, c.st, c.sklad, c.priemka, c.ceh = h, st, sklad, priemka, ceh
    return c


def task(st, pid, text):
    return st.insert("tasks", project_id=pid, description=text, status="active", date_set="2026-10-20")


def test_выбор_проекта_деревом_и_подписи(env):
    c = env
    rows = c.get("/projects-list", headers=c.h()).json()
    assert [(r["name"], r["level"], r["label"]) for r in rows] == [
        ("Общие встречи", 0, "Общие встречи"),  # «Общие встречи» — первой строкой (Доработка 2, 28.10.2026)
        ("Склад", 0, "Склад"), ("Приёмка", 1, "Склад – Приёмка"), ("Цех", 0, "Цех")]
    c.st.update("projects", c.priemka, archived=1)
    assert "Приёмка" not in [r["name"] for r in c.get("/projects-list", headers=c.h()).json()]


def test_справочник_надпроект_кольцо_и_архив(env):
    c, h = env, env.h
    n = c.post("/projects-list", json={"name": "Отгрузка", "aliases": "отгрузки; ОТГ", "parent_id": c.sklad}, headers=h())
    assert n.status_code == 201 and n.json()["label"] == "Склад – Отгрузка" and n.json()["aliases"] == ["отгрузки", "ОТГ"]
    assert c.patch(f"/projects-list/{c.sklad}", json={"parent_id": c.priemka}, headers=h()).status_code == 422
    assert c.patch(f"/projects-list/{c.sklad}", json={"parent_id": c.sklad}, headers=h()).status_code == 422
    rows = {r["id"]: r for r in c.get("/projects-list/all", headers=h()).json()}
    assert rows[c.priemka]["parent_name"] == "Склад" and rows[c.priemka]["level"] == 1
    # подпроект в архив можно, даже когда проект верхнего уровня один из двух
    assert c.patch(f"/projects-list/{c.priemka}", json={"archived": True}, headers=h()).json()["archived"] is True


def test_проект_вместе_с_подпроектами_подпроект_отдельно(env):
    c, h = env, env.h
    a, b, d = task(c.st, c.sklad, "Склад: опись"), task(c.st, c.priemka, "Акт приёмки"), task(c.st, c.ceh, "Наладка")
    got = lambda p: {t["id"] for t in c.get("/tasks?status=active", headers=h(project=p)).json()}  # noqa: E731
    assert got(c.sklad) == {a, b} and got(c.priemka) == {b} and got(0) == {a, b, d}
    rows = {t["id"]: t for t in c.get("/tasks?status=active", headers=h(project=0)).json()}
    assert rows[b]["project_root"] == "Склад" and rows[b]["subproject"] == "Приёмка"
    assert rows[a]["subproject"] is None and rows[d]["project_root"] == "Цех"


def test_подпроект_задачи_только_из_справочника(env):
    c, h = env, env.h
    t = task(c.st, c.sklad, "Опись стеллажей")
    r = c.patch(f"/tasks/{t}/subproject", json={"subproject": "приемка"}, headers=h("project_admin", c.sklad))
    assert r.status_code == 200 and r.json()["subproject"] == "Приёмка" and c.st.get("tasks", t)["project_id"] == c.priemka
    assert c.patch(f"/tasks/{t}/subproject", json={"subproject": "Цех"}, headers=h("project_admin", c.sklad)).status_code == 400
    back = c.patch(f"/tasks/{t}/subproject", json={"subproject": ""}, headers=h("project_admin", c.sklad)).json()
    assert back["subproject"] is None and c.st.get("tasks", t)["project_id"] == c.sklad
    assert any("подпроект -> Приёмка" in (x["evidence_quote"] or "") for x in c.st.q("SELECT * FROM task_history WHERE task_id=?", (t,)))
    assert c.patch(f"/tasks/{t}/subproject", json={"subproject": "Приёмка"}, headers=h("member", c.sklad)).status_code == 403


def test_подпроекты_карточки_проекта_это_справочник(env):
    c, h = env, env.h
    d = c.post("/project-status/system-subprojects", json={"items": [{"name": "Отгрузка"}, {"name": "приемка"}]},
               headers=h(project=c.sklad)).json()
    assert sorted(x["name"] for x in d["items"]) == ["Отгрузка", "приемка"]
    otg = c.st.q("SELECT * FROM projects WHERE name='Отгрузка'")[0]
    assert otg["parent_id"] == c.sklad
    c.post("/project-status/system-subprojects", json={"items": [{"name": "Отгрузка"}]}, headers=h(project=c.sklad))
    assert c.st.get("projects", c.priemka)["archived"] == 1          # убранный — в архив, не удалён
    assert c.post("/project-status/system-subprojects", json={"items": [{"name": "Цех"}]},
                  headers=h(project=c.sklad)).status_code == 409


def test_договорённости_фильтр_проекта_и_подпроекта(env):
    c, h = env, env.h
    m1 = c.st.insert("meetings", project_id=c.sklad, date="2026-10-20")
    m2 = c.st.insert("meetings", project_id=c.priemka, date="2026-10-21")
    m3 = c.st.insert("meetings", project_id=c.ceh, date="2026-10-22")
    for pid, mid, text in ((c.sklad, m1, "Склад общий"), (c.priemka, m2, "Приёмка по акту"), (c.ceh, m3, "Цех наладка")):
        c.st.insert("units", project_id=pid, meeting_id=mid, kind="agreement", text=text, status="active")
    d = c.get("/agreements", headers=h(project=c.sklad)).json()
    assert d["project_filter"]["all"] == "Весь проект Склад" and d["project_filter"]["options"] == ["Приёмка"]
    assert {x["text"] for x in d["items"]} == {"Склад общий", "Приёмка по акту"}
    assert [x["text"] for x in c.get("/agreements?project=Приёмка", headers=h(project=c.sklad)).json()["items"]] == ["Приёмка по акту"]
    assert [x["text"] for x in c.get("/agreements?project=__none__", headers=h(project=c.sklad)).json()["items"]] == ["Склад общий"]
    allp = c.get("/agreements", headers=h(project=0)).json()
    assert allp["project_filter"]["options"] == ["Общие встречи", "Склад", "Склад – Приёмка", "Цех"]  # «Общие встречи» — первой строкой (Доработка 2, 28.10.2026)
    assert {x["text"] for x in c.get("/agreements?project=Склад", headers=h(project=0)).json()["items"]} == {"Склад общий", "Приёмка по акту"}
    assert [x["subproject"] for x in c.get("/agreements?project=Склад – Приёмка", headers=h(project=0)).json()["items"]] == ["Склад – Приёмка"]


def test_подпроект_встречи(env):
    c, h = env, env.h
    mid = c.st.insert("meetings", project_id=c.sklad, date="2026-10-20")
    sp = c.get(f"/meetings/{mid}/subprojects", headers=h(project=c.sklad)).json()
    assert sp["project"] == "Склад" and [x["name"] for x in sp["items"]] == ["Приёмка"] and sp["current"] == ""
    m = c.patch(f"/meetings/{mid}/subproject", json={"subproject": "Приёмка"}, headers=h("project_admin", c.sklad)).json()
    assert m["project_label"] == "Склад – Приёмка" and m["subproject"] == "Приёмка"
    assert c.patch(f"/meetings/{mid}/subproject", json={"subproject": "Цех"}, headers=h("project_admin", c.sklad)).status_code == 400
    assert mid in [x["id"] for x in c.get("/meetings", headers=h(project=c.sklad)).json()]
    assert mid not in [x["id"] for x in c.get("/meetings", headers=h(project=c.ceh)).json()]


def test_экран_приставка_фильтр_и_дерево():
    reg = (STATIC / "registry.js").read_text(encoding="utf-8")
    assert "function реестрПриставка(t)" in reg and 'id="reg-proj"' in reg and "без подпроекта" in reg
    assert "`${t.project_root} – ${t.subproject}`" in reg
    nav = (STATIC / "nav.js").read_text(encoding="utf-8")
    assert 'class="prj-parent"' in nav and "Надпроект" in nav
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'repeat(п.level || 0)' in app
    meet = (STATIC / "meeting.js").read_text(encoding="utf-8")
    assert "/subproject`, { method: \"PATCH\"" in meet


def test_прежние_подпроекты_переносятся_в_справочник(tmp_path):
    from meetflow.core.store import Store
    from meetflow.web.app import create_app
    db = str(tmp_path / "t.db")
    st = Store(db)
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    st.set_setting("subprojects", ["Отгрузка"], pid)
    tid = st.insert("tasks", project_id=pid, description="Отгрузить партию", status="active", subproject="отгрузка")
    st.close()
    app = create_app("erp_rollout", db, str(tmp_path / "j.jsonl"), watch=False)
    s = app.state.store
    otg = s.q("SELECT * FROM projects WHERE name='Отгрузка'")[0]
    assert otg["parent_id"] == pid and s.get("tasks", tid)["project_id"] == otg["id"] and not s.get("tasks", tid)["subproject"]
    create_app("erp_rollout", db, str(tmp_path / "j.jsonl"), watch=False)
    assert len(s.q("SELECT * FROM projects WHERE name='Отгрузка'")) == 1


def test_окно_правки_задачи_проект_и_подпроект(env):
    c, h = env, env.h
    rows = c.get("/tasks/projects", headers=h("project_admin", c.sklad)).json()
    assert [r["name"] for r in rows] == ["Общие встречи", "Склад", "Склад – Приёмка", "Цех"]  # «Общие встречи» — первой строкой (Доработка 2, 28.10.2026)
    t = task(c.st, c.sklad, "Сверить остатки")
    r = c.patch(f"/tasks/{t}/project", json={"project_id": c.priemka}, headers=h("project_admin", c.sklad)).json()
    assert r["subproject"] == "Приёмка"
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '<label for="modal-project">Проект и подпроект</label>' in app
