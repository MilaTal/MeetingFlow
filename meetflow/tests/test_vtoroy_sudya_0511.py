# -*- coding: utf-8 -*-
"""Второй судья в тень: один вызов на сборку, только журнал (записка 05.11.2026).

Выключатель `WEBAPP_VTOROY_SUDYA` по умолчанию выключен; включённый — зовёт модель один раз, пишет пары
в `vtoroy_sudya.jsonl` и ничего в реестре не меняет.
"""
import json
from types import SimpleNamespace

from meetflow.core import vtoroy_sudya
from meetflow.core.store import Store


def _store():
    s = Store(":memory:")
    pid = s.insert("projects", name="П", theme="_default")
    своя = s.insert("tasks", project_id=pid, description="Согласовать график поставок на ноябрь",
                    status="active", source_meeting_id=7, date_set="2026-11-03")
    чужая = s.insert("tasks", project_id=pid, description="Согласовать график поставок на ноябрь",
                     status="active", source_meeting_id=3, date_set="2026-10-20")
    разная = s.insert("tasks", project_id=pid, description="Закупить спецобувь для склада",
                      status="active", source_meeting_id=3, date_set="2026-10-20")
    return s, pid, своя, чужая, разная


def test_по_умолчанию_выключен(monkeypatch):
    monkeypatch.delenv(vtoroy_sudya.ПЕРЕМЕННАЯ, raising=False)
    assert vtoroy_sudya.включён() is False
    monkeypatch.setenv(vtoroy_sudya.ПЕРЕМЕННАЯ, "on")
    assert vtoroy_sudya.включён() is True


def test_пары_берут_свою_встречу_и_порог():
    s, pid, своя, чужая, разная = _store()
    пары = vtoroy_sudya.пары(s, pid, 7)
    assert [(п["a"], п["b"]) for п in пары] == [(своя, чужая)]
    assert пары[0]["score"] >= vtoroy_sudya.ПОРОГ


def test_прогнать_делает_один_вызов_и_пишет_журнал(tmp_path, monkeypatch):
    s, pid, своя, чужая, _ = _store()
    журнал = tmp_path / "llm_calls.jsonl"
    вызовов = []

    def _call(llm, budget, purpose, system, user, meeting_id):
        вызовов.append((purpose, meeting_id, user))
        return {"pairs": [{"n": 1, "answer": "одна", "why": "та же работа"}]}

    pipe = SimpleNamespace(s=s, gen=SimpleNamespace(model="тест"), journal=SimpleNamespace(path=журнал),
                           _call=_call)
    monkeypatch.setenv(vtoroy_sudya.ПЕРЕМЕННАЯ, "on")
    результат = vtoroy_sudya.прогнать(pipe, pid, 7, budget=None)
    assert len(вызовов) == 1 and вызовов[0][0] == "второй судья"
    строка = json.loads((tmp_path / "vtoroy_sudya.jsonl").read_text(encoding="utf-8").strip())
    assert строка["meeting_id"] == 7
    assert строка["pairs"][0]["answer"] == "одна" and строка["pairs"][0]["b"] == чужая
    assert результат["pairs"][0]["why"] == "та же работа"
    # реестр не тронут
    assert [t["status"] for t in s.q("SELECT status FROM tasks ORDER BY id")] == ["active", "active", "active"]


def test_выключенный_не_зовёт_модель(tmp_path, monkeypatch):
    s, pid, _, _, _ = _store()
    pipe = SimpleNamespace(s=s, gen=SimpleNamespace(model="тест"),
                           journal=SimpleNamespace(path=tmp_path / "llm_calls.jsonl"),
                           _call=lambda *a, **k: (_ for _ in ()).throw(AssertionError("вызова быть не должно")))
    monkeypatch.delenv(vtoroy_sudya.ПЕРЕМЕННАЯ, raising=False)
    assert "пропуск" in vtoroy_sudya.прогнать(pipe, pid, 7, budget=None)
    assert not (tmp_path / "vtoroy_sudya.jsonl").exists()


def test_сбой_судьи_не_выходит_наружу(tmp_path, monkeypatch):
    s, pid, _, _, _ = _store()
    pipe = SimpleNamespace(s=s, gen=SimpleNamespace(model="тест"),
                           journal=SimpleNamespace(path=tmp_path / "llm_calls.jsonl"),
                           _call=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("нет сети")))
    monkeypatch.setenv(vtoroy_sudya.ПЕРЕМЕННАЯ, "on")
    результат = vtoroy_sudya.прогнать(pipe, pid, 7, budget=None)
    assert "сбой" in результат and "нет сети" in результат["сбой"]
