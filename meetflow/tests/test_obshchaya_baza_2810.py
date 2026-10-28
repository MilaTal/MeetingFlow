"""Общая база компании в MeetFlow (задание владелицы 28.10.2026): справочник проектов и внешние контакты «Команды»
Планёрки — только чтение, свой справочник главнее, включается флагом проекта «встречи общей тематики компании».
Данные вымышленные: база Планёрки собирается в tmp_path."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from meetflow.core import obshchaya_baza as ob, proekt_zapisi as pz, slovar_whisper, tablica_zadach, ukrupnenie_sborka
from meetflow.core import ukrupnenie_zadach as uz
from meetflow.core.prompts import PROFILES, PromptBuilder


def планёрка(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT, aliases TEXT, parent_id INTEGER, is_active BOOLEAN,
                               contract_chain TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, is_external BOOLEAN, organization TEXT,
                            confidence TEXT, is_active BOOLEAN, department TEXT);
    """)
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?)", [
        (1, "Севернефть", "«СНФ»", None, 1, "Северойл — Промснаб — Невалайн"),
        (2, "Верхнедонск", "", 1, 1, ""),                       # площадка Севернефти
        (3, "Склад", "", None, 1, ""),                           # есть в справочнике MeetFlow — свой главнее
        (4, "Заречье", "", 3, 1, ""),                            # площадка проекта, который у MeetFlow свой
        (5, "Старый объект", "", None, 0, ""),                   # снят
        (6, "Калуга261", "", None, 1, ""),
    ])
    con.executemany("INSERT INTO users (full_name, is_external, organization, confidence, is_active) VALUES (?,?,?,?,?)", [
        ("Брусникин Олег Петрович", 1, "Промснаб", "confirmed", 1),
        ("Ландышева Ирина", 1, "Северойл", "preliminary", 1),    # не подтверждена — не берётся
        ("Участник 86", 1, "", "confirmed", 1),                   # безличная метка
        ("Морошкин", 1, "Гидроузел", "confirmed", 1),             # одно слово — в подсказку только прозвучавший
        ("Клюквин Сергей Андреевич", 0, "", "confirmed", 1),      # свой сотрудник компании
        ("Черникова Анна", 1, "Промснаб", "confirmed", 0),        # снята
        ("Орлова Анна", 1, "Другая", "confirmed", 1),             # есть в «Команде» проекта — своя запись главнее
    ])
    con.commit()
    con.close()
    return path


@pytest.fixture
def база(store, tmp_path):
    ob._кэш.clear()
    путь = планёрка(tmp_path / "app.db")
    общ = store.insert("projects", name="Общие встречи", theme="erp_rollout")
    склад = store.insert("projects", name="Склад", theme="erp_rollout", aliases='["складской учёт"]')
    store.insert("people", project_id=общ, full_name="Орлова Анна", external=0, confirmed=1)
    store.set_setting(ob.НАСТРОЙКА_ПУТЬ, str(путь))
    store.set_setting(ob.НАСТРОЙКА_ТЕМАТИКА, True, общ)
    return {"путь": путь, "общ": общ, "склад": склад}


def test_выключено_без_флага_и_без_пути(store, база):
    assert ob.включена(store, база["склад"]) is False and ob.проекты(store, база["склад"]) == []
    store.set_setting(ob.НАСТРОЙКА_ПУТЬ, None)
    assert ob.включена(store, база["общ"]) is False and ob.люди(store, база["общ"]) == []
    store.set_setting(ob.НАСТРОЙКА_ПУТЬ, str(база["путь"].parent / "нет.db"))
    assert ob.включена(store, база["общ"]) is False
    assert "не найден" in ob.сводка(store)["error"]


def test_флаг_всем_проектам_и_подпроект_наследует(store, база):
    под = store.insert("projects", name="Приёмка", theme="erp_rollout", parent_id=база["склад"])
    store.set_setting(ob.НАСТРОЙКА_ТЕМАТИКА, True, база["склад"])
    assert ob.включена(store, под) is True
    store.set_setting(ob.НАСТРОЙКА_ТЕМАТИКА, False, база["склад"])
    assert ob.включена(store, под) is False
    store.set_setting(ob.НАСТРОЙКА_ВСЕМ, True)
    assert ob.включена(store, под) is True


def test_проекты_свой_главнее_площадки_и_снятые(store, база):
    пр = {п["name"]: п for п in ob.проекты(store, база["общ"])}
    assert set(пр) == {"Севернефть", "Верхнедонск", "Заречье", "Калуга261"}
    assert all(п["id"] < 0 for п in пр.values())                         # номера не пересекаются со своими
    assert пр["Верхнедонск"]["parent_id"] == пр["Севернефть"]["id"]
    assert пр["Заречье"]["parent_id"] == база["склад"]                     # площадка общей базы у своего «Склада»
    assert ob.названия_проектов(store, база["общ"])[:2] == ["Севернефть", "Севернефть – Верхнедонск"]


def test_свой_вариант_с_кодом_перекрывает_общий(store, база):
    store.insert("projects", name="Калуга", theme="erp_rollout")
    assert "Калуга261" not in {п["name"] for п in ob.проекты(store, база["общ"])}


def test_база_только_на_чтение(store, база):
    ob.проекты(store, база["общ"])
    con = sqlite3.connect(f"file:{база['путь'].as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO projects (name) VALUES ('x')")
    con.close()


def test_люди_только_подтверждённые_действующие_и_не_свои(store, база):
    лю = {з.full_name: з for з in ob.люди(store, база["общ"])}
    assert set(лю) == {"Брусникин Олег Петрович", "Морошкин", "Клюквин Сергей Андреевич"}
    assert лю["Брусникин Олег Петрович"].is_external and лю["Брусникин Олег Петрович"].organization == "Промснаб"
    assert not лю["Клюквин Сергей Андреевич"].is_external


def test_подсказка_внешних_по_правилу_звучания(store, база):
    без = ob.внешние_в_подсказку(store, база["общ"], ["Обсудили отгрузку."])
    assert len(без) == 1 and без[0].startswith("Брусникин Олег Петрович (Промснаб) [внешний контакт")
    с = ob.внешние_в_подсказку(store, база["общ"], ["Морошкину отправить письмо."])
    assert any(x.startswith("Морошкин (Гидроузел) [в «Команде» одно слово") for x in с)


def test_строка_проектов_в_подсказке_поручений(store, база):
    строка = ob.строка_проектов(store, база["общ"])
    assert строка.startswith("Проекты компании (для написания названий, НЕ источник фактов): Общие встречи; Склад;")
    assert "Севернефть – Верхнедонск" in строка
    assert ob.строка_проектов(store, база["склад"]) == ""
    _, user = PromptBuilder("", PROFILES["generic"]).extract_tasks(0, ["a"], ["Орлова Анна"], строка)
    assert "Севернефть" in user.split("\n\n")[0]
    _, прежний = PromptBuilder("", PROFILES["generic"]).extract_tasks(0, ["a"], ["Орлова Анна"])
    assert "Проекты компании" not in прежний


@pytest.mark.parametrize("путь, как", [
    ("Севернефть/встреча 20.10.2026.m4a", "Севернефть"),
    ("встреча СНФ 20.10.2026.m4a", "Севернефть"),
    ("Верхнедонск 20.10.2026.m4a", "Верхнедонск"),
])
def test_проект_записи_общей_базы_остаётся_проекту_папки(store, база, tmp_path, путь, как):
    общая = tmp_path / "Встречи по всем проектам"
    файл = общая / путь
    файл.parent.mkdir(parents=True, exist_ok=True)
    файл.write_bytes(b"x")
    итог = pz.проект_файла(store, база["общ"], общая, файл)
    assert итог["project_id"] == база["общ"] and как in итог["how"]


def test_проект_записи_свой_главнее_и_без_флага_как_было(store, база, tmp_path):
    общая = tmp_path / "Встречи по всем проектам"
    общая.mkdir()
    f = общая / "Склад и Севернефть 20.10.2026.m4a"
    f.write_bytes(b"x")
    assert pz.проект_файла(store, база["общ"], общая, f)["project_id"] == база["склад"]
    g = общая / "Севернефть 21.10.2026.m4a"
    g.write_bytes(b"x")
    store.set_setting(ob.НАСТРОЙКА_ТЕМАТИКА, False, база["общ"])
    assert pz.проект_файла(store, база["общ"], общая, g)["project_id"] is None


def test_семейства_укрупнения_и_словарь_распознавания(store, база):
    проекты, _ = tablica_zadach.справочники_укрупнения(store, база["общ"])
    assert uz.семейство("Верхнедонск", проекты) == ("Севернефть", "Верхнедонск")
    assert uz.семейство("Заречье", проекты) == ("Склад", "Заречье")
    без, _ = tablica_zadach.справочники_укрупнения(store, база["склад"])
    assert uz.семейство("Верхнедонск", без) == ("Верхнедонск", "")
    имена = slovar_whisper.имена_базы(store, база["общ"])
    assert имена.index("Склад") < имена.index("Севернефть")             # свои — раньше общей базы
    assert "Севернефть" not in slovar_whisper.имена_базы(store, база["склад"])


def test_контрагенты_общей_базы_в_укрупнении(store, база):
    сп = ukrupnenie_sborka._справочник(store, база["общ"])
    assert "Брусникин" in сп.люди and "Клюквин" not in сп.люди
    орг = {к for к, _ in сп.организации}
    assert {"Промснаб", "Северойл"} <= орг and "Северойл" not in {к for к, _ in ukrupnenie_sborka._справочник(
        store, база["склад"]).организации}
    assert uz.контрагенты_текста("Направить письмо в Промснаб по допсоглашению", сп) == frozenset({"Промснаб"})


def test_выключатели_через_api(tmp_path):
    from meetflow.web.app import create_app
    ob._кэш.clear()
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Общие встречи", theme="erp_rollout", archived=0)
    st.set_setting(ob.НАСТРОЙКА_ПУТЬ, str(планёрка(tmp_path / "app.db")))
    h = {"X-User-Role": "super_admin", "X-User-Name": "admin"}
    r = c.post(f"/api/projects/{pid}/settings/company-topic", json={"enabled": True}, headers=h)
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["projects_taken"] == 5
    общее = c.get("/api/settings/company-base", headers=h).json()
    assert общее["ok"] is True and общее["projects"][0]["company_topic"] is True
    assert c.post(f"/api/projects/{pid}/settings/company-topic", json={"enabled": False}, headers=h).json()["enabled"] \
        is False
    assert c.post("/api/settings/company-base/all", json={"enabled": True}, headers=h).json()["all_projects"] is True
    assert c.post(f"/api/projects/{pid}/settings/company-topic", json={"enabled": True},
                  headers={"X-User-Role": "member", "X-User-Name": "u"}).status_code in (401, 403)
