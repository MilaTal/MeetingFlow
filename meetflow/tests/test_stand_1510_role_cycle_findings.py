"""Находки циклов ролей ERP и Планёрки (через «Мониторинг» 15.10.26), проверка для MeetFlow.
3 — служебные поля протокола (замечания проверки, когда собран) отдавались без проверки роли: участнику — без них.
2 — причина «под вопросом» утекала участнику через поле статуса после «Не задача»: ни одно поле ответа не несёт её.
4 — задача из карточки «похожая задача» теряла срок: заведённая из карточки задача — со сроком.
Тест 3 написан до правки и падал; 2 и 4 — сторожа (у MeetFlow этого нет)."""
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from conftest import TRANSCRIPT
from meetflow.connectors.llm_mock import MockLLM
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}
M = {"X-User-Role": "member"}


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
    for n in ("Петрова Анастасия", "Игнатов Иван"):
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n, "confirm_new": True}, headers=H)
    c.app_ = app
    return c


def _meeting(c, text, gen=None):
    if gen:
        c.app_.state.pipe.gen = gen
    mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", text.encode())})
    c.post(f"/api/meetings/{mid}/run", headers=H)
    return mid


def test_protocol_service_fields_only_for_admins(env):
    mid = _meeting(env, TRANSCRIPT)
    env.app_.state.store.update("meetings", mid, review_notes=[{"issue": "служебное замечание проверки", "severity": "minor"}])
    admin = env.get(f"/api/meetings/{mid}/protocol", headers=H).json()
    member = env.get(f"/api/meetings/{mid}/protocol", headers=M).json()
    assert admin["review_notes"] and member["markdown"] == admin["markdown"]
    assert member["review_notes"] == [] and not member.get("built_at")
    assert "служебное замечание" not in env.get(f"/api/meetings/{mid}/protocol", headers=M).text


def test_doubt_reason_does_not_leak_after_not_a_task(env):
    line = "Петрова Анастасия: Регламент склада подготовлен, отправили на согласование"
    _meeting(env, f"[00:01:00] {line}\n", Say([{"description": "Подготовить регламент склада",
                                                 "assignee": "Петрова Анастасия", "quote": line}]))
    card = [x for x in env.get(f"/api/projects/{env.pid}/cards", headers=H).json() if x["kind"] == "task_doubt"][0]
    env.post(f"/api/cards/{card['id']}/resolve", json={"status": "rejected", "action": "reject"}, headers=H)
    reason = "отчёт о сделанном"
    who = {"X-User-Role": "member", "X-User-Name": quote("Петрова Анастасия")}
    for path in (f"/api/projects/{env.pid}/tasks?status=all", f"/api/projects/{env.pid}/tasks?status=dropped"):
        assert reason not in env.get(path, headers=who).text
    tid = card["payload"]["task_id"]
    r = env.patch(f"/api/tasks/{tid}", json={"status": "active"}, headers=who)
    assert reason not in r.text


def test_task_from_similar_card_keeps_due(env):
    env.app_.state.pipe.reg.add(env.pid, "подготовьте регламент склада", "Петрова Анастасия", date_set="2026-09-01")
    line = "Игнатов Иван: Петрова Анастасия, подготовьте регламент склада до 10.10"
    _meeting(env, f"[00:01:00] {line}\n", Say([{"description": "подготовьте регламент склада", "assignee": "Петрова Анастасия",
                                                 "quote": line, "due_date": "10.10.2026"}]))
    card = [x for x in env.get(f"/api/projects/{env.pid}/cards", headers=H).json()
            if x["kind"] == "held_task" and "duplicate" in (x["payload"].get("reasons") or [])][0]
    env.post(f"/api/cards/{card['id']}/resolve", json={"status": "accepted"}, headers=H)
    new = [t for t in env.get(f"/api/projects/{env.pid}/tasks", headers=H).json() if t["source_meeting_id"]]
    assert new and new[0]["due_date"], "задача из карточки «похожая задача» потеряла срок"
