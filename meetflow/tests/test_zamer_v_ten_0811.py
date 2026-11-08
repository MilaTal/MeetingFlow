"""Замер В: тень сведения считается и пишет журнал, задачи не снимаются (вариант C, слово владелицы 06.11.2026).

Найдено 08.11.2026: тень не считалась ни разу — запрос прежних задач встречи брал несуществующую колонку `quote`, и
каждая сборка писала в итог «тень не посчиталась: no such column: quote». Здесь держится три вещи: строка журнала есть,
задачи остаются на месте, ошибочно снятых 0.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import svedenie_ten
from meetflow.core.pipeline import MeetingPipeline

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте график поставки труб к пятнице.\n"
          "[00:03:00] Игнатов Иван: И график поставки труб согласуйте с подрядчиком до среды.\n"
          "[00:04:00] Петрова Анастасия: Хорошо, сделаю.\n")


class Модель(MockLLM):
    def _extract(self, data):
        return {"tasks": [
            {"description": "Подготовить график поставки труб", "assignee": "Петрова Анастасия", "line": 2,
             "due_date": "к пятнице"},
            {"description": "Согласовать график поставки труб с подрядчиком", "assignee": "Петрова Анастасия",
             "line": 3, "due_date": "до среды"},
        ]}

    def _units(self, data):
        return {"items": []}


def test_тень_считает_и_пишет_журнал(store, project, meeting, theme, tmp_path):
    p = MeetingPipeline(theme, store, default_registry(), Модель(), MockLLM(),
                        journal_path=tmp_path / "llm_calls.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="t1" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-05T10:00:00")
    rep = p.run(project, meeting)
    assert rep.svedenie_ten.startswith("тень:"), rep.svedenie_ten          # не «тень не посчиталась»
    строки = [json.loads(x) for x in (tmp_path / "svedenie_ten.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(строки) == 1
    строка = строки[0]
    assert строка["meeting_id"] == meeting and строка["ошибочно_снятых"] == 0
    # сколько задач встречи тень увидела (после штатного укрупнения их может быть и одна) — главное, что счёт
    # состоялся: прежде он падал на несуществующей колонке `quote` и строки не было вовсе
    assert строка["было"] >= 1 and строка["чем"] == "сборка"
    # базовая линия рабочей сборки (08.11): без неё не видно, добавляет ли способ 1 что-то сверх обычного сведения
    assert строка["сейчас"]["черновиков"] >= 1 and строка["сейчас"]["после_сборки"] >= 1
    assert строка["сейчас"]["после_сборки"] <= строка["сейчас"]["черновиков"]
    assert isinstance(строка.get("секунд"), (int, float)) and строка["секунд"] >= 0
    задачи = store.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='active'", (meeting,))
    assert len(задачи) == 1, "тень задачи не снимает: в реестре то, что завела сборка"


def test_посчитать_не_меняет_список():
    задачи = [{"description": "Подготовить график поставки труб"},
              {"description": "Согласовать график поставки труб"}]
    счёт = svedenie_ten.посчитать(задачи)
    assert счёт["ошибочно_снятых"] == 0 and счёт["групп"] == 1 and счёт["объединено_бы"] == 1
    assert len(задачи) == 2                      # входной список не тронут
