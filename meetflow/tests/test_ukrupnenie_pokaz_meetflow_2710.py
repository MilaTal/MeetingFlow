"""Показ строк из реестра одной строкой в таблице протокола MeetFlow (ERP 3550fc6, решение владелицы 27.10.2026,
«Подпроекты + реестр», п. 2). Своё у MeetFlow: таблица хранится в тексте протокола, показ собирает строки в двери показа
(экран и Word); полотно правки строки не собирает; хранимый текст и реестр не меняются. Данные вымышленные.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meetflow.core import tablica_zadach as tz
from meetflow.core import ukrupnenie_zadach as u
from meetflow.core.registry import TaskRegistry


@pytest.fixture(autouse=True)
def _включено(monkeypatch):
    for v in (u.ПЕРЕМЕННАЯ, u.ПЕРЕМЕННАЯ_ПОДПРОЕКТЫ, u.ПЕРЕМЕННАЯ_ПОКАЗ):
        monkeypatch.delenv(v, raising=False)


def _сцена(store):
    куст = store.insert("projects", name="Северный куст", theme="erp_rollout")
    озёрная = store.insert("projects", name="Озёрная", theme="erp_rollout", parent_id=куст)
    каменный = store.insert("projects", name="Каменный", theme="erp_rollout", parent_id=куст)
    прошлая = store.insert("meetings", project_id=куст, date="2026-10-26")
    эта = store.insert("meetings", project_id=куст, date="2026-10-27")
    reg = TaskRegistry(store)
    a = reg.add(куст, "Принять акт по насосной", "Ершов Пётр", прошлая, "", None, "2026-10-26")
    b = reg.add(куст, "Проверить ограждение площадки", "Ершов Пётр", прошлая, "", None, "2026-10-26")
    c = reg.add(куст, "Заказать кабель", "Сомов Глеб", прошлая, "", None, "2026-10-26")
    new = reg.add(куст, "Согласовать график смен", "Ершов Пётр", эта, "", None, "2026-10-27")
    store.update("tasks", a, project_id=озёрная)
    store.update("tasks", b, project_id=каменный)
    return куст, эта, (a, b, c, new)


def _таблица(store, эта):
    m = store.get("meetings", эта)
    return "# Протокол\n\n" + "\n".join(tz.раздел_задач(tz.строки_встречи(store, m, lambda t: "")))


def test_строки_одного_исполнителя_по_подпроектам_одной_строкой(store):
    куст, эта, (a, b, c, new) = _сцена(store)
    md = _таблица(store, эта)
    показ = tz.укрупнить_показ(store, store.get("meetings", эта), md)
    строки = [ln for ln in показ.split("\n") if ln.startswith("| ") and not ln.startswith("| №")]
    assert len(строки) == 3                                   # новая задача, одна сводная строка, чужой исполнитель
    сводная = next(ln for ln in строки if "Северный куст:" in ln)
    assert f"(№{a})" in сводная and f"(№{b})" in сводная and "Озёрная — " in сводная and "Каменный — " in сводная
    assert "Согласовать график смен" in показ and "Заказать кабель" in показ
    assert [ln.split("|")[1].strip() for ln in строки] == ["1", "2", "3"]
    # реестр не меняется
    assert {t["id"] for t in store.q("SELECT id FROM tasks WHERE status='active'")} == {a, b, c, new}


def test_выключатель_показа(store, monkeypatch):
    _куст, эта, _ = _сцена(store)
    monkeypatch.setenv(u.ПЕРЕМЕННАЯ_ПОКАЗ, "off")
    md = _таблица(store, эта)
    assert tz.укрупнить_показ(store, store.get("meetings", эта), md) == md


def test_задача_под_вопросом_и_с_карточкой_сама_по_себе(store):
    куст, эта, (a, b, _c, _n) = _сцена(store)
    store.update("tasks", a, doubt_reason="исполнитель не прозвучал")
    md = _таблица(store, эта)
    assert tz.укрупнить_показ(store, store.get("meetings", эта), md) == md


def test_экран_и_word_собирают_полотно_нет(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    куст, эта, (a, b, _c, _n) = _сцена(st)
    st.update("meetings", эта, protocol_md=_таблица(st, эта), protocol_built_at="2026-10-27T12:00:00")
    sup = {"X-User-Role": "super_admin"}
    экран = c.get(f"/api/meetings/{эта}/protocol", headers=sup).json()["markdown"]
    assert f"(№{a})" in экран
    assert app.state.erp.shown(st.get("meetings", эта)["protocol_md"], куст).count("Ершов Пётр") == 3   # полотно
    assert "(№" not in st.get("meetings", эта)["protocol_md"]          # хранимый текст не тронут


def test_снятая_задача_подпроекта_не_видна_в_протоколе_проекта(tmp_path, monkeypatch):
    """Снятые задачи не показываются нигде (решение владелицы 26.10.2026) — и задача, переведённая в подпроект: скрытие
    берёт проект встречи вместе с подпроектами (27.10.2026). Экран обеих дверей, Word — той же дверью."""
    from meetflow.web.app import create_app
    monkeypatch.setenv(u.ПЕРЕМЕННАЯ_ПОКАЗ, "off")
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    куст, эта, (a, b, _c, new) = _сцена(st)
    st.update("tasks", new, project_id=st.q("SELECT id FROM projects WHERE name='Озёрная'")[0]["id"])
    st.update("meetings", эта, protocol_md=_таблица(st, эта), protocol_built_at="2026-10-27T12:00:00")
    assert "Согласовать график смен" in st.get("meetings", эта)["protocol_md"]
    TaskRegistry(st).set_status(new, __import__("meetflow.core.types", fromlist=["TaskStatus"]).TaskStatus.DROPPED,
                                "operator", "не нужна")
    sup = {"X-User-Role": "super_admin"}
    assert "Согласовать график смен" not in c.get(f"/api/meetings/{эта}/protocol", headers=sup).json()["markdown"]
    assert "Согласовать график смен" not in app.state.erp.shown(st.get("meetings", эта)["protocol_md"], куст)
    assert "Согласовать график смен" in st.get("meetings", эта)["protocol_md"]     # хранимый текст не тронут
