"""Документ 14 «Решение — задача не теряется и новый человек в Команде» (владелец 03.10.26, для всех
веток; письмо 34 оркестратора). Тесты написаны до правки.

1. Карточка выбора исполнителя не закрывается сама (чистка по сроку её не снимает).
3. Новый человек, названный фамилией и именем: похож на кого-то (та же фамилия) — карточка «тот же или
   новый», без записи; похожих нет — сразу запись «не подтверждён», задача на него, карточка на
   подтверждение. Повторное упоминание — та же запись, второй не заводится. Внешнему (названа организация)
   — организация и роль обязательны: без роли не заводится, задача без исполнителя плюс карточка.
4. Одно слово, человека нет — в «Команду» не заводится, задача без исполнителя плюс карточка.
5. «Отдел без руководителя» — как было (задача задерживается карточкой)."""
import json

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


class Say(MockLLM):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def _extract(self, data):
        return {"tasks": self.items}


@pytest.fixture
def env(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    for n in ("Гаврилов Павел", "Петрова Анастасия"):
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n}, headers=H)
    c.store, c.pipe = app.state.store, app.state.pipe
    return c


def run(c, line, who, desc="Подготовить график монтажа", d="2026-10-01"):
    c.pipe.gen = Say([{"description": desc, "assignee": who, "quote": line}])
    mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": d}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H,
           files={"file": (f"t {d[8:]}.{d[5:7]}.{d[:4]}.txt", f"[00:01:00] {line}\n".encode())})
    return c.post(f"/api/meetings/{mid}/run", headers=H).json()


def people(c):
    return c.store.q("SELECT full_name, confirmed, external, organization FROM people WHERE project_id=?", (c.pid,))


def cards(c, kind):
    return [x for x in c.get(f"/api/projects/{c.pid}/cards", headers=H).json() if x["kind"] == kind]


def tasks(c):
    return c.get(f"/api/projects/{c.pid}/tasks", headers=H).json()


# 3 — новый человек, фамилия и имя, похожих нет
def test_new_full_name_registered_unconfirmed_and_assigned(env):
    line = "Гаврилов Павел: Сидоров Олег, подготовьте график монтажа"
    r = run(env, line, "Сидоров Олег")
    assert r["tasks_added"] == 1 and tasks(env)[0]["assignee"] == "Сидоров Олег"
    assert ("Сидоров Олег", 0, 0, "") in [tuple(p.values()) for p in people(env)]          # «не подтверждён»
    card = cards(env, "confirm_person")[0]
    assert card["payload"]["full_name"] == "Сидоров Олег"
    env.post(f"/api/cards/{card['id']}/resolve", json={"status": "accepted"}, headers=H)
    assert ("Сидоров Олег", 1, 0, "") in [tuple(p.values()) for p in people(env)]          # подтверждён
    # повторное упоминание — та же запись, второй не заводится
    run(env, line, "Сидоров Олег", desc="Прислать акт монтажа", d="2026-10-08")
    assert sum(1 for p in people(env) if p["full_name"] == "Сидоров Олег") == 1
    assert [t["assignee"] for t in tasks(env)] == ["Сидоров Олег", "Сидоров Олег"]


def test_unconfirmed_person_reused_before_confirmation(env):
    line = "Гаврилов Павел: Сидоров Олег, подготовьте график монтажа"
    run(env, line, "Сидоров Олег")
    run(env, line, "Сидорову Олегу", desc="Прислать акт монтажа", d="2026-10-08")
    assert sum(1 for p in people(env) if p["full_name"].startswith("Сидоров")) == 1
    assert len(cards(env, "confirm_person")) == 1                                    # одна карточка на человека


# 3 — похож на кого-то: карточка «тот же или новый», без записи
def test_similar_surname_is_same_or_new_without_record(env):
    line = "Гаврилов Павел: Петрова Ольга, подготовьте график монтажа"
    r = run(env, line, "Петрова Ольга")
    assert r["tasks_added"] == 1 and tasks(env)[0]["assignee"] is None
    assert not any(p["full_name"] == "Петрова Ольга" for p in people(env))
    assert cards(env, "assign_person")


# 3 — внешний: организация названа, роли нет — не заводится
def test_external_without_role_not_registered(env):
    line = "Гаврилов Павел: Сидоров Олег из ТМК, пришлите график монтажа"
    run(env, line, "Сидоров Олег из ТМК")
    assert not any(p["full_name"].startswith("Сидоров") for p in people(env))
    assert tasks(env)[0]["assignee"] is None and cards(env, "assign_person")


# 4 — одно слово
def test_one_word_unknown_task_without_assignee_and_card(env):
    line = "Гаврилов Павел: Кутузов, подготовьте график монтажа"
    r = run(env, line, "Кутузов")
    assert r["tasks_added"] == 1 and tasks(env)[0]["assignee"] is None
    assert not any(p["full_name"] == "Кутузов" for p in people(env))
    assert cards(env, "assign_person")


# 5 — отдел без руководителя: перевёрнут решением владельца (письмо 36) — задача сразу, исполнитель — отдел
def test_department_without_head_task_first(env):
    line = "Гаврилов Павел: ОТН, проверьте пломбы на цистернах"
    r = run(env, line, "ОТН", desc="Проверить пломбы на цистернах")
    assert r["tasks_added"] == 1 and tasks(env)[0]["assignee"] == "ОТН"
    card = cards(env, "assign_person")[0]
    assert card["payload"]["reason"] == "department" and not cards(env, "held_task")


# 1 — карточка выбора исполнителя не снимается по сроку
def test_assign_card_survives_cleanup(env):
    line = "Гаврилов Павел: Кутузов, подготовьте график монтажа"
    run(env, line, "Кутузов")
    env.store._conn.execute("UPDATE cards SET created_at='2026-01-01T00:00:00'")
    env.pipe.cards.cleanup(env.pid, 3)
    assert cards(env, "assign_person")


# найдено прогоном ERP (этап 6): «— Чистякова М., Мелехова А.» склеилось в нового человека «Чистякова Мелехова»
@pytest.mark.parametrize("mention", ["Чистякова М., Мелехова А.", "Чистякова Мелехова", "Чистякова и Мелехова",
                                     "Петрова Сидорова"])
def test_two_people_or_known_surnames_never_new_person(env, mention):
    env.post(f"/api/projects/{env.pid}/people", json={"full_name": "Чистякова Марина"}, headers=H)
    env.post(f"/api/projects/{env.pid}/people", json={"full_name": "Мелехова Анастасия"}, headers=H)
    line = f"Гаврилов Павел: {mention}, подготовьте график монтажа"
    r = run(env, line, mention)
    assert r["tasks_added"] == 1
    assert not any(p["confirmed"] == 0 for p in people(env))           # никого «не подтверждён»
    assert tasks(env)[0]["assignee"] is None and cards(env, "assign_person")


# письмо 45 (находки ERP 59d0629)
def test_one_new_person_two_tasks_one_record_one_card(env):
    env.pipe.gen = Say([
        {"description": "Подготовить график монтажа", "assignee": "Сидорова Ольга",
         "quote": "Гаврилов Павел: Сидорова Ольга, подготовьте график монтажа"},
        {"description": "Прислать акт приёмки", "assignee": "Сидоровой Ольге",
         "quote": "Гаврилов Павел: Сидоровой Ольге прислать акт приёмки"}])
    mid = env.post(f"/api/projects/{env.pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    env.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", (
        "[00:01:00] Гаврилов Павел: Сидорова Ольга, подготовьте график монтажа\n"
        "[00:02:00] Гаврилов Павел: Сидоровой Ольге прислать акт приёмки\n").encode())})
    env.post(f"/api/meetings/{mid}/run", headers=H)
    assert sum(1 for p in people(env) if p["full_name"].startswith("Сидоров")) == 1      # одна запись
    assert len(cards(env, "confirm_person")) == 1                                    # одна карточка
    card = cards(env, "confirm_person")[0]
    env.post(f"/api/cards/{card['id']}/resolve", json={"status": "accepted"}, headers=H)
    assert {t["assignee"] for t in tasks(env)} == {"Сидорова Ольга"}                 # обе задачи на нём
    assert not cards(env, "confirm_person")


def test_not_a_person_refused_when_record_has_other_tasks(env):
    line = "Гаврилов Павел: Сидоров Олег, подготовьте график монтажа"
    run(env, line, "Сидоров Олег")
    run(env, line, "Сидоров Олег", desc="Прислать акт монтажа", d="2026-10-08")
    card = cards(env, "confirm_person")[0]
    r = env.post(f"/api/cards/{card['id']}/resolve", json={"status": "rejected"}, headers=H)
    assert r.status_code == 409                                                        # у записи другие задачи
    assert any(p["full_name"] == "Сидоров Олег" for p in people(env))


def test_not_a_person_single_task_removes_record(env):
    line = "Гаврилов Павел: Сидоров Олег, подготовьте график монтажа"
    run(env, line, "Сидоров Олег")
    card = cards(env, "confirm_person")[0]
    assert env.post(f"/api/cards/{card['id']}/resolve", json={"status": "rejected"}, headers=H).status_code == 200
    assert not any(p["full_name"] == "Сидоров Олег" for p in people(env)) and tasks(env)[0]["assignee"] is None
