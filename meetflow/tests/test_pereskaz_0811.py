"""Пересказ ИИ не берём вовсе (слово владелицы 06.11.2026, перенос п. 1 записок ERP).

Пересказ может быть ошибочным и выложен по ошибке: в сборку, задачи, карточки, поиск и сверку он не идёт, лежит
материалом. Заслон — в приёмнике и на ручной загрузке (один путь `Pipeline.ingest`), плюс запасной путь «других
источников» его не берёт.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import pereskaz
from meetflow.core.pipeline import MeetingPipeline

ПЕРЕСКАЗ = ("Пересказ Планёрка 05.11.2026\n\n"
            "Краткое содержание встречи, сделанное ИИ.\n"
            "[00:02:00] Петрова Анастасия: подготовит регламент склада к пятнице.\n")
ЖИВАЯ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная, вопросов нет.\n"
         "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к пятнице.\n"
         "[00:03:00] Петрова Анастасия: Хорошо, сделаю к пятнице.\n")


def _труба(store, theme, tmp_path):
    return MeetingPipeline(theme, store, default_registry(), MockLLM(), MockLLM(),
                           journal_path=tmp_path / "llm_calls.jsonl")


def test_пересказ_по_имени_и_по_тексту():
    assert pereskaz.это_пересказ("Пересказ Планёрка 05.11.2026.txt")
    assert pereskaz.это_пересказ("ПЕРЕСКАЗ встречи.txt", "")
    assert pereskaz.это_пересказ("встреча.txt", "Пересказ\n\nКратко о встрече…")
    assert pereskaz.это_пересказ("встреча.txt", "Конспект встречи: обсудили склад.")
    assert not pereskaz.это_пересказ("Транскрипция 05.11.2026.txt", ЖИВАЯ)
    assert not pereskaz.это_пересказ("Отчёт 06.11.2026.txt", "Обсудили пересказ коллеги на встрече.")


def test_приёмник_делает_пересказ_материалом(store, project, meeting, theme, tmp_path):
    p = _труба(store, theme, tmp_path)
    res = p.ingest(project, meeting, "Пересказ Планёрка 05.11.2026.txt", ПЕРЕСКАЗ.encode("utf-8"))
    assert res["status"] == "ok" and res["kind"] == "other", res
    источник = store.q("SELECT kind, meta, text FROM sources WHERE meeting_id=?", (meeting,))[0]
    assert источник["kind"] == "other"
    assert pereskaz.помечен(источник["meta"])
    журнал = tmp_path / "llm_calls.jsonl"
    строки = [json.loads(x) for x in журнал.read_text(encoding="utf-8").splitlines()] if журнал.exists() else []
    assert any(r.get("purpose") == "pereskaz" for r in строки), "строка в журнал — след заслона"


def test_пересказ_не_становится_источником_сборки(store, project, meeting, theme, tmp_path):
    p = _труба(store, theme, tmp_path)
    p.ingest(project, meeting, "Пересказ Планёрка 05.11.2026.txt", ПЕРЕСКАЗ.encode("utf-8"))
    rep = p.run(project, meeting)
    assert rep.status == "no_sources", rep.detail          # источников нет: пересказ — материал
    assert store.q("SELECT id FROM tasks WHERE source_meeting_id=?", (meeting,)) == []


def test_живая_расшифровка_остаётся_источником(store, project, meeting, theme, tmp_path):
    p = _труба(store, theme, tmp_path)
    res = p.ingest(project, meeting, "Транскрипция 05.11.2026.txt", ЖИВАЯ.encode("utf-8"))
    assert res["status"] == "ok" and res["kind"] == "transcript", res
