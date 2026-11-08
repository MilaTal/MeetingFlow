"""Путь единиц встречи до базы: ответ модели → `UnitsExtractor` → общий сторож задач → `units.apply`.

Записка машине разработчика `917f51e` и ответ `10605c1`, п. 2: тест этого пути делается вместе с правками конвейера.
Здесь проверяется, что задача, найденная в единицах, а не в списке поручений, проходит те же ворота и попадает в реестр
с исполнителем, а единица — в таблицу `units` со своей цитатой и строками; отказ сторожа даёт карточку, а не тишину.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.pipeline import MeetingPipeline

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте график поставки труб к пятнице.\n"
          "[00:03:00] Петрова Анастасия: Хорошо, сделаю.\n"
          "[00:04:00] Сидоров Пётр: Решили: поставки идут по средам.\n")

ЕДИНИЦЫ = [
    {"kind": "Задача", "statement": "Подготовить график поставки труб к пятнице",
     "lines": ["2"], "responsible": ["Петрова Анастасия"]},
    {"kind": "Решение", "statement": "Поставки идут по средам", "lines": ["4"]},
]


class Модель(MockLLM):
    """Заглушка: поручений списком нет вовсе — все задачи приходят только из единиц."""

    def __init__(self, items=None):
        super().__init__()
        self.items = ЕДИНИЦЫ if items is None else items

    def _extract(self, data):
        return {"tasks": []}

    def _units(self, data):
        return {"items": self.items}

    def _units_close(self, system, data):
        return {"closed": []}


def _сборка(store, project, meeting, theme, tmp_path, items=None):
    gen = Модель(items)
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="запись 01.10.2026", kind="transcript", text=ЗАПИСЬ,
                 digest="u" + str(meeting), meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-10-01T10:00:00")
    return p, p.run(project, meeting)


def test_задача_из_единиц_попадает_в_реестр_с_исполнителем(store, project, meeting, theme, tmp_path):
    _p, rep = _сборка(store, project, meeting, theme, tmp_path)
    задачи = store.q("SELECT * FROM tasks WHERE source_meeting_id=? ORDER BY id", (meeting,))
    assert len(задачи) == 1, [t["description"] for t in задачи]
    assert задачи[0]["assignee"] == "Петрова Анастасия"
    assert "график поставки труб" in задачи[0]["description"].lower()
    assert "подготовьте" in (задачи[0]["source_quote"] or "").lower()
    assert rep.units_tasks == 1 and rep.units_added == 1


def test_решение_из_единиц_сохраняется_цитатой_и_строками(store, project, meeting, theme, tmp_path):
    _p, _rep = _сборка(store, project, meeting, theme, tmp_path)
    единицы = store.q("SELECT * FROM units WHERE meeting_id=?", (meeting,))
    assert len(единицы) == 1
    u = единицы[0]
    assert u["kind"] == "decision" and "средам" in u["text"]
    assert "поставки идут по средам" in (u["quote"] or "").lower()
    # место в записи хранится номером строки источника с нуля (`rows[0].src`): четвёртая строка записи
    assert (u["line_from"], u["line_to"]) == (3, 3)


def test_отказ_сторожа_даёт_карточку_а_не_тишину(store, project, meeting, theme, tmp_path):
    # «Кузнецов Олег» назван, но в «Команде» его нет: документ 14 — новый человек карточкой, задача заведена
    items = [{"kind": "Задача", "statement": "Проверить отчёт по браку", "lines": ["2"],
              "responsible": ["Кузнецов Олег"]}]
    запись = ("[00:01:00] Игнатов Иван: Начинаем.\n"
              "[00:02:00] Игнатов Иван: Кузнецов Олег, проверьте отчёт по браку.\n"
              "[00:03:00] Кузнецов Олег: Принял, проверю.\n")
    gen = Модель(items)
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="запись 01.10.2026", kind="transcript", text=запись,
                 digest="v" + str(meeting), meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-10-01T10:00:00")
    p.run(project, meeting)
    задачи = store.q("SELECT * FROM tasks WHERE source_meeting_id=?", (meeting,))
    assert len(задачи) == 1 and задачи[0]["assignee"] == "Кузнецов Олег"
    карточки = store.q("SELECT * FROM cards WHERE kind='confirm_person' AND status='open'")
    assert карточки and карточки[0]["meeting_id"] == meeting
