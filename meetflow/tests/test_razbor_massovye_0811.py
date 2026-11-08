"""Массовые действия в «Разборе» и срок хранения 10 дней (правки ERP/Планёрки 03–06.11, п. 11).

«Выделить все / снять выделение», «Удалить выбранное» по группам «вид + встреча»; построчного удаления нет. Срок
хранения строк «Разбора» — 10 дней (было 7).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from meetflow.web.app import create_app

# ERP-адреса: заголовок запроса и номер учётной записи (как у остальных тестов «Разбора»)
H = {"X-Requested-With": "erp-webapp", "X-User-Role": "super_admin", "X-User-Name": "admin"}
СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


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


def test_срок_хранения_разбора_десять_дней(tmp_path):
    c, _st, _pid, _mid = _клиент(tmp_path)
    assert c.get("/razbor", headers=H).json()["days"] == 10


def test_удалить_выбранную_карточку(tmp_path):
    c, st, pid, mid = _клиент(tmp_path)
    cid = st.insert("cards", project_id=pid, meeting_id=mid, kind="held_task", title="Возможна потеря",
                    payload="{}", status="open")
    r = c.post("/razbor/batch", json={"source": "card", "ids": [cid], "action": "delete"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["done"] == 1 and not st.get("cards", cid)


def test_удалить_строку_под_вопросом_задача_остаётся(tmp_path):
    c, st, pid, mid = _клиент(tmp_path)
    tid = st.insert("tasks", project_id=pid, description="Согласовать график", status="active",
                    source_meeting_id=mid, doubt_reason="условие, а не поручение", date_set="2026-11-06")
    card = st.insert("cards", project_id=pid, meeting_id=mid, kind="task_doubt", title="Задача под вопросом",
                     payload=f'{{"task_id": {tid}}}', status="open")
    r = c.post("/razbor/batch", json={"source": "task", "ids": [tid], "action": "delete"}, headers=H)
    assert r.status_code == 200, r.text
    задача = st.get("tasks", tid)
    assert задача["status"] == "active" and not (задача["doubt_reason"] or ""), "задача в реестре, без пометки"
    assert not st.get("cards", card), "карточка сомнения убрана из «Разбора»"


def test_удалить_возможное_поручение(tmp_path):
    c, st, pid, mid = _клиент(tmp_path)
    pa = st.insert("possible_assignments", project_id=pid, meeting_id=mid, meeting_date="2026-11-06",
                   text="Проверить отчёт", quote="", reason="", state="новое", created_at="2026-11-06T10:00:00")
    r = c.post("/razbor/batch", json={"source": "possible", "ids": [pa], "action": "delete"}, headers=H)
    assert r.status_code == 200, r.text
    assert not st.get("possible_assignments", pa)


def test_решения_названы_в_ошибке(tmp_path):
    c, _st, _pid, _mid = _клиент(tmp_path)
    r = c.post("/razbor/batch", json={"source": "card", "ids": [1], "action": "что-то"}, headers=H)
    assert r.status_code == 400 and "Удалить выбранное" in r.json()["detail"]


def test_на_экране_есть_выделение_и_удаление():
    js = (СТАТИКА / "razbor.js").read_text(encoding="utf-8")
    for надпись in ("Выделить все", "Снять выделение", "Удалить выбранное"):
        assert надпись in js, надпись
    assert 'пакет("delete", "Удалить выбранное")' in js and "confirmDialog(" in js
    assert "rz-batch-del" in js and "rz-card-del" in js
