"""Меню «…» у встречи: переименовать, переместить и удалить — всем (слово владелицы 08.11.2026 «вернуть их»).

Найдено по её скриншоту: в реестре встреч меню не было вовсе. Причина — кнопка и меню были только для администратора,
а владелица работала участником (вход через портал). Решение: видят все вошедшие; на сервере переименование, перенос,
удаление и отмена удаления доступны любому вошедшему; удаление мягкое — «Отменить удаление» возвращает задачи и карточки.
Остальные пункты (дата, подпроект, кто вёл, свести) остаются администратору. Данные вымышленные.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

W = {"X-Requested-With": "erp-webapp"}


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    ids = {r: st.insert("accounts", full_name=f, role=r, active=1, confirmed=1)
           for f, r in (("Орлова Анна", "super_admin"), ("Сидорова Вера", "member"))}

    def h(role="member"):
        return {**W, "X-User-Id": str(ids[role])}
    c.h, c.st, c.pid = h, st, pid
    return c


def _встреча(c, label="") -> int:
    return c.post("/meetings", json={"date": "2026-11-06", "label": label},
                  headers={**c.h("super_admin"), "X-Project-Id": str(c.pid)}).json()["id"]


def test_участник_переименовывает_встречу(env):
    mid = _встреча(env)
    r = env.patch(f"/meetings/{mid}/label", json={"label": "  Работа   с тендерами "}, headers=env.h("member"))
    assert r.status_code == 200 and r.json()["label"] == "Работа с тендерами"


def test_участник_переносит_встречу_в_проект(env):
    mid = _встреча(env)
    другой = env.st.insert("projects", name="Цех", theme="erp_rollout", archived=0)
    r = env.post(f"/meetings/{mid}/move-project", json={"project_id": другой, "rebuild": False}, headers=env.h("member"))
    assert r.status_code == 200 and r.json()["meeting"]["project_id"] == другой


def test_участник_удаляет_пустую_встречу(env):
    mid = _встреча(env)
    r = env.delete(f"/meetings/{mid}", headers=env.h("member"))
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert env.st.get("meetings", mid) is None


def test_участник_удаляет_встречу_с_задачами_и_отменяет_удаление(env):
    mid = _встреча(env)
    tid = env.st.insert("tasks", project_id=env.pid, description="Подготовить график поставки", status="active",
                        source_meeting_id=mid, assignee="Сидорова Вера")
    r = env.delete(f"/meetings/{mid}?with_tasks=true", headers=env.h("member"))
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert env.st.get("meetings", mid)["deleted_at"], "удаление мягкое — встреча остаётся в базе"
    assert env.st.get("tasks", tid)["status"] == "dropped"
    back = env.post(f"/meetings/{mid}/restore", headers=env.h("member"))
    assert back.status_code == 200 and back.json()["restored"] is True
    assert env.st.get("tasks", tid)["status"] == "active" and not env.st.get("meetings", mid).get("deleted_at")


def test_статика_показывает_меню_всем(env):
    """Кнопка «…» в реестре рисуется по `canPrepare()` (любой вошедший), а не только админу."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static" / "nav.js").read_text(encoding="utf-8")
    assert '${canPrepare() ? `<span class="reg-menu-wrap proto-more-wrap"><button type="button" class="pl-more proto-more"' in js
    assert "if (!m || !canPrepare()) return;" in js
