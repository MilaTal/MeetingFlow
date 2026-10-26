"""Этап 2 плана сведения: решения письма 02, подтверждённые владельцем
напрямую 03.10.26.

1. Снятие задачи по голосу «как для единиц»: только явные слова снятия;
   «не отменили», «отменять не будем», вопрос, условие — не снятие; ранняя и
   своя встреча не снимают; массовое — карточкой; «Вернуть» — одна кнопка.
2. Спорное имя — без подстановки (владелец отклонил «назначить того, кто
   говорил»): всегда карточка, кандидаты отсортированы подсказками из текста
   и реестра, задача заводится после выбора, ответ правилом не становится.
Попутно: карточки по «Подтвердить» ничего не делали — задача не заводилась,
закрытие не применялось."""
import json

import pytest
from fastapi.testclient import TestClient

from meetflow.core.negation import NegationRule
from meetflow.web.app import create_app


# ------------------------------------------------------------------ снятие по голосу
@pytest.mark.parametrize("phrase,removal", [
    ("Задачу по регламенту склада снимаем, больше не нужна.", True),
    ("Регламент склада отменили.", True),
    ("От регламента склада отказались.", True),
    ("Регламент склада больше не актуален.", True),
    ("Регламент склада не отменили.", False),
    ("Отменять регламент склада не будем.", False),
    ("Может, снимем регламент склада?", False),
    ("Если не успеем, регламент склада снимем.", False),
    ("Регламент склада готов, сделано.", False),
])
def test_states_removal(phrase, removal):
    assert NegationRule().states_removal(phrase) is removal


def _voice(store, project, make_pipe, lines, mdate="2026-10-01", n_tasks=1):
    p = make_pipe()
    tasks = ["Подготовить регламент склада", "Отправить выгрузку остатков", "Согласовать график поставок",
             "Проверить отчёт браку продукции"][:n_tasks]
    ids = [p.reg.add(project, t, "Игнатов Иван", date_set="2026-09-01") for t in tasks]
    mid = store.insert("meetings", project_id=project, date=mdate, label="встреча")
    text = "\n".join(f"[00:0{i}:00] Игнатов Иван: {ln}" for i, ln in enumerate(lines, 1))
    p.ingest(project, mid, f"t {mdate[8:]}.{mdate[5:7]}.{mdate[:4]}.txt", text.encode())
    return p, mid, ids, p.run(project, mid)


def test_task_removed_by_voice(store, project, make_pipe):
    p, mid, ids, rep = _voice(store, project, make_pipe, ["Задачу по регламенту склада снимаем, больше не нужна."])
    t = store.get("tasks", ids[0])
    assert t["status"] == "dropped" and rep.tasks_dropped == 1
    # перевёрнут 27.10.2026 (ERP 26.10.2026: снятые задачи не показываются нигде, раздела «Снято по встрече» нет)
    md = store.get("meetings", mid)["protocol_md"]
    assert "Снято" not in md and "регламент" not in md.lower()
    hist = store.q("SELECT * FROM task_history WHERE task_id=? ORDER BY id DESC", (ids[0],))[0]
    assert "снимаем" in hist["evidence_quote"] and hist["new_status"] == "dropped"


@pytest.mark.parametrize("line", ["Регламент склада не отменили, работаем.", "Отменять регламент склада не будем."])
def test_not_removal_keeps_task(store, project, make_pipe, line):
    p, mid, ids, rep = _voice(store, project, make_pipe, [line])
    assert store.get("tasks", ids[0])["status"] == "active"


def test_mass_removal_is_one_card(store, project, make_pipe):
    lines = ["Регламент склада отменили.", "Выгрузку остатков отменили.", "График поставок отменили.",
             "Отчёт по браку продукции отменили."]
    p, mid, ids, rep = _voice(store, project, make_pipe, lines, n_tasks=4)
    assert all(store.get("tasks", i)["status"] == "active" for i in ids)
    card = store.q("SELECT * FROM cards WHERE kind='mass_closing'")[0]
    assert {c["status"] for c in json.loads(card["payload"])["closings"]} == {"dropped"}


# ------------------------------------------------------------------ карточки делают дело
TEAM = ["Игнатов Иван", "Петрова Анастасия", "Петрова Мария", "Сидоров Пётр"]
MEET = ("[00:00:10] Игнатов Иван: Петрова Анастасия, доложите по складу.\n"
        "[00:01:00] Петрова Анастасия: По складу всё по плану.\n"
        "[00:02:00] Игнатов Иван: Петрова, подготовьте регламент приёмки на складе до 10.10\n")


@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.H = {"X-User-Role": "project_admin"}
    c.pid = c.post("/api/projects", json={"name": "П"}, headers=c.H).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n, "department": "склад" if n == "Петрова Мария" else "",
                                                         "confirm_new": True},   # тёзки заведены осознанно
               headers=c.H)
    c.store = app.state.store
    return c


def _run(c, text=MEET, d="2026-10-01"):
    mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": d}, headers=c.H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", files={"file": (f"t {d[8:]}.{d[5:7]}.{d[:4]}.txt", text.encode())}, headers=c.H)
    return mid, c.post(f"/api/meetings/{mid}/run", headers=c.H).json()


def _cards(c, kind):
    return [x for x in c.get(f"/api/projects/{c.pid}/cards", headers=c.H).json() if x["kind"] == kind]


def test_disputed_name_is_card_with_ranked_hints_never_substituted(client):
    c = client
    c.store.insert("tasks", project_id=c.pid, description="Подготовить регламент отгрузки на складе",
                   assignee="Петрова Мария", status="done", date_set="2026-09-01")
    # перевёрнут 03.10.26 по письму 30 оркестратора (решение владельца): задача сразу без исполнителя,
    # рядом карточка assign_person; выбор ставит исполнителя в ту же задачу
    mid, rep = _run(c)
    t = c.get(f"/api/projects/{c.pid}/tasks", headers=c.H).json()
    assert rep["tasks_added"] == 1 and [x["assignee"] for x in t if "приёмки" in x["description"]] == [None]  # подстановки нет
    card = _cards(c, "assign_person")[0]
    cands = card["payload"]["candidates"]
    assert {x["name"] for x in cands} == {"Петрова Анастасия", "Петрова Мария"}
    hints = {x["name"]: x["hints"] for x in cands}
    assert any("полностью" in h for h in hints["Петрова Анастасия"])
    assert any("похожие задачи" in h for h in hints["Петрова Мария"])
    assert any("отдел" in h for h in hints["Петрова Мария"])
    assert cands[0]["name"] == "Петрова Мария"                         # больше подсказок — выше


def test_disputed_name_choice_creates_task_without_rule(client):
    c = client
    # перевёрнут 03.10.26 по письму 30 оркестратора (решение владельца): задача сразу без исполнителя,
    # рядом карточка assign_person; выбор ставит исполнителя в ту же задачу
    mid, rep = _run(c)
    card = _cards(c, "assign_person")[0]
    url = f"/api/cards/{card['id']}/resolve"
    assert c.post(url, json={"status": "accepted"}, headers=c.H).status_code == 400          # выбор обязателен
    assert c.post(url, json={"status": "accepted", "choice": "Сидоров Пётр"}, headers=c.H).status_code == 400
    r = c.post(url, json={"status": "accepted", "choice": "Петрова Мария"}, headers=c.H)
    assert r.status_code == 200
    t = c.get(f"/api/projects/{c.pid}/tasks", headers=c.H).json()
    assert [x["assignee"] for x in t] == ["Петрова Мария"] and "регламент приёмки" in t[0]["description"]
    assert not c.store.q("SELECT * FROM operator_rules")                # ответ правилом не стал


def test_held_task_accept_creates_task(client):
    """Прежняя версия теста проходила впустую: заглушка модели строку не
    извлекала, и 0 == 0. Карточка задаётся явно."""
    c = client
    cid = c.store.insert("cards", project_id=c.pid, kind="held_task", title="Задача не заведена", status="open",
                         payload={"description": "Подписать договор", "assignee": "Петрова Анастасия",
                                  "reasons": ["report_not_assignment"], "quote": "Договор подписан, отправили."})
    assert c.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=c.H).status_code == 200
    t = c.get(f"/api/projects/{c.pid}/tasks", headers=c.H).json()
    assert [(x["description"], x["assignee"]) for x in t] == [("Подписать договор", "Петрова Анастасия")]
    c.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=c.H)          # повтор — без второй задачи
    assert len(c.get(f"/api/projects/{c.pid}/tasks", headers=c.H).json()) == 1


def test_closing_card_accept_closes_task(client):
    c = client
    tid = c.store.insert("tasks", project_id=c.pid, description="Подготовить регламент склада", assignee="Игнатов Иван",
                         status="active", date_set="2026-09-01")
    cid = c.store.insert("cards", project_id=c.pid, kind="closing_candidate", title="Возможно выполнено", status="open",
                         payload={"task_id": tid, "quote": "Регламент склада почти готов", "why": "x"})
    c.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=c.H)
    assert c.store.get("tasks", tid)["status"] == "done"


def test_mass_card_accept_applies_all(client):
    c = client
    ids = [c.store.insert("tasks", project_id=c.pid, description=f"Задача {i}", assignee="Игнатов Иван", status="active",
                          date_set="2026-09-01") for i in range(4)]
    cid = c.store.insert("cards", project_id=c.pid, kind="mass_closing", title="м", status="open",
                         payload={"closings": [{"task_id": i, "quote": "q", "status": s}
                                               for i, s in zip(ids, ["done", "done", "dropped", "done"])]})
    c.post(f"/api/cards/{cid}/resolve", json={"status": "accepted"}, headers=c.H)
    assert [c.store.get("tasks", i)["status"] for i in ids] == ["done", "done", "dropped", "done"]
