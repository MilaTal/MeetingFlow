"""Проверка полноты по выгрузке ВКС после сборки (записка 05.11.2026, п. 4; пункт 6 плана, шаг 3).

Окно выгрузки по 2 минуты, где есть признаки поручения (кому-то сделать и срок или дата), а в протоколе и реестре на это
время нет ни задачи, ни пункта, даёт карточку «Возможна потерянная задача, время …». Задачу из окна не заводят: слово
в фразе не делает факта. Вопрос и отрицание карточкой не становятся.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.pipeline import MeetingPipeline

СВОЯ = ("[00:01:00] Игнатов Иван: Начинаем по складу.\n"
        "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к пятнице.\n"
        "[00:03:00] Петрова Анастасия: Хорошо, сделаю.\n"
        "[00:10:30] Игнатов Иван: Дальше по складу, ничего нового.\n"
        "[00:11:30] Игнатов Иван: Заканчиваем.\n")
# Окно 10–12 мин есть только в выгрузке: в своём тексте этого обмена нет вовсе
ВЫГРУЗКА = ("[00:01:05] Игнатов Иван: Начинаем по складу.\n"
            "[00:02:10] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к 17-му.\n"
            "[00:10:20] Дупак Андрей: Колоночный профиль по Эль-Дабаа до пятницы подготовить, 5128.\n"
            "[00:11:30] Минеев Анатолий: Хорошо, возьму.\n")
ВЫГРУЗКА_БЕЗ_ПОРУЧЕНИЯ = ("[00:01:05] Игнатов Иван: Начинаем по складу.\n"
                           "[00:10:20] Дупак Андрей: Не будем ничего согласовывать до пятницы.\n"
                           "[00:11:30] Минеев Анатолий: А кто это будет делать?\n")


class Модель(MockLLM):
    def __init__(self, tasks=None):
        super().__init__()
        self.tasks = tasks or []

    def _extract(self, data):
        return {"tasks": self.tasks}

    def _units(self, data):
        return {"items": []}


def _сборка(store, project, meeting, theme, tmp_path, выгрузка=ВЫГРУЗКА):
    gen = Модель([{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                   "line": 2, "due_date": "к пятнице"}])
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=СВОЯ,
                 digest="w1" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-06T10:00:00")
    store.insert("sources", meeting_id=meeting, name="выгрузка ВКС", kind="transcript", text=выгрузка,
                 digest="w2" + str(meeting), local_asr=0, meta=json.dumps({}, ensure_ascii=False),
                 created_at="2026-11-06T10:05:00")
    rep = p.run(project, meeting)
    return p, rep


def _карточки_окон(store, meeting):
    return [dict(c) for c in store.q("SELECT * FROM cards WHERE meeting_id=? AND kind='held_task' AND title LIKE "
                                     "'Возможна потерянная задача%'", (meeting,))]


def test_окно_без_задачи_даёт_карточку(store, project, meeting, theme, tmp_path):
    _p, _rep = _сборка(store, project, meeting, theme, tmp_path)
    карточки = _карточки_окон(store, meeting)
    assert len(карточки) == 1, [c["title"] for c in карточки]
    c = карточки[0]
    assert c["title"] == "Возможна потерянная задача, время 10:00–12:00"
    payload = json.loads(c["payload"])
    assert payload["from"] == "выгрузка ВКС" and payload["reasons"] == ["vks_window"]
    assert "Колоночный профиль" in payload["description"] and "5128" in payload["description"]
    assert payload["window"] == "10:00–12:00"


def test_из_окна_задачу_не_заводят(store, project, meeting, theme, tmp_path):
    _p, _rep = _сборка(store, project, meeting, theme, tmp_path)
    задачи = store.q("SELECT description FROM tasks WHERE source_meeting_id=?", (meeting,))
    assert [t["description"] for t in задачи] == ["Подготовить регламент склада"]
    assert not any("Колоночный профиль" in t["description"] for t in задачи)


def test_отрицание_и_вопрос_карточкой_не_становятся(store, project, meeting, theme, tmp_path):
    _p, _rep = _сборка(store, project, meeting, theme, tmp_path, выгрузка=ВЫГРУЗКА_БЕЗ_ПОРУЧЕНИЯ)
    assert _карточки_окон(store, meeting) == []


def test_без_выгрузки_проверка_молчит(store, project, meeting, theme, tmp_path):
    gen = Модель([{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                   "line": 2, "due_date": "к пятнице"}])
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=СВОЯ,
                 digest="w3" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-06T10:00:00")
    p.run(project, meeting)
    assert _карточки_окон(store, meeting) == []
