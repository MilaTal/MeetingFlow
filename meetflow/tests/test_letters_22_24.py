"""Письма 22–24 ветки meeting-registry (03.10.26). Тесты написаны до правки.

22: решение владельца — «другой отдел в той же фразе» задачу НЕ задерживает: задача на человека по
    ключу, рядом карточка «отдел не совпадает» («главное — чтобы задача не потерялась»). Чужая
    организация по-прежнему — «тот же или новый».
23.1: неполная запись связывается с полным упоминанием: запись «Пересыпкин», упоминание
    «Пересыпкин Сергей» — кандидат, а не «никого»; при заведении внешний «Иван Петров» из ТМК при
    «Иван» из ТМК — вопрос «тот же или новый?», а не второй человек молча.
24: внешний из другой организации не отказывается как дубль и по пути «совпал ключ»."""
import json

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.people import Team
from meetflow.core.types import Person
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


# ------------------------------------------------------------------ 22: другой отдел
def test_other_department_assigns_with_mark():
    t = Team([Person("Игнатов Иван", department="склад", id=7), Person("Петрова Анна", department="бухгалтерия", id=8)])
    m = t.find("Игнатов", context="Гаврилов: Игнатов из бухгалтерии, подготовьте акт.")
    assert m.person is not None and m.person.id == 7 and any("бухгалтер" in x for x in m.dept_marks)


def test_foreign_org_still_holds():
    t = Team([Person("Игнатов Иван", id=7)])
    assert t.find("Игнатов", context="Подрядчик Игнатов из ТМК, пришлите график.").via == "same_or_new"


class Say(MockLLM):
    def _extract(self, data):
        return {"tasks": [{"description": "Подготовить акт сверки", "assignee": "Игнатов",
                           "quote": "Гаврилов Павел: Игнатов из бухгалтерии, подготовьте акт сверки"}]}


def test_pipeline_task_created_and_dept_card(store, project, make_pipe):
    store.insert("people", project_id=project, full_name="Петрова Анна", department="бухгалтерия")
    store.q("UPDATE people SET department='склад' WHERE full_name='Игнатов Иван'")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Say())
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Гаврилов Павел: Игнатов из бухгалтерии, подготовьте акт сверки\n".encode())
    rep = p.run(project, mid)
    assert rep.tasks_added == 1                                       # задача не потерялась
    card = store.q("SELECT * FROM cards WHERE kind='department_mismatch'")
    assert card and json.loads(card[0]["payload"])["assignee"] == "Игнатов Иван"


# ------------------------------------------------------------------ 23.1: неполная запись
def test_short_record_is_candidate_for_full_mention():
    t = Team([Person("Пересыпкин", id=1), Person("Гаврилов Павел", id=2)])
    m = t.find("Пересыпкин Сергей")
    assert m.person is None and [p.id for p in m.candidates] == [1]


@pytest.fixture
def c(tmp_path):
    cl = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                    raise_server_exceptions=False)
    cl.pid = cl.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    cl.url = f"/api/projects/{cl.pid}/people"
    return cl


def test_external_longer_name_same_org_asks(c):
    ext = {"full_name": "Иван", "external": True, "organization": "ТМК", "role": "инженер"}
    assert c.post(c.url, json=ext, headers=H).status_code == 200
    r = c.post(c.url, json={**ext, "full_name": "Иван Петров"}, headers=H)
    assert r.status_code == 409 and "Иван" in r.json()["detail"]
    assert c.post(c.url, json={**ext, "full_name": "Иван Петров", "confirm_new": True}, headers=H).status_code == 200


# ------------------------------------------------------------------ 24: другая организация
def test_external_other_org_not_duplicate_by_key(c):
    ext = {"full_name": "Иван", "external": True, "organization": "ТМК", "role": "инженер"}
    c.post(c.url, json=ext, headers=H)
    assert c.post(c.url, json={**ext, "organization": "Газпром"}, headers=H).status_code == 200
    # другая организация и по пути «совпал ключ» — не дубль (у Газпрома «Иван» теперь уже есть, поэтому — третья)
    assert c.post(c.url, json={**ext, "full_name": "Иван Петров", "organization": "Росатом"}, headers=H).status_code == 200
