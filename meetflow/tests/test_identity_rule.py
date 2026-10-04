"""Правило «один человек или два» — решение владельца 03.10.26 (документ
meeting-registry «11_Решение — один человек или два», письма 10 и 11).
Владелец в сессии MeetFlow: «действуй, как там решено». Тесты написаны до кода.

Порядок для одного упоминания: отдел → руководитель; рабочий ключ у одного и
нет несовпадения — назначить; ключ общий, имя названо — по имени; ключ общий
без имени — карточка с подсказками; признак несовпадения — карточка «тот же
или новый»; совпадения нет — «нет в Команде». Модель не участвует."""
import json

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.people import Team
from meetflow.core.types import Person
from meetflow.web.app import create_app

NAZ = Person("Назаров Константин", id=1)
GAVR = Person("Гаврилов Павел", id=2)


# ------------------------------------------------------------------ рабочие ключи
@pytest.mark.parametrize("mention", ["Назаров", "Назарову", "Константин"])
def test_working_key_assigns(mention):
    assert Team([NAZ, GAVR]).find(mention).person is NAZ


def test_shared_key_needs_first_name():
    t = Team([NAZ, GAVR, Person("Назаров Андрей", id=3)])
    m = t.find("Назаров")
    assert m.person is None and {p.id for p in m.candidates} == {1, 3}
    assert t.find("Константин Назаров").person is NAZ


def test_diminutive_is_a_key():
    t = Team([Person("Орлова Мария", id=5), GAVR], diminutives={"маша": ["мария"]})
    assert t.find("Маша").person.id == 5
    t2 = Team([Person("Орлова Мария", id=5), Person("Белова Мария", id=6)], diminutives={"маша": ["мария"]})
    assert t2.find("Маша").person is None and len(t2.find("Маша").candidates) == 2


# ------------------------------------------------------------------ несовпадение
@pytest.mark.parametrize("context,marks", [
    ("Гаврилов Павел: Подрядчик Игнатов из ТМК, пришлите график монтажа.", True),
    ("Гаврилов Павел: Игнатов, пришлите график монтажа.", False),
])
def test_foreign_org_near_key_is_same_or_new(context, marks):
    t = Team([Person("Игнатов Иван", id=7), GAVR])
    m = t.find("Игнатов", context=context)
    if marks:
        assert m.person is None and m.via == "same_or_new" and [p.id for p in m.candidates] == [7]
        assert any("подрядчик" in x.lower() or "тмк" in x.lower() for x in m.marks)
    else:
        assert m.person.id == 7


def test_other_department_in_phrase_is_mark_not_hold():
    """Перевёрнут 03.10.26 решением владельца (письмо 22 meeting-registry): другой отдел в фразе
    задачу не задерживает — назначается по ключу, рядом карточка «отдел не совпадает»."""
    t = Team([Person("Игнатов Иван", department="склад", id=7), Person("Петрова Анна", department="бухгалтерия", id=8)])
    m = t.find("Игнатов", context="Гаврилов: Игнатов из бухгалтерии, подготовьте акт.")
    assert m.person is not None and m.person.id == 7 and m.dept_marks


def test_external_new_topic_is_mismatch():
    ext = Person("Смирнов", external=True, organization="ТМК", role="инженер", id=9)
    t = Team([ext, GAVR], tasks=[{"assignee": "Смирнов (ТМК)", "description": "Прислать график монтажа опор",
                                 "date_set": "2026-09-20"}], today="2026-10-01")
    assert t.find("Смирнов", context="Смирнов, пришлите график монтажа", description="Прислать график монтажа").person is ext
    m = t.find("Смирнов", context="Смирнов, оплатите счёт за аренду", description="Оплатить счёт за аренду")
    assert m.person is None and m.via == "same_or_new"


def test_accepted_mark_stops_asking():
    t = Team([Person("Игнатов Иван", id=7, known_marks=["подрядчик", "тмк"]), GAVR])
    assert t.find("Игнатов", context="Подрядчик Игнатов из ТМК, пришлите график.").person.id == 7


# ------------------------------------------------------------------ внешние
EXT = [Person("Иван", external=True, organization="ТМК", role="инженер", id=10),
       Person("Иван", external=True, organization="Газпром", role="куратор", id=11)]


def test_external_split_by_org():
    t = Team(EXT + [GAVR])
    assert t.find("Иван из ТМК").person.id == 10
    assert t.find("Иван", context="Иван из Газпрома, пришлите акт").person.id == 11
    m = t.find("Иван", context="Иван, пришлите акт испытаний")
    assert m.person is None and {p.id for p in m.candidates} == {10, 11}


# ------------------------------------------------------------------ конвейер и экран
class Say(MockLLM):
    def __init__(self, who, desc, line):
        super().__init__()
        self.who, self.desc, self.line = who, desc, line

    def _extract(self, data):
        return {"tasks": [{"description": self.desc, "assignee": self.who, "quote": self.line}]}


def _run(store, project, make_pipe, who, line, d="2026-10-01", desc="Прислать график монтажа"):
    mid = store.insert("meetings", project_id=project, date=d, label="встреча")
    p = make_pipe(gen=Say(who, desc, line))
    p.ingest(project, mid, f"t {d[8:]}.{d[5:7]}.{d[:4]}.txt", f"[00:01:00] {line}\n".encode())
    return mid, p.run(project, mid)


def test_pipeline_same_or_new_card_then_this_is_him(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    H = {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    for n in ("Игнатов Иван", "Гаврилов Павел"):
        c.post(f"/api/projects/{pid}/people", json={"full_name": n}, headers=H)
    pipe = app.state.pipe
    pipe.gen = Say("Игнатов", "Прислать график монтажа", "Гаврилов Павел: Подрядчик Игнатов из ТМК, пришлите график монтажа")

    def meet(d):
        mid = c.post(f"/api/projects/{pid}/meetings", json={"date": d}, headers=H).json()["id"]
        c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": (
            f"t {d[8:]}.{d[5:7]}.{d[:4]}.txt",
            "[00:01:00] Гаврилов Павел: Подрядчик Игнатов из ТМК, пришлите график монтажа\n".encode())})
        return c.post(f"/api/meetings/{mid}/run", headers=H).json()
    # перевёрнут 03.10.26 по письму 30 оркестратора (решение владельца): задача сразу без исполнителя,
    # рядом карточка assign_person; выбор ставит исполнителя в ту же задачу
    r1 = meet("2026-10-01")
    assert r1["tasks_added"] == 1
    assert [t["assignee"] for t in c.get(f"/api/projects/{pid}/tasks", headers=H).json()] == [None]
    card = next(x for x in c.get(f"/api/projects/{pid}/cards", headers=H).json()
                if x["kind"] == "assign_person" and x["payload"]["reason"] == "same_or_new")
    assert card["payload"]["marks"]
    c.post(f"/api/cards/{card['id']}/resolve", json={"status": "accepted", "choice": "Игнатов Иван"}, headers=H)
    assert [t["assignee"] for t in c.get(f"/api/projects/{pid}/tasks", headers=H).json()] == ["Игнатов Иван"]
    pipe.gen = Say("Игнатов", "Прислать акт монтажа", "Гаврилов Павел: Подрядчик Игнатов из ТМК, пришлите акт монтажа")
    r2 = meet("2026-10-08")                                          # «через неделю» — без карточки
    assert r2["tasks_added"] == 1


def test_old_tasks_unchanged_when_key_becomes_shared(store, project, make_pipe):
    p = make_pipe()
    tid = p.reg.add(project, "Подготовить спецификацию", "Назаров Константин", date_set="2026-09-01")
    store.insert("people", project_id=project, full_name="Назаров Андрей")
    _run(store, project, make_pipe, "Назаров", "Игнатов Иван: Спасибо, дальше.")
    assert store.get("tasks", tid)["assignee"] == "Назаров Константин"


# ------------------------------------------------------------------ заведение людей
def test_people_form_rules(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    H = {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    url = f"/api/projects/{pid}/people"
    assert c.post(url, json={"full_name": "Назаров"}, headers=H).status_code == 422          # своим — фамилия и имя
    assert c.post(url, json={"full_name": "Иван", "external": True}, headers=H).status_code == 422   # внешнему —
    assert c.post(url, json={"full_name": "Иван", "external": True, "organization": "ТМК",          # организация и роль
                             "role": "инженер"}, headers=H).status_code == 200
    rows = c.get(url).json()
    assert rows[0]["organization"] == "ТМК"


def test_card_choice_by_id_not_by_name(tmp_path):
    """Письмо 19 (по ответу ERP): выбор в карточке — по id, а не по строке ФИО. В старых данных
    могут лежать два «Игнатов Иван»; «это он» должно попасть ровно одному."""
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    H = {"X-User-Role": "project_admin"}
    s = app.state.store
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    a = s.insert("people", project_id=pid, full_name="Игнатов Иван")
    b = s.insert("people", project_id=pid, full_name="Игнатов Иван")          # дубль из старых данных
    cid = s.insert("cards", project_id=pid, kind="held_task", title="t", status="open",
                   payload={"description": "Прислать график", "reasons": ["same_or_new"], "marks": ["подрядчик"],
                            "candidates": [{"id": a, "name": "Игнатов Иван", "hints": []},
                                           {"id": b, "name": "Игнатов Иван", "hints": []}]})
    r = c.post(f"/api/cards/{cid}/resolve", json={"status": "accepted", "choice": str(b)}, headers=H)
    assert r.status_code == 200
    marks = {p["id"]: json.loads(p["known_marks"]) for p in s.q("SELECT id, known_marks FROM people")}
    assert marks[b] == ["подрядчик"] and marks[a] == []
