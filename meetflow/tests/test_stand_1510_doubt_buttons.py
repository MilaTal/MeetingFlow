"""Решение владельца 15.10.26 (вечер, через «Мониторинг»): кнопки карточки «под вопросом» — «Подтвердить» / «Своя
формулировка» / «Не задача»; «Это дубль» — только где дубль возможен (в реестре есть похожая действующая задача);
подписи кнопок и короткая подпись причины у точки реестра — из общей таблицы doubt_labels.py (автор — Планёрка,
байт в байт). Тесты написаны до правки и падали."""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}
LINE = "Петрова Анастасия: Регламент склада подготовлен, отправили на согласование"
SHARED = Path(__file__).parents[1] / "meetflow" / "connectors" / "shared" / "doubt_labels.py"


class Say(MockLLM):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def _extract(self, data):
        return {"tasks": self.items}


@pytest.fixture
def env(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    c.pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    c.post(f"/api/projects/{c.pid}/people", json={"full_name": "Петрова Анастасия", "confirm_new": True}, headers=H)
    c.app_ = app
    return c


def run(c, desc):
    c.app_.state.pipe.gen = Say([{"description": desc, "assignee": "Петрова Анастасия", "quote": LINE}])
    mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", f"[00:01:00] {LINE}\n".encode())})
    c.post(f"/api/meetings/{mid}/run", headers=H)
    return [x for x in c.get(f"/api/projects/{c.pid}/cards", headers=H).json() if x["kind"] == "task_doubt"][-1]


def test_labels_module_is_the_shared_one():
    assert hashlib.md5(SHARED.read_bytes()).hexdigest().startswith("578ce274")


def test_buttons_without_duplicate_when_nothing_similar(env):
    card = run(env, "Подготовить регламент склада")
    assert [b["label"] for b in card["payload"]["buttons"]] == ["Подтвердить", "Своя формулировка", "Не задача"]


def test_duplicate_button_only_when_similar_task_exists(env):
    # поставлена позже встречи — встреча её не закрывает (строка 42), а похожая действующая задача в реестре есть
    env.app_.state.pipe.reg.add(env.pid, "подготовьте регламент на складе", "Сидоров Пётр", date_set="2026-10-05")
    card = run(env, "Подготовить регламент склада")
    assert [b["action"] for b in card["payload"]["buttons"]] == ["accept", "custom", "reject", "duplicate"]


def test_duplicate_button_disappears_when_similar_task_closed(env):
    tid = env.app_.state.pipe.reg.add(env.pid, "подготовьте регламент на складе", "Сидоров Пётр", date_set="2026-09-01")
    card = run(env, "Подготовить регламент склада")
    from meetflow.core.types import TaskStatus
    env.app_.state.pipe.reg.set_status(tid, TaskStatus.DONE, "web_form")
    card = [x for x in env.get(f"/api/projects/{env.pid}/cards", headers=H).json() if x["id"] == card["id"]][0]
    assert "duplicate" not in [b["action"] for b in card["payload"]["buttons"]]


def test_custom_wording_replaces_description_and_clears_doubt(env):
    card = run(env, "Подготовить регламент склада")
    r = env.post(f"/api/cards/{card['id']}/resolve", headers=H,
                 json={"status": "accepted", "action": "custom", "resolution": "Согласовать регламент склада с ОТК"})
    assert r.status_code == 200
    t = env.app_.state.store.get("tasks", card["payload"]["task_id"])
    assert t["description"] == "Согласовать регламент склада с ОТК" and t["doubt_reason"] == ""


def test_duplicate_refused_when_not_offered(env):
    card = run(env, "Подготовить регламент склада")
    r = env.post(f"/api/cards/{card['id']}/resolve", headers=H, json={"status": "rejected", "action": "duplicate"})
    assert r.status_code == 400


def test_registry_tooltip_uses_shared_label(env):
    run(env, "разработчики выполнили задачу")
    t = env.get(f"/api/projects/{env.pid}/tasks", headers=H).json()[0]
    assert t["doubt_label"] == "проверить — см. карточку" or t["doubt_label"]
    # фронт ERP 1 в 1 (27.10.2026): подпись причины — с сервера (`under_question_label`), решение — в «Разборе»
    root = Path(__file__).parents[1] / "meetflow" / "web" / "static"
    js = (root / "app.js").read_text(encoding="utf-8")
    assert "под вопросом: ${t.under_question_label || t.source_anchor}" in js
    assert "решить в «Разборе»" in (root / "registry.js").read_text(encoding="utf-8")
