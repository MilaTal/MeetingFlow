"""Поиск встречи по имени (план, пункт 19; слово владелицы 08.11.2026 «поиск по имени только»).

Правило одно и на сервере: встреча находится по названию, без регистра и с «ё» = «е»; дата в имя не входит. Охват — тот
же, что у списка (выбранный проект или «Все проекты»), поэтому в поиске не всплывают встречи другого проекта.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meetflow.core import poisk_vstrech as пв

W = {"X-Requested-With": "erp-webapp"}


def test_по_имени_без_регистра_и_ё():
    assert пв.подходит({"label": "Работа с тендерами"}, "тендер")
    assert пв.подходит({"label": "Работа с тендерами"}, "ТЕНДЕР")
    assert пв.подходит({"label": "Выезд на склады, ещё раз"}, "еще")
    assert пв.подходит({"label": "  Работа   с тендерами  "}, "работа с")
    assert not пв.подходит({"label": "Работа с тендерами"}, "склады")


def test_дата_в_имя_не_входит():
    assert not пв.подходит({"label": "Работа с тендерами", "date": "2026-11-06"}, "06.11")
    assert not пв.подходит({"label": "Работа с тендерами", "date": "2026-11-06"}, "2026-11-06")


def test_пустой_запрос_ничего_не_даёт():
    assert пв.отобрать([{"label": "Работа с тендерами"}], "") == []
    assert пв.отобрать([{"label": "Работа с тендерами"}], "   ") == []


def test_не_больше_восьми_и_порядок_сохранён():
    встречи = [{"id": i, "label": f"Склад {i}"} for i in range(12)]
    отобрано = пв.отобрать(встречи, "склад")
    assert len(отобрано) == пв.МАКСИМУМ and [м["id"] for м in отобрано] == list(range(8))


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    p1 = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    p2 = st.insert("projects", name="Цех", theme="erp_rollout", archived=0)
    uid = st.insert("accounts", full_name="Орлова Анна", role="super_admin", active=1, confirmed=1)
    return {"c": c, "st": st, "p1": p1, "p2": p2, "h": {**W, "X-User-Id": str(uid)}}


def _встреча(env, pid, день, label):
    r = env["c"].post("/meetings", json={"date": день, "label": label},
                      headers={**env["h"], "X-Project-Id": str(pid)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_поиск_идёт_по_имени_и_в_охвате_проекта(env):
    _встреча(env, env["p1"], "2026-11-06", "Работа с тендерами")
    _встреча(env, env["p1"], "2026-11-03", "Выезд на склады")
    _встреча(env, env["p2"], "2026-11-05", "Работа с подрядчиками")

    def искать(q, pid):
        return env["c"].get("/meetings/search", params={"q": q},
                            headers={**env["h"], "X-Project-Id": str(pid)}).json()
    имена = [м["label"] for м in искать("работ", env["p1"])]
    assert имена == ["Работа с тендерами"], "чужая встреча проекта в поиск не попадает"
    assert искать("06.11", env["p1"]) == [], "дата в имя не входит"
    assert [м["label"] for м in искать("работ", 0)].count("Работа с тендерами") == 1
    assert len(искать("работ", 0)) == 2


def test_поиск_без_заголовка_проекта_ищет_по_всем(env):
    _встреча(env, env["p1"], "2026-11-06", "Работа с тендерами")
    _встреча(env, env["p2"], "2026-11-05", "Работа с подрядчиками")
    r = env["c"].get("/meetings/search", params={"q": "работ"}, headers=env["h"])
    assert r.status_code == 200 and len(r.json()) == 2


def test_метка_в_поиске_чистая(env):
    """«из папки-приёмника:» и хвост имени файла в выдаче не показываются (как в реестре встреч)."""
    env["st"].insert("meetings", project_id=env["p1"], date="2026-11-06", status="built",
                     label="из папки-приёмника: работа с тендерами 2026-11-06 11-59-7.m4a")
    rows = env["c"].get("/meetings/search", params={"q": "тендер"},
                        headers={**env["h"], "X-Project-Id": str(env["p1"])}).json()
    assert rows and "папки-приёмника" not in rows[0]["label"] and "m4a" not in rows[0]["label"]
