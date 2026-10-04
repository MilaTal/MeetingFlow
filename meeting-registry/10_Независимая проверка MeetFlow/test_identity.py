"""Правило «один человек или два» (решение владельца 03.10.26, документ «11_Решение — один человек или два»).
Кейсы записаны до кода. Ожидается поведение после реализации в MeetFlow.

Прибор: на коде 715f6cd кейсы 02, 04, 06 проходят впустую — сейчас любое неполное имя уходит карточкой.
Настоящей проверкой они станут после базового правила «рабочий ключ — назначить» (кейс 01): если не сделать
проверку несовпадения, кейс 04 упадёт. Поэтому их нельзя считать закрытыми, пока не прошёл кейс 01."""

import pytest

from conftest import Env, Scripted, assert_task_first


def extract(assignee, desc, line=0):
    def g(pu, sy, us):
        if pu == "extract_tasks":
            return {"tasks": [{"description": desc, "assignee": assignee, "line": line}]}
    return Scripted(g)


TEAM = ["Гаврилов Павел", "Назаров Константин", "Ершова Светлана", "Игнатов Иван"]


def env_with(team, gen, extra=None):
    e = Env(gen=gen, team=team)
    for p in extra or []:
        e.s.insert("people", project_id=e.pid, **p)
    return e


def test_id_01_unique_surname_assigns():
    e = env_with(TEAM, extract("Назаров", "подготовьте спецификацию на фильтры"))
    e.src("[00:00:10] Гаврилов Павел: Назаров, подготовьте спецификацию на фильтры.\n")
    e.run()
    t = e.tasks("active")
    assert len(t) == 1 and "Назаров" in t[0]["assignee"]


def test_id_02_second_namesake_switches_to_name_rule():
    e = env_with(TEAM + ["Назаров Андрей"], extract("Назаров", "подготовьте спецификацию на фильтры"))
    e.src("[00:00:10] Гаврилов Павел: Назаров, подготовьте спецификацию на фильтры.\n")
    e.run()
    # Перевёрнут 03.10.26 по документу 14 (решение владельца «задача не теряется»): задача сразу без исполнителя плюс карточка. Было: задачи нет, только карточка.
    assert_task_first(e, min_candidates=2)


def test_id_03_with_first_name_assigns_among_namesakes():
    e = env_with(TEAM + ["Назаров Андрей"], extract("Назаров Константин", "подготовьте спецификацию на фильтры"))
    e.src("[00:00:10] Гаврилов Павел: Константин Назаров, подготовьте спецификацию на фильтры.\n")
    e.run()
    t = e.tasks("active")
    assert len(t) == 1 and t[0]["assignee"].startswith("Назаров Константин")


def test_id_04_foreign_org_near_unique_surname_asks_same_or_new():
    """«подрядчик Игнатов» при нашем Игнатове без такой организации — задача без исполнителя плюс карточка «тот же или новый»."""
    e = env_with(TEAM, extract("Игнатов", "пришлите график монтажа"))
    e.src("[00:00:10] Гаврилов Павел: Подрядчик Игнатов из ТМК, пришлите график монтажа.\n")
    e.run()
    # Перевёрнут 03.10.26 по документу 14 (решение владельца «задача не теряется»): задача сразу без исполнителя плюс карточка. Было: задачи нет, только карточка.
    assert_task_first(e)


def test_id_05_external_same_name_split_by_org():
    """Внешние без фамилии: «Иван» из ТМК и «Иван» из Газпрома — разные люди по организации."""
    extra = [{"full_name": "Иван", "external": 1, "role": "инженер", "organization": "ТМК"},
             {"full_name": "Иван", "external": 1, "role": "куратор", "organization": "Газпром"}]
    e = env_with(["Гаврилов Павел"], extract("Иван из ТМК", "пришлите акт испытаний"), extra)
    e.src("[00:00:10] Гаврилов Павел: Иван из ТМК, пришлите акт испытаний.\n")
    e.run()
    t = e.tasks("active")
    assert len(t) == 1 and "ТМК" in (t[0]["assignee"] + str(t[0].get("assignee_org", "")))


def test_id_06_external_same_name_no_org_goes_to_card():
    extra = [{"full_name": "Иван", "external": 1, "role": "инженер", "organization": "ТМК"},
             {"full_name": "Иван", "external": 1, "role": "куратор", "organization": "Газпром"}]
    e = env_with(["Гаврилов Павел"], extract("Иван", "пришлите акт испытаний"), extra)
    e.src("[00:00:10] Гаврилов Павел: Иван, пришлите акт испытаний.\n")
    e.run()
    # Перевёрнут 03.10.26 по документу 14 (решение владельца «задача не теряется»): задача сразу без исполнителя плюс карточка. Было: задачи нет, только карточка.
    assert_task_first(e, min_candidates=2)


def test_id_erp_alexey_is_not_same_stem_surname():
    """Кейс ERP (test_identity_0310.py::test_id_alexey_is_not_same_stem_surname): сверка по началу слова при молчаливом
    назначении недопустима — «Алексей» не «Алексейко»."""
    from meetflow.core.people import Team
    from meetflow.core.types import Person
    t = Team([Person("Алексейко Вероника", id=1), Person("Гаврилов Павел", id=2)])
    m = t.find("Алексей")
    assert m.person is None or m.person.id != 1


def test_id_erp_new_external_needs_org_and_role(tmp_path):
    """Кейс ERP: внешнему при заведении обязательны организация и роль, ФИО — нет."""
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient
    import meetflow.web.app as app
    c = TestClient(app.create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                   raise_server_exceptions=False)
    h = {"X-User-Role": "super_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=h).json()["id"]
    url = f"/api/projects/{pid}/people"
    assert c.post(url, json={"full_name": "Иван", "external": True}, headers=h).status_code == 422
    assert c.post(url, json={"full_name": "Иван", "external": True, "organization": "ТМК", "role": "инженер"},
                  headers=h).status_code in (200, 201)


def test_id_07_old_tasks_unchanged_when_key_becomes_shared():
    e = env_with(TEAM, Scripted())
    e.prior([("подготовить спецификацию на фильтры", "Назаров Константин")])
    before = [(t["id"], t["assignee"]) for t in e.tasks()]
    assert before, "прибор: задачи нет — проверка была бы пустой"
    e.s.insert("people", project_id=e.pid, full_name="Назаров Андрей")
    m2 = e.meeting("2026-10-02")
    e.src("[00:00:10] Гаврилов Павел: Спасибо, дальше.\n", m2)
    e.run(m2)
    assert [(t["id"], t["assignee"]) for t in e.tasks()][:len(before)] == before
