"""Объект рядом с поручением (пункт 8 плана, находка замера 05.11.2026).

В выгрузке ВКС объект назван за минуту до разговора о работе («Прокал Эльдаба… Колоночный профиль мы уже приняли»),
модель объект в формулировку не вписала. Код дописывает объект, если он один и его нет в описании; два объекта —
карточка, описание не меняется.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import obekt_ryadom as ор
from meetflow.core.pipeline import MeetingPipeline

СВОЯ = ("[00:55:46] Людмила Тальянова: Прокал Эльдаба, да.\n"
        "[00:56:37] Станислав Очкивский: Колоночный профиль мы уже приняли, можно уже передавать на производство.\n"
        "[00:57:10] Антон Майдуров: Хорошо.\n")
ВЫГРУЗКА = ("[00:55:46] Людмила Тальянова: Прокал Эльдаба, да.\n"
            "[00:56:37] Станислав Очкивский: Колоночный профиль мы уже приняли, можно уже передавать на производство.\n")


class Модель(MockLLM):
    def _extract(self, data):
        return {"tasks": [{"description": "Передать колоночный профиль на производство",
                           "assignee": None, "line": 2}]}

    def _units(self, data):
        return {"items": []}


def _сборка(store, project, meeting, theme, tmp_path, выгрузка=ВЫГРУЗКА, модель=None):
    p = MeetingPipeline(theme, store, default_registry(), модель or Модель(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=СВОЯ,
                 digest="o1" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-05T09:00:00")
    if выгрузка is not None:
        store.insert("sources", meeting_id=meeting, name="выгрузка ВКС", kind="transcript", text=выгрузка,
                     digest="o2" + str(meeting), local_asr=0, meta=json.dumps({}, ensure_ascii=False),
                     created_at="2026-11-05T09:05:00")
    p.run(project, meeting)
    return st_задачи(store, meeting)


def st_задачи(store, meeting):
    return [dict(r) for r in store.q("SELECT description FROM tasks WHERE source_meeting_id=? ORDER BY id", (meeting,))]


def test_объект_после_маркера_и_из_справочника():
    окно = "Прокал Эльдаба, да. Колоночный профиль мы уже приняли."
    assert "Эльдаба" in ор.объекты_в_окне(окно)
    справочник = [{"name": "Эль-Дабаа", "aliases": []}]
    assert "Эль-Дабаа" in ор.объекты_в_окне("Сегодня по Эльдаба согласовали профиль", справочник)


def test_один_объект_дописывается():
    итог = ор.с_объектом("Передать колоночный профиль на производство", "Прокал Эльдаба, да.")
    assert итог["описание"].endswith("— объект Эльдаба") and not итог["сомнительно"]


def test_объект_уже_назван_не_дописывается():
    итог = ор.с_объектом("Передать профиль Эльдаба на производство", "Прокал Эльдаба, да.")
    assert итог["описание"] == "Передать профиль Эльдаба на производство"


def test_два_объекта_карточка_описание_не_меняется():
    итог = ор.с_объектом("Передать профиль на производство", "Прокал Эльдаба. Объект Курск, срок тот же.")
    assert итог["сомнительно"] and итог["описание"] == "Передать профиль на производство"


def test_сборка_дописывает_объект_в_задачу(store, project, meeting, theme, tmp_path):
    задачи = _сборка(store, project, meeting, theme, tmp_path)
    assert задачи and задачи[0]["description"] == "Передать колоночный профиль на производство — объект Эльдаба"


def test_без_выгрузки_объекта_нет(store, project, meeting, theme, tmp_path):
    задачи = _сборка(store, project, meeting, theme, tmp_path, выгрузка=None)
    assert задачи and задачи[0]["description"] == "Передать колоночный профиль на производство"


def test_два_объекта_дают_карточку(store, project, meeting, theme, tmp_path):
    выгрузка = ("[00:55:46] Людмила Тальянова: Прокал Эльдаба, да. Объект Курск сдвинули.\n"
                "[00:56:37] Станислав Очкинский: Колоночный профиль мы уже приняли, можно уже передавать.\n")
    задачи = _сборка(store, project, meeting, theme, tmp_path, выгрузка=выгрузка)
    assert задачи[0]["description"] == "Передать колоночный профиль на производство"
    карточки = store.q("SELECT payload FROM cards WHERE meeting_id=? AND title LIKE 'Объект рядом%'", (meeting,))
    assert карточки, "два объекта — карточка оператору"
    объекты = json.loads(карточки[0]["payload"])["объекты"]
    assert set(объекты) >= {"Эльдаба", "Курск"}
