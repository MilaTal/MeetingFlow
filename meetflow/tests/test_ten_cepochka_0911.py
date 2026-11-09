"""Цепочка замера целиком: сборка → журнал тени → итоговый отчёт (план, пункт 28).

Проверки были по частям: `посчитать` отдельно, журнал отдельно, скрипт отдельно. Здесь одна сквозная: сборка на MockLLM
пишет строку тени со всеми полями (базовая линия, сравнение, цена, спорные пары), задачи не снимаются, а итоговый отчёт
читает эту строку и показывает числа. Денег нет — модель заглушка.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.config import load_theme
from meetflow.core.pipeline import MeetingPipeline

КОРЕНЬ = Path(__file__).resolve().parents[1]

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Петрова Анастасия, подготовьте график поставки труб к пятнице.\n"
          "[00:02:00] Игнатов Иван: И согласуйте график поставки труб с подрядчиком к пятнице.\n"
          "[00:03:00] Игнатов Иван: Отдельно подготовьте отчёт по складу.\n")


def _итог():
    путь = КОРЕНЬ / "scripts" / "zamer_v_ten_itog.py"
    spec = importlib.util.spec_from_file_location("zamer_v_ten_itog", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


class Модель(MockLLM):
    def _extract(self, data):
        return {"tasks": [
            {"description": "Подготовить график поставки труб", "assignee": "Петрова Анастасия", "line": 1,
             "due_date": "к пятнице"},
            {"description": "Подготовить отчёт по складу", "assignee": "Петрова Анастасия", "line": 3,
             "due_date": "к пятнице"}]}

    def _units(self, data):
        return {"items": []}


def test_сборка_журнал_отчёт(store, project, meeting, tmp_path, capsys):
    p = MeetingPipeline(load_theme("it_product"), store, default_registry(), Модель(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="цеп" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-09T10:00:00")
    p.run(project, meeting)

    журнал = tmp_path / "svedenie_ten.jsonl"
    assert журнал.is_file(), "сборка должна оставить строку тени"
    строки = [json.loads(s) for s in журнал.read_text(encoding="utf-8").splitlines() if s.strip()]
    assert len(строки) == 1
    строка = строки[0]
    assert строка["meeting_id"] == meeting and строка["чем"] == "сборка"
    assert строка["было"] >= 2 and строка["стало_бы"] <= строка["было"]
    assert строка["ошибочно_снятых"] == 0
    assert строка["сейчас"]["черновиков"] >= 1 and строка["сейчас"]["после_сборки"] >= 1
    assert "сейчас_рядом" in строка, "сравнение на том же наборе считается по умолчанию"
    assert строка["секунд"] >= 0

    # тень ничего не снимает: обе задачи сборки на месте и активны
    задачи = store.q("SELECT description FROM tasks WHERE source_meeting_id=? AND status='active'", (meeting,))
    assert len(задачи) == 2, [з["description"] for з in задачи]

    # итоговый отчёт читает эту же строку
    м = _итог()
    день = строка["at"][:10]
    код = м.main(["--журнал", str(журнал), "--с", день, "--по", день])
    вывод = capsys.readouterr().out
    assert код == 0, "рабочая строка за окно — отчёт собирается"
    assert "## Рабочие сборки" in вывод and f"| {meeting} |" in вывод
    assert "сверх набора" in вывод
