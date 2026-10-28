"""«Общие встречи» и встречи по проекту (Доработка 2, решение владелицы 28.10.2026).

Две сущности: «Общие встречи» — служебный проект для встреч без проекта (его нельзя переименовать, убрать в архив и
удалить), и проекты со своими встречами. Проект можно завести, переименовать и удалить — встречи удалённого проекта уходят
в «Общие встречи». Встречу можно переименовать, перенести в проект или обратно и удалить: задачи удалённой встречи
снимаются с причиной «встреча удалена», удаление отменяется. Запись из общей папки-приёмника ложится в проект по имени
файла, иначе по содержанию расшифровки, иначе — в «Общие встречи». Данные вымышленные.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.core import proekt_zapisi as pz

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
    ceh = st.insert("projects", name="Цех", theme="erp_rollout", archived=0, aliases='["цеховой участок"]')
    ids = {r: st.insert("accounts", full_name=f, role=r, active=1, confirmed=1)
           for f, r in (("Орлова Анна", "super_admin"), ("Петров Илья", "project_admin"), ("Сидорова Вера", "member"))}

    def h(role="super_admin", project=0):
        return {**W, "X-User-Id": str(ids[role]), "X-Project-Id": str(project)}
    c.h, c.st, c.sklad, c.priemka, c.ceh = h, st, sklad, priemka, ceh
    c.general = pz.общие_встречи(st)
    return c


# --- узнавание проекта по содержанию -----------------------------------------------------------------------------------

def справочник():
    return [{"id": 1, "name": "Склад", "aliases": [], "parent_id": None},
            {"id": 2, "name": "Приёмка", "aliases": [], "parent_id": 1},
            {"id": 3, "name": "Цех", "aliases": ["цеховой участок"], "parent_id": None}]


def текст(*строки):
    return "\n".join(f"[00:0{i}:00] Игнатов Иван: {s}" for i, s in enumerate(строки))


def test_по_содержанию_порог_трёх_упоминаний():
    assert pz.по_содержанию(текст("По складу всё", "Склад закрыт"), справочник())["project_id"] is None
    r = pz.по_содержанию(текст("По складу всё", "Склад закрыт", "Остатки склада сверили"), справочник())
    assert r["project_id"] == 1 and r["how"] == "по содержанию записи: «Склад», упоминаний 3"


def test_по_содержанию_отрыв_от_второго():
    """Лучший кандидат должен быть назван хотя бы вдвое чаще второго — иначе «Общие встречи» с двумя кандидатами."""
    близко = текст("Склад", "склад", "склад", "цех", "цех")
    r = pz.по_содержанию(близко, справочник())
    assert r["project_id"] is None and "два проекта близко" in r["how"] and "«Цех», упоминаний 2" in r["how"]
    далеко = текст("Склад", "склад", "склад", "склад", "цех", "цех")
    assert pz.по_содержанию(далеко, справочник())["project_id"] == 1


def test_по_содержанию_вариант_написания_и_подпроект():
    r = pz.по_содержанию(текст("Цеховой участок", "цеховой участок готов", "цеховой участок сдан"), справочник())
    assert r["project_id"] == 3
    # подпроект назван трижды — выбирается он, а не надпроект: подпроект точнее и с надпроектом не соперничает
    r = pz.по_содержанию(текст("приёмка на складе", "приёмка идёт", "приемка закончена"), справочник())
    assert r["project_id"] == 2


def test_по_содержанию_ничего_не_названо():
    r = pz.по_содержанию(текст("Добрый день", "Начинаем"), справочник())
    assert r["project_id"] is None and r["how"].startswith("в общих встречах: проект не назван")


def test_общие_встречи_вне_узнавания(env):
    assert env.general not in {п["id"] for п in pz.проекты(env.st)}
    assert pz.общие_встречи(env.st) == env.general           # второй раз не заводится


# --- проекты: список, правка, удаление -------------------------------------------------------------------------------

def test_список_начинается_с_общих_встреч(env):
    rows = env.get("/projects-list", headers=env.h()).json()
    assert rows[0]["name"] == "Общие встречи" and rows[0]["general"] is True
    assert all(r["general"] is False for r in rows[1:])


def test_общие_встречи_не_правятся_и_не_удаляются(env):
    g = env.general
    assert env.patch(f"/projects-list/{g}", json={"name": "Другое"}, headers=env.h()).status_code == 400
    assert env.patch(f"/projects-list/{g}", json={"archived": True}, headers=env.h()).status_code == 400
    assert env.delete(f"/projects-list/{g}", headers=env.h()).status_code == 400


def test_удаление_проекта_уводит_встречи_в_общие(env):
    st = env.st
    m1 = st.insert("meetings", project_id=env.sklad, date="2026-10-20")
    m2 = st.insert("meetings", project_id=env.priemka, date="2026-10-21")
    t = st.insert("tasks", project_id=env.sklad, description="Проверить пломбы на складе", status="active",
                  source_meeting_id=m1, date_set="2026-10-20")
    ручная = st.insert("tasks", project_id=env.sklad, description="Сверить остатки склада", status="active",
                       date_set="2026-10-20")
    assert env.delete(f"/projects-list/{env.sklad}", headers=env.h("project_admin")).status_code == 403
    r = env.delete(f"/projects-list/{env.sklad}", headers=env.h())
    assert r.status_code == 200 and r.json()["meetings_moved"] == 2
    assert st.get("meetings", m1)["project_id"] == env.general and st.get("meetings", m2)["project_id"] == env.general
    assert st.get("tasks", t)["project_id"] == env.general and st.get("tasks", ручная)["project_id"] == env.general
    names = [x["name"] for x in env.get("/projects-list", headers=env.h()).json()]
    assert "Склад" not in names and "Приёмка" not in names
    assert env.sklad not in {п["id"] for п in pz.проекты(st)}
    assert env.delete(f"/projects-list/{env.sklad}", headers=env.h()).status_code == 404
    # имя удалённого проекта снова свободно
    assert env.post("/projects-list", json={"name": "Склад"}, headers=env.h()).status_code == 201


def test_последний_проект_в_архив_не_уходит_без_учёта_общих(env):
    env.delete(f"/projects-list/{env.ceh}", headers=env.h())
    r = env.patch(f"/projects-list/{env.sklad}", json={"archived": True}, headers=env.h())
    assert r.status_code == 400 and "Последний" in r.json()["detail"]


# --- встречи: переименовать, перенести, удалить с отменой -------------------------------------------------------------

def test_переименовать_встречу(env):
    mid = env.st.insert("meetings", project_id=env.sklad, date="2026-10-20")
    r = env.patch(f"/meetings/{mid}/label", json={"label": "  Приёмка   металла "}, headers=env.h("project_admin"))
    assert r.status_code == 200 and r.json()["label"] == "Приёмка металла"
    assert env.patch(f"/meetings/{mid}/label", json={"label": ""}, headers=env.h()).json()["label"] is None
    assert env.patch(f"/meetings/{mid}/label", json={"label": "x"}, headers=env.h("member")).status_code == 403


def test_перенос_встречи_в_общие_и_обратно(env):
    st = env.st
    mid = st.insert("meetings", project_id=env.sklad, date="2026-10-20")
    tid = st.insert("tasks", project_id=env.sklad, description="Проверить пломбы", status="active",
                    source_meeting_id=mid, date_set="2026-10-20")
    for куда in (env.general, env.ceh):
        r = env.post(f"/meetings/{mid}/move-project", json={"project_id": куда, "rebuild": False}, headers=env.h())
        assert r.status_code == 200, r.text
        assert st.get("meetings", mid)["project_id"] == куда and st.get("tasks", tid)["project_id"] == куда
    assert r.json()["meeting"]["general"] is False


def test_удаление_встречи_с_задачами_и_отмена(env):
    st = env.st
    mid = st.insert("meetings", project_id=env.sklad, date="2026-10-20", protocol_md="# Протокол")
    a = st.insert("tasks", project_id=env.sklad, description="Проверить пломбы", status="active",
                  source_meeting_id=mid, date_set="2026-10-20")
    done = st.insert("tasks", project_id=env.sklad, description="Сверить остатки", status="done",
                     source_meeting_id=mid, date_set="2026-10-20")
    card = st.insert("cards", project_id=env.sklad, meeting_id=mid, kind="closing_candidate", title="к", status="open")
    chk = env.get(f"/meetings/{mid}/delete-check", headers=env.h()).json()
    assert chk["can_delete"] is False and chk["can_delete_with_tasks"] is True
    assert "Её задачи (1) будут сняты" in chk["with_tasks_text"]
    # без согласия на снятие задач — прежний отказ
    assert env.delete(f"/meetings/{mid}", headers=env.h()).status_code == 400
    r = env.delete(f"/meetings/{mid}?with_tasks=true", headers=env.h())
    assert r.status_code == 200 and r.json()["tasks_dropped"] == 1 and r.json()["can_undo"] is True
    assert st.get("tasks", a)["status"] == "dropped" and st.get("tasks", done)["status"] == "done"
    assert st.q("SELECT * FROM task_history WHERE task_id=? AND evidence_quote='встреча удалена'", (a,))
    assert st.get("cards", card)["status"] == "rejected"
    assert mid not in [m["id"] for m in env.get("/meetings", headers=env.h(project=env.sklad)).json()]
    assert env.get(f"/meetings/{mid}", headers=env.h()).status_code == 404
    # отмена: задача снова в работе, карточка открыта, встреча видна
    r = env.post(f"/meetings/{mid}/restore", headers=env.h())
    assert r.status_code == 200
    assert st.get("tasks", a)["status"] == "active" and st.get("cards", card)["status"] == "open"
    assert mid in [m["id"] for m in env.get("/meetings", headers=env.h(project=env.sklad)).json()]


def test_удалённая_встреча_не_питает_план(env):
    from meetflow.core import plan
    st = env.st
    old = st.insert("meetings", project_id=env.sklad, date="2026-10-20", protocol_md="# Протокол 20.10\nСтарое")
    new = st.insert("meetings", project_id=env.sklad, date="2026-10-27")
    env.delete(f"/meetings/{old}?with_tasks=true", headers=env.h())
    src = Path(plan.__file__).read_text(encoding="utf-8")
    assert "deleted_at IS NULL" in src
    rows = st.q("SELECT id FROM meetings WHERE deleted_at IS NULL AND project_id=? AND id<>?", (env.sklad, new))
    assert old not in [r["id"] for r in rows]


# --- экран: блок «Проекты» и действия со встречей ---------------------------------------------------------------------

def test_экран_блок_проектов_и_меню_встречи():
    js = (STATIC / "app.js").read_text(encoding="utf-8") + (STATIC / "nav.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="project-list"' in html and 'id="project-select"' in html
    for фраза in ("Общие встречи", "+ Новый проект", "Переименовать", "Удалить", "Переместить в проект",
                  "/projects-list/", "/move-project", "/restore", "with_tasks=true", "/label"):
        assert фраза in js, фраза


def test_число_встреч_проекта_свежее_после_переноса():
    """Отчёт ЛМ 83714c5, шаг 4 (29.10.2026): после «Переместить в проект…» окно удаления проекта без Ctrl+F5 писало
    «Встреч в нём нет». Теперь после переноса и удаления встречи список проектов перечитывается, а окно удаления проекта
    берёт число встреч с сервера."""
    nav = (STATIC / "nav.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    перенос = nav[nav.index("function перенестиВстречу(m)"):nav.index("function уведомлениеСОтменой")]
    assert перенос.index("await загрузитьПроекты();") < перенос.index("renderProtocols();", перенос.index("move-project"))
    удаление = nav[nav.index("function менюВстречи("):nav.index("function перенестиВстречу(m)")]
    assert удаление.count("await загрузитьПроекты();") == 2
    окно = app[app.index("$m.querySelector('[data-act=\"delete\"]')"):app.index("function нуженПроект(")]
    assert окно.index("await загрузитьПроекты();") < окно.index("Встреч в нём")
