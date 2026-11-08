"""«Разбор» показывает имя из карточки (аудит ответственного 07.11: «26 из 26 карточек с пустым именем»).

Карточки «кто исполнитель» конвейер пишет с ключом `mention` («Кто из них: Сергей…»), а `razbor.conflict_out` читал
только `named` — в «Разборе» имя было пустым у всех таких карточек. `named`/`assignee`/`name` читаются после — старые
карточки в базе их помнят.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from meetflow.core.registry import CardQueue
from meetflow.web.app import create_app

H = {"X-Requested-With": "erp-webapp", "X-User-Role": "super_admin", "X-User-Name": "admin"}


def _клиент(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    uid = st.insert("accounts", login=None, full_name="Админ", role="super_admin", password_hash="", active=1,
                    confirmed=1)
    H["X-User-Id"] = str(uid)
    pid = st.insert("projects", name="П", theme="erp_rollout")
    mid = st.insert("meetings", project_id=pid, date="2026-11-06")
    return c, st, pid, mid


def _карточка(st, pid, mid, payload):
    return CardQueue(st).open(pid, "assign_person", "Кто из них: Сергей — подготовить отчёт", payload, mid)


def test_имя_из_mention_видно_в_разборе(tmp_path):
    c, st, pid, mid = _клиент(tmp_path)
    _карточка(st, pid, mid, {"task_id": None, "description": "Подготовить отчёт", "quote": "[00:02:00] Сергей…",
                             "mention": "Сергей", "reason": "ambiguous", "marks": [], "candidates": []})
    # подробности карточки «Разбор» берёт из `/task-conflicts` (та же `conflict_out`, что и в списке)
    строки = c.get("/task-conflicts?status=open", headers=H).json()
    карточки = [x for x in строки if x["source"] == "unconfirmed_person"]
    assert карточки and карточки[0]["current_value"] == "Сергей", карточки


def test_старые_карточки_читаются_по_прежним_ключам(tmp_path):
    c, st, pid, mid = _клиент(tmp_path)
    _карточка(st, pid, mid, {"task_id": None, "description": "x", "quote": "q", "named": "Петрова",
                             "reason": "ambiguous", "marks": [], "candidates": []})
    строки = c.get("/task-conflicts?status=open", headers=H).json()
    карточки = [x for x in строки if x["source"] == "unconfirmed_person"]
    assert карточки and карточки[0]["current_value"] == "Петрова"
