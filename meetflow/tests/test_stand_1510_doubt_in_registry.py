"""Находка стенда, строка 44 — решение владельца 15.10.26 (заменяет пункт документа 14 и в MeetFlow, ответ
«Мониторинга» 15.10): сомнительная задача — сразу в реестр, в протоколе как обычная, без пометки; неброская
отметка только для оператора и карточка обязательна. Вне реестра — только дубли и уже отклонённое оператором
(и внедрённая инструкция: текст реестра идёт в подсказки модели на следующих встречах). Причину сервер отдаёт
только администраторам при включённой настройке. Автоочистка такие карточки не снимает. Уверенная близняшка
вытесняет сомнительную. Тесты написаны до правки и падали (задача сидела в карточке вне реестра)."""
import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}
M = {"X-User-Role": "member"}
# пример сомнения — отчёт о сделанном: вопрос и отрицание с вечера 15.10.26 отсеиваются ДО «под вопросом»
LINE = "Петрова Анастасия: Регламент склада подготовлен, отправили на согласование"


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
    for n in ("Гаврилов Павел", "Петрова Анастасия", "Игнатов Иван"):
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n, "confirm_new": True}, headers=H)
    c.store, c.pipe = app.state.store, app.state.pipe
    return c


def run(c, lines, items, d="2026-10-01"):
    c.pipe.gen = Say(items)
    c.mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": d}, headers=H).json()["id"]
    text = "".join(f"[00:0{i}:00] {ln}\n" for i, ln in enumerate(lines, 1))
    c.post(f"/api/meetings/{c.mid}/sources", headers=H, files={"file": (f"t {d[8:]}.{d[5:7]}.{d[:4]}.txt", text.encode())})
    return c.post(f"/api/meetings/{c.mid}/run", headers=H).json()


def tasks(c, h=H, status="active"):
    return c.get(f"/api/projects/{c.pid}/tasks?status={status}", headers=h).json()


def cards(c, kind):
    return [x for x in c.get(f"/api/projects/{c.pid}/cards", headers=H).json() if x["kind"] == kind]


QUESTION = [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия", "quote": LINE}]


def test_doubtful_task_goes_to_registry_and_protocol_with_card(env):
    run(env, [LINE], QUESTION)
    t = tasks(env)
    assert len(t) == 1 and t[0]["description"] == "Подготовить регламент склада"
    assert "отчёт" in t[0]["doubt_reason"]
    card = cards(env, "task_doubt")
    assert len(card) == 1 and card[0]["payload"]["task_id"] == t[0]["id"]
    assert not cards(env, "held_task")
    proto = env.store.get("meetings", env.mid)["protocol_md"]
    assert "Подготовить регламент склада" in proto and "под вопросом" not in proto.lower()


def test_reason_hidden_from_member_and_when_switched_off(env):
    run(env, [LINE], QUESTION)
    assert tasks(env, M)[0]["doubt_reason"] in ("", None)
    tid = tasks(env)[0]["id"]
    r = env.patch(f"/api/tasks/{tid}", json={"status": "done"},
                  headers={"X-User-Role": "member", "X-User-Name": quote("Петрова Анастасия")})
    assert r.status_code == 200 and r.json().get("doubt_reason") in ("", None)    # и в ответе на правку
    env.post("/api/settings/thresholds", json={"show_doubt_mark": False}, headers={"X-User-Role": "super_admin"})
    assert tasks(env, status="all")[0]["doubt_reason"] in ("", None)


def test_card_actions(env):
    run(env, [LINE], QUESTION)
    c = cards(env, "task_doubt")[0]
    env.post(f"/api/cards/{c['id']}/resolve", json={"status": "accepted"}, headers=H)
    assert tasks(env)[0]["doubt_reason"] in ("", None) and tasks(env)[0]["status"] == "active"
    run(env, [LINE], [{**QUESTION[0], "description": "Подготовить график инвентаризации"}], d="2026-10-02")
    c2 = cards(env, "task_doubt")[0]
    env.post(f"/api/cards/{c2['id']}/resolve", json={"status": "rejected"}, headers=H)   # «Не задача» — снята
    # перевёрнут 27.10.2026 (ERP 26.10.2026: снятые не показываются нигде, API их не отдаёт): проверка — по базе
    dropped = [t for t in env.store.q("SELECT * FROM tasks WHERE status='dropped'") if "инвентаризации" in t["description"]]
    assert dropped, "«Не задача» снимает задачу, а не удаляет"
    assert not [t for t in tasks(env, status="dropped") if "инвентаризации" in t["description"]]


def test_duplicates_stay_out_of_registry(env):
    env.pipe.reg.add(env.pid, "Подготовить регламент склада", "Петрова Анастасия", date_set="2026-09-01")
    line = "Гаврилов Павел: Петрова Анастасия, подготовьте регламент склада"
    run(env, [line], [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия", "quote": line}])
    assert len(tasks(env)) == 1 and cards(env, "held_task") and not cards(env, "task_doubt")


def test_confident_twin_displaces_doubtful(env):
    sure = "Гаврилов Павел: Петрова Анастасия, подготовьте регламент склада до пятницы"
    run(env, [LINE, sure], [QUESTION[0], {"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                                          "quote": sure}])
    t = tasks(env)
    assert len(t) == 1 and t[0]["doubt_reason"] in ("", None) and not cards(env, "task_doubt")


def test_cleanup_does_not_close_doubt_card(env):
    run(env, [LINE], QUESTION)
    env.store.q("UPDATE cards SET created_at='2026-01-01T00:00:00' WHERE kind='task_doubt'")
    env.pipe.cards.cleanup(env.pid, 1)
    assert cards(env, "task_doubt")


def test_monitoring_counter_first_line(env):
    run(env, [LINE], QUESTION)
    q = env.get("/api/monitoring/live", headers={"X-User-Role": "super_admin"}).json()
    assert q["queue"]["tasks_doubt_open"] == 1


def test_ui_dot_and_card_buttons():
    """Точка без текста с подсказкой «под вопросом: причина — карточка в «Конфликтах»», три действия карточки,
    выключатель в «Порогах», счётчик первой строкой «Очереди» мониторинга."""
    from pathlib import Path
    js = (Path(__file__).parents[1] / "meetflow" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'class="doubt-dot" title="под вопросом: ${esc(t.doubt_label || t.doubt_reason)} — карточка в «Конфликтах»"' in js
    body = js[js.index('if (c.kind === "task_doubt")'):]
    body = body[:body.index("// задача уже заведена без исполнителя")]
    # перевёрнут 15.10.26, вечер (решение владельца): кнопки — из общей таблицы doubt_labels в карточке
    # («Подтвердить» / «Своя формулировка» / «Не задача», «Это дубль» — только где дубль возможен)
    assert "p.buttons" in body and "data-doubt-act" in body and "Своя формулировка" in body
    assert 'id="th-doubt"' in js and "show_doubt_mark: $(\"#th-doubt\").checked" in js
    q = js[js.index('<h2 style="margin-top:0">Очередь</h2>'):]
    assert q.index("Задачи под вопросом") < q.index("Карточки «Конфликтов»")
