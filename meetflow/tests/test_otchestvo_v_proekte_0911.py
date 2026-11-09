"""Правка отчества в общей «Команде» доходит до проекта без перезапуска (9–10.11.2026).

Владелица правит отчества в «Команде»; проектная «Команда» должна получить их, когда экран открывают, — без рестарта и без
двойника. Экран зовёт `GET /api/projects/{pid}/people`, и тот делает `sync_people`. Проверяем это на уровне API.
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
    uid = st.insert("accounts", full_name="Орлова Анна", role="super_admin", active=1, confirmed=1)
    c.pid, c.st, c.h = pid, st, {**W, "X-User-Id": str(uid), "X-Project-Id": str(pid)}
    return c


@pytest.fixture
def общая_команда(monkeypatch):
    """Что «пришло» из общей «Команды»: тест задаёт список, остальное — боевой путь sync_people."""
    from meetflow.core import team_sync

    state = {"люди": []}
    monkeypatch.setattr(team_sync, "shared_people", lambda *a, **k: state["люди"])
    return state


def _люди(c):
    return [r["full_name"] for r in c.st.q("SELECT full_name FROM people WHERE project_id=?", (c.pid,))]


def test_отчество_дописывается_при_открытии_команды(env, общая_команда):
    env.st.insert("people", project_id=env.pid, full_name="Иванов Пётр", confirmed=1)
    общая_команда["люди"] = [{"full_name": "Иванов Пётр Сергеевич"}]
    r = env.get(f"/api/projects/{env.pid}/people", headers=env.h)
    assert r.status_code == 200
    assert "Иванов Пётр Сергеевич" in [x["full_name"] for x in r.json()]
    assert _люди(env) == ["Иванов Пётр Сергеевич"], "дописано в существующую запись, без двойника"


def test_повторное_открытие_не_плодит_двойника(env, общая_команда):
    env.st.insert("people", project_id=env.pid, full_name="Иванов Пётр", confirmed=1)
    общая_команда["люди"] = [{"full_name": "Иванов Пётр Сергеевич"}]
    for _ in range(3):
        env.get(f"/api/projects/{env.pid}/people", headers=env.h)
    assert _люди(env) == ["Иванов Пётр Сергеевич"], "три открытия — одна запись"


def test_тёзка_с_другим_отчеством_остаётся_вторым_человеком(env, общая_команда):
    env.st.insert("people", project_id=env.pid, full_name="Иванов Пётр Сергеевич", confirmed=1)
    общая_команда["люди"] = [{"full_name": "Иванов Пётр Иванович"}]
    env.get(f"/api/projects/{env.pid}/people", headers=env.h)
    assert sorted(_люди(env)) == ["Иванов Пётр Иванович", "Иванов Пётр Сергеевич"]
