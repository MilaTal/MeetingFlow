# -*- coding: utf-8 -*-
"""«Разбор голосов» — разница с ERP и «е» = «ё» (перенос 27.10.2026; DECISIONS ERP 26.10.2026 «Разбор голосов без
пустых строк, «Это он» по кандидату», «два почти равных кандидата у «не узнан»», «е и ё: оба написания принимаются»).

Модуль-близнец `core/voice_review.py` у MeetFlow уже совпадает с ERP main 2ea59c1 (строки только с отрывком или
репликой, `dva_kandidata`, `mesto_govoryashchego`, человек базы по ключу без «ё»). Здесь — то, что у ERP в роутере и на
экране: кандидат «в Команде», отказ «Это он» по имени не из «Команды», «Другой человек» — ФИО «Команды», выбор одного из
двух; и «е» = «ё» в оставшихся сравнениях MeetFlow. Базы голосов нет: ответы модуля подставлены.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.core import norm_yo, voice_review
from meetflow.core.people import Team
from meetflow.core.types import Person
from meetflow.web.app import create_app

SUPER = {"X-User-Role": "super_admin"}
ADMIN = {"X-User-Role": "project_admin"}


def _klaster(kandidat, second="", dva=False):
    return {"label": "Говорящий 3", "ref": "2026-10-01", "ids": [1, 2], "kandidat": kandidat, "cosine": 0.52,
            "second": second, "second_cosine": 0.50, "dva_kandidata": dva, "status": "none", "otpechatki": [],
            "vsego": 2}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("VOICE_BASE_PATH", raising=False)
    monkeypatch.setenv("TEAM_SHARED", "off")
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.store = app.state.store
    pid = c.post("/api/projects", json={"name": "П"}, headers=ADMIN).json()["id"]
    for n in ("Тихонов Денис Андреевич", "Королёв Пётр", "Широков Павел"):
        c.post(f"/api/projects/{pid}/people", json={"full_name": n, "confirm_new": True}, headers=ADMIN)
    c.store.set_setting("voice_base_path", str(tmp_path / "voices.db"))
    (tmp_path / "voices.db").write_bytes(b"")
    calls = []
    monkeypatch.setattr(voice_review, "ochered", lambda base: {"gruppy": [
        {"imya": "", "klastery": [_klaster("Тихонов Денис", "Широков Павел Игоревич", True),
                                  _klaster("Королев Петр"), _klaster("Неизвестный Человек")]}],
        "klasterov": 3, "bez_materiala": 0})
    monkeypatch.setattr(voice_review, "primenit",
                        lambda base, ids, decision, name, kto="": calls.append((decision, name)) or
                        {"razobrano": len(ids), "otryvkov_udaleno": 0, "klastery": []})
    c.calls = calls
    return c


def test_кандидат_в_команде_и_второй(env):
    d = env.get("/api/monitoring/voice-review", headers=SUPER).json()
    k1, k2, k3 = d["gruppy"][0]["klastery"]
    assert k1["kandidat_v_komande"] == "Тихонов Денис Андреевич", "фамилия и имя без тёзок — человек «Команды»"
    assert k1["vtoroy_v_komande"] == "Широков Павел"
    assert k2["kandidat_v_komande"] == "Королёв Пётр", "«е» = «ё» при поиске в «Команде»"
    assert k3["kandidat_v_komande"] == ""


def test_это_он_только_по_команде_другой_человек_фио_команды(env):
    r = env.post("/api/monitoring/voice-review/apply", json={"ids": [1], "decision": "yes",
                                                            "name": "Неизвестный Человек"}, headers=SUPER)
    assert r.status_code == 422 and "нет в «Команде» MeetFlow" in r.json()["detail"]
    r = env.post("/api/monitoring/voice-review/apply", json={"ids": [1], "decision": "yes", "name": "Тихонов Денис",
                                                            "vybran": "pervyy"}, headers=SUPER)
    assert r.status_code == 200 and r.json()["vybran"] == "pervyy"
    assert env.calls[-1] == ("yes", "Тихонов Денис"), "«Это он» — имя кандидата из базы голосов"
    env.post("/api/monitoring/voice-review/apply", json={"ids": [1], "decision": "other", "name": "Королев Петр"},
             headers=SUPER)
    assert env.calls[-1] == ("other", "Королёв Пётр"), "«Другой человек» — ФИО «Команды»"
    r = env.post("/api/monitoring/voice-review/apply", json={"ids": [1], "decision": "no", "vybran": "vtoroy"},
                 headers=SUPER)
    assert r.status_code == 422


def test_экран_два_кандидата_и_серая_кнопка():
    """С 27.10.2026 «Разбор голосов» — экран ERP 1 в 1: «Это он» по кандидату из «Команды», «Не он», «Другой человек»;
    строка «без материала» — только при N > 0."""
    js = (Path(__file__).resolve().parents[1] / "meetflow/web/static/app.js").read_text(encoding="utf-8")
    assert "kandidat_v_komande" in js and "vtoroy_v_komande" in js and ">Это он</button>" in js and ">Не он</button>" in js
    assert "нет в «Команде» полным ФИО — выберите в «Другой человек»" in js
    assert "д.bez_materiala > 0 ?" in js, "строка «без материала» — только при N > 0"


# --- «е» = «ё» -------------------------------------------------------------------------------------------------------

def test_модуль_близнец():
    assert norm_yo.без_ё("Королёв Пётр") == "Королев Петр" and norm_yo.равны("ООО «Артём»", "ооо «артем»")


def test_вариант_написания_человека():
    team = Team([Person("Смирнов Олег", aliases=["Олёг Смирнов"])])
    assert team.find("Олег Смирнов").person is not None


def test_внешний_той_же_организации_с_е(env):
    pid = env.store.q("SELECT id FROM projects")[0]["id"]
    r1 = env.post(f"/api/projects/{pid}/people", json={"full_name": "Иванов Иван", "external": True,
                                                       "organization": "ООО «Артём»", "role": "подрядчик"}, headers=ADMIN)
    r2 = env.post(f"/api/projects/{pid}/people", json={"full_name": "Иванов Иван", "external": True,
                                                       "organization": "ООО «Артем»", "role": "подрядчик"}, headers=ADMIN)
    assert r1.status_code == 200 and r2.status_code == 409
